"""Transcribe view for speech-to-text, audio tags, and activity visualization."""

import altair as alt
import pandas as pd
import streamlit as st

from app import pipeline
from app.views._shared import (
    archive_items,
    files_markdown,
    job_log,
    job_picker,
    job_url,
    render_detail_expanders,
    render_previews,
    render_running_log,
    start_stage_job,
    start_targeted_extract_job,
    status_badge,
)


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


def render_targeted_extract(targeted: dict, log_job: dict | None = None) -> None:
    if not targeted:
        return
    status = targeted.get("status")
    st.subheader(":material/content_cut: Targeted extraction")
    st.caption(
        "YAMNet candidate windows are transcribed with offsets. "
        "Qwen selection happens later in the Select stage."
    )
    if status:
        status_badge(status)
    if status == "failed":
        st.error(targeted.get("error") or "Targeted extraction failed.")
    summary = targeted.get("summary") or {}
    metrics = [
        ("candidates", summary.get("candidates", 0)),
        ("segments", summary.get("segments", 0)),
        ("words", summary.get("words", 0)),
        ("whisper", f"{summary.get('targeted_whisper_seconds') or 0:.1f}s"),
        ("total", f"{summary.get('total_seconds') or 0:.1f}s"),
    ]
    for column, (label, value) in zip(st.columns(5), metrics):
        column.metric(label, value)
    candidates = targeted.get("candidates") or []
    if candidates:
        st.dataframe(
            [
                {
                    "candidate": item.get("id"),
                    "window start": pipeline.clock(item.get("window_start") or 0),
                    "window end": pipeline.clock(item.get("window_end") or 0),
                    "peak score": item.get("peak_score"),
                    "types": ", ".join(sorted((item.get("types") or {}).keys())),
                }
                for item in candidates
            ],
            hide_index=True,
            width="stretch",
        )
    render_previews(targeted.get("previews") or [], title="Extraction previews")
    with st.expander("Extraction files & log", expanded=False):
        st.markdown(files_markdown(archive_items(targeted.get("files") or [])))
        if log_job:
            st.caption("Latest extraction log")
            st.code(log_job["log_tail"][-4000:] or "No output.", language="text")


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
    left, right = st.columns(2)
    with left:
        if st.button(
            "Re-run full transcribe",
            icon=":material/graphic_eq:",
            disabled=busy or not audio,
            width="stretch",
        ):
            start_stage_job(job, "2-transcribe")
    with right:
        if st.button(
            "Run targeted extraction",
            icon=":material/content_cut:",
            disabled=busy or not audio,
            width="stretch",
        ):
            start_targeted_extract_job(job)
    st.caption(
        "Targeted extraction transcribes only YAMNet candidate windows. "
        "Qwen selection runs on the Select page."
    )
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
        render_targeted_extract(targeted, log_job=job_log(job, "targeted-extract"))
    else:
        st.caption("No targeted extraction yet.")
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
