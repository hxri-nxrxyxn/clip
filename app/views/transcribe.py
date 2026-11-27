"""Transcribe view for speech-to-text, audio tags, and activity visualization."""

import altair as alt
import pandas as pd
import streamlit as st

from app import pipeline
from app.views._shared import (
    archive_items,
    job_log,
    job_picker,
    job_url,
    render_detail_expanders,
    render_previews,
    render_running_log,
    start_stage_job,
    start_targeted_job,
)
from app.views.select import render_targeted


def chart_axes(chart: alt.Chart) -> alt.Chart:
    return (
        chart.configure_axis(
            gridColor="#d3d2ca",
            labelColor="#8a8570",
            titleColor="#3d3a2a",
            domainColor="#d3d2ca",
        )
        .configure_view(strokeOpacity=0)
        .configure_legend(labelColor="#8a8570", titleColor="#3d3a2a")
    )


def render_activity_charts(data: dict) -> None:
    minutes = pd.DataFrame(data["minutes"])
    heat = pd.DataFrame(data["heatmap"])
    labels = [item["time"] for item in data["bins"]]
    step = max(1, len(labels) // 12)
    visible_labels = labels[::step]
    metric_order = [
        "Loudness",
        "Speech",
        "Loud",
        "Laughter",
        "Screaming",
        "Shouting",
        "Music",
    ]
    heatmap = (
        alt.Chart(heat)
        .mark_rect()
        .encode(
            x=alt.X(
                "time:O",
                sort=labels,
                axis=alt.Axis(title="Time", labelAngle=-45, values=visible_labels),
            ),
            y=alt.Y("metric:N", sort=metric_order, title=None),
            color=alt.Color(
                "value:Q",
                scale=alt.Scale(scheme="tealblues", domain=[0, 1]),
                legend=alt.Legend(title="activity"),
            ),
            tooltip=[
                alt.Tooltip("time:N", title="Time"),
                alt.Tooltip("metric:N", title="Metric"),
                alt.Tooltip("raw:Q", title="Raw", format=".2f"),
                alt.Tooltip("value:Q", title="Normalized", format=".2f"),
            ],
        )
        .properties(height=280)
    )
    st.subheader("Activity heatmap")
    st.caption("Each row is normalized. Darker means more activity.")
    st.altair_chart(chart_axes(heatmap), width="stretch")

    left, right = st.columns([1.15, 1])
    with left:
        st.subheader("Activity by minute")
        bars = (
            alt.Chart(minutes)
            .mark_bar(color="#0ea5e9", cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
            .encode(
                x=alt.X(
                    "time:O",
                    sort=minutes["time"].tolist(),
                    axis=alt.Axis(title="Minute", labelAngle=-45),
                ),
                y=alt.Y("activity:Q", title="Activity index"),
                tooltip=[
                    alt.Tooltip("time:N", title="Minute"),
                    alt.Tooltip("activity:Q", format=".2f"),
                    alt.Tooltip("words:Q", title="Words"),
                    alt.Tooltip("loud:Q", title="Loud windows"),
                ],
            )
            .properties(height=250)
        )
        st.altair_chart(chart_axes(bars), width="stretch")

    with right:
        st.subheader("Loudness over time")
        loudness = heat[heat["metric"] == "Loudness"]
        base = alt.Chart(loudness).encode(
            x=alt.X(
                "time:O",
                sort=labels,
                axis=alt.Axis(title="Time", labelAngle=-45, values=visible_labels),
            ),
            y=alt.Y("raw:Q", title="Loudness (dB relative)"),
            tooltip=[
                alt.Tooltip("time:N", title="Time"),
                alt.Tooltip("raw:Q", title="dB", format=".1f"),
            ],
        )
        area = base.mark_area(color="#059669", opacity=0.10)
        line = base.mark_line(color="#059669", strokeWidth=2)
        points = base.mark_circle(color="#fbbf24", size=18)
        st.altair_chart(chart_axes(area + line + points), width="stretch")

    st.subheader("Highest-activity minutes")
    top = minutes.sort_values("activity", ascending=False).head(10)
    with st.container(border=True):
        st.dataframe(
            top[
                [
                    "time",
                    "activity",
                    "words",
                    "loud",
                    "laugh",
                    "scream",
                    "shout",
                    "music",
                ]
            ],
            hide_index=True,
            width="stretch",
        )


def render() -> None:
    job = job_picker()
    if render_running_log():
        return
    if not job:
        st.title("Transcribe")
        st.caption("No jobs yet. Create one from History.")
        return
    if job.get("status") == "failed" and not job.get("run_id"):
        st.title("Transcribe")
        st.error("Last job failed.")
        latest = pipeline.JOBS.latest("pipeline")
        if latest:
            with st.expander("Last job log", expanded=False):
                st.code(latest["log_tail"][-4000:] or "No output.", language="text")
        return
    detail = pipeline.job_detail(job["id"])
    if not detail:
        st.title("Transcribe")
        if job.get("status") == "failed":
            st.error("Last job failed.")
            latest = pipeline.JOBS.latest("pipeline")
            if latest:
                with st.expander("Last job log", expanded=False):
                    st.code(latest["log_tail"][-4000:] or "No output.", language="text")
        else:
            st.caption("No archived data for this job yet.")
        return

    video = detail.get("video") or {}
    st.title("Transcribe")
    st.caption(video.get("title") or job["label"])
    if job.get("status") == "failed":
        st.caption("Last run failed. See the log under Files & logs.")
    files = detail.get("files") or []
    audio = [item for item in files if item.get("name") == "audio16k_full.wav"]
    busy = pipeline.JOBS.current() is not None
    targeted_mode = st.toggle(
        "Targeted transcribe (YAMNet + Qwen)",
        value=False,
        help=(
            "Find laughter, screaming, and shouting with YAMNet, transcribe only "
            "those windows, and let Qwen choose the clip boundaries."
        ),
    )
    use_llm = True
    if targeted_mode:
        use_llm = st.toggle(
            "Use Qwen for clip selection",
            value=True,
            help="Turn off to use peak-centered clip selection instead.",
        )
        st.caption(
            "Runs on the archived audio. Qwen falls back to peak-centered "
            "selection if the local server is unavailable."
        )
    if st.button(
        "Run targeted transcribe" if targeted_mode else "Re-run transcribe for this job",
        icon=":material/hearing:" if targeted_mode else ":material/graphic_eq:",
        disabled=busy or not audio,
    ):
        if targeted_mode:
            start_targeted_job(job, use_llm=use_llm)
        else:
            start_stage_job(job, "2-transcribe")
    if not audio:
        st.caption("This job has no archived audio for re-running transcribe.")

    data = detail.get("activity")
    if data:
        render_activity_charts(data)
    else:
        st.caption("No activity data for this job.")

    render_previews(detail.get("previews") or [], title="Previews")
    targeted = detail.get("targeted")
    if targeted:
        render_targeted(targeted, log_job=job_log(job, "targeted"))
    else:
        st.caption("No targeted transcription yet.")
    output_files = [
        item
        for item in files
        if item.get("name")
        not in {"audio16k_full.wav", "ingest.json", "source.info.json", "run.json"}
    ]
    summary = detail.get("summary") or {}
    render_detail_expanders(
        [
            ("title", video.get("title") or "—"),
            ("url", job_url(job) or "—"),
            ("duration", pipeline.clock(video.get("duration") or 0)),
        ],
        archive_items(audio),
        archive_items(output_files),
        [
            ("words", summary.get("words", 0)),
            ("segments", summary.get("segments", 0)),
            ("tags", summary.get("tags", 0)),
            ("transcript lines", summary.get("transcript_lines", 0)),
            ("tagged lines", summary.get("tagged_lines", 0)),
            ("vtt cues", summary.get("vtt_cues", 0)),
            ("model", summary.get("model", "—")),
        ],
        log_job=job_log(job, "2-transcribe"),
    )
