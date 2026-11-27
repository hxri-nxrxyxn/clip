"""Targeted clip selection and review view."""

import streamlit as st

from app import pipeline
from app.views._shared import (
    archive_items,
    files_markdown,
    job_log,
    job_picker,
    render_previews,
    render_running_log,
    start_targeted_job,
    status_badge,
)


def render_targeted(targeted: dict, log_job: dict | None = None) -> None:
    if not targeted:
        return
    status = targeted.get("status")
    st.subheader(":material/hearing: Targeted transcription")
    st.caption(
        "YAMNet finds laughter, screaming, and shouting, Whisper transcribes "
        "only those windows, and Qwen picks the clip boundaries."
    )
    if status:
        status_badge(status)
    if status == "failed":
        st.error(targeted.get("error") or "Targeted run failed.")
    summary = targeted.get("summary") or {}
    metrics = [
        ("candidates", summary.get("candidates", 0)),
        ("selections", summary.get("selections", 0)),
        ("segments", summary.get("segments", 0)),
        ("words", summary.get("words", 0)),
        (
            "whisper",
            f"{summary.get('targeted_whisper_seconds') or 0:.1f}s",
        ),
        ("qwen", f"{summary.get('llm_seconds') or 0:.1f}s"),
        ("total", f"{summary.get('total_seconds') or 0:.1f}s"),
        ("qwen ready", "yes" if summary.get("llm_ready") else "no"),
    ]
    for column, (label, value) in zip(st.columns(4), metrics[:4]):
        column.metric(label, value)
    for column, (label, value) in zip(st.columns(4), metrics[4:]):
        column.metric(label, value)
    selections = targeted.get("selections") or []
    if selections:
        st.dataframe(
            [
                {
                    "candidate": item.get("candidate_id"),
                    "start": pipeline.clock(item.get("start") or 0),
                    "end": pipeline.clock(item.get("end") or 0),
                    "seconds": round(
                        float(item.get("end") or 0) - float(item.get("start") or 0), 1
                    ),
                    "peak score": item.get("peak_score"),
                    "qwen": "yes" if item.get("llm_used") else "no",
                    "reason": item.get("reason") or "",
                }
                for item in selections
            ],
            hide_index=True,
            width="stretch",
        )
    render_previews(targeted.get("previews") or [], title="Targeted previews")
    with st.expander("Targeted files & log", expanded=False):
        st.markdown(files_markdown(archive_items(targeted.get("files") or [])))
        if log_job:
            st.caption("Latest targeted log")
            st.code(log_job["log_tail"][-4000:] or "No output.", language="text")


def render() -> None:
    job = job_picker()
    if render_running_log():
        return
    st.title("Select")
    st.caption("YAMNet-guided targeted transcription and Qwen clip selection.")
    if not job:
        st.caption("No jobs yet. Create one from History.")
        return
    detail = pipeline.job_detail(job["id"])
    if not detail:
        st.caption("No archived data for this job yet.")
        return
    run_id = job.get("run_id")
    video = detail.get("video") or {}
    st.caption(video.get("title") or job["label"])
    busy = pipeline.JOBS.current() is not None
    has_audio = bool(run_id and (pipeline.HISTORY_DIR / run_id / "audio16k_full.wav").is_file())
    use_llm = st.toggle(
        "Use Qwen for clip selection",
        value=True,
        help="Turn off to use peak-centered clip selection instead.",
    )
    if st.button(
        "Run targeted selection",
        icon=":material/hearing:",
        disabled=busy or not has_audio,
    ):
        start_targeted_job(job, use_llm=use_llm)
    if not has_audio:
        st.caption("This job has no archived audio for targeted selection.")
    targeted = detail.get("targeted")
    if targeted:
        render_targeted(targeted, log_job=job_log(job, "targeted"))
    else:
        st.caption("No targeted selection yet.")
