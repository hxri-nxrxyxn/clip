"""Shared UI components, formatters, and job control helpers for Streamlit views."""

import time
from pathlib import Path
from typing import Any

import streamlit as st

from app import pipeline

STATUS_COLORS = {
    "complete": "green",
    "succeeded": "green",
    "running": "primary",
    "ready": "orange",
    "blocked": "red",
    "scaffold": "gray",
    "past": "gray",
    "current": "green",
    "failed": "red",
}

STATUS_ICONS = {
    "complete": ":material/check_circle:",
    "succeeded": ":material/check_circle:",
    "running": ":material/autorenew:",
    "ready": ":material/play_circle:",
    "blocked": ":material/error:",
    "scaffold": ":material/construction:",
    "past": ":material/history:",
    "current": ":material/radio_button_checked:",
    "failed": ":material/error:",
}


def size_label(value: float | int | None) -> str:
    val = float(value or 0)
    if val < 1024:
        return f"{int(val)} B"
    if val < 1024 * 1024:
        return f"{val / 1024:.1f} KB"
    if val < 1024 * 1024 * 1024:
        return f"{val / 1024 / 1024:.1f} MB"
    return f"{val / 1024 / 1024 / 1024:.1f} GB"


def time_label(value: str | None) -> str:
    if not value:
        return "—"
    return value[:16].replace("T", " ")


def status_badge(status: str) -> None:
    st.badge(
        status,
        icon=STATUS_ICONS.get(status, ":material/info:"),
        color=STATUS_COLORS.get(status, "gray"),  # type: ignore[arg-type]
    )


def files_markdown(items: list[dict[str, Any]] | None, limit: int = 10) -> str:
    if not items:
        return "No files."
    lines = []
    for item in items[:limit]:
        path = item.get("path", "")
        name = Path(path).name or path
        exists = bool(item.get("exists", True))
        icon = ":material/check_circle:" if exists else ":material/error:"
        details = size_label(item.get("size", 0))
        if not exists:
            details = "missing · " + details
        lines.append(f"- {icon} **{name}** — {details}")
    if len(items) > limit:
        lines.append(f"- … {len(items) - limit} more")
    return "\n".join(lines)


def markdown_pairs(pairs: list[tuple[str, Any]]) -> str:
    return "\n".join(f"- **{key}:** {value}" for key, value in pairs)


def job_picker() -> dict[str, Any] | None:
    jobs = pipeline.jobs()
    if not jobs:
        st.caption("No jobs yet.")
        return None
    ids = [job["id"] for job in jobs]
    labels = {job["id"]: job["label"] for job in jobs}
    marker = pipeline.current_job() or {}
    preferred = pipeline.current_run_id() or marker.get("job_id")
    pending = st.session_state.pop("pending_job_id", None)
    if pending in ids:
        st.session_state["job_picker_widget"] = pending
    if (
        "job_picker_widget" not in st.session_state
        or st.session_state["job_picker_widget"] not in ids
    ):
        st.session_state["job_picker_widget"] = preferred if preferred in ids else ids[0]
    selected = st.selectbox(
        "Job",
        ids,
        key="job_picker_widget",
        format_func=lambda job_id: labels.get(job_id, job_id),
    )
    st.session_state["selected_job_id"] = selected
    return next(job for job in jobs if job["id"] == selected)


def job_url(job: dict[str, Any]) -> str:
    video = job.get("video") or {}
    ingest = job.get("ingest") or {}
    url = (
        video.get("url")
        or ingest.get("webpage_url")
        or ingest.get("source_url")
        or job.get("url")
        or ""
    )
    return str(url)


def archive_items(files: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [
        {"path": file.get("name", ""), "exists": True, "size": file.get("size", 0)}
        for file in files or []
    ]


def job_log(job: dict[str, Any], stage_id: str) -> dict[str, Any] | None:
    if not job.get("is_current"):
        return None
    return pipeline.JOBS.latest(stage_id) or pipeline.JOBS.latest("pipeline")


def render_running_log() -> bool:
    active = pipeline.JOBS.current()
    if not active:
        return False
    st.subheader(":material/terminal: Live log")
    log = st.empty()
    while active["status"] == "running":
        active = pipeline.JOBS.get(active["id"])
        log.code(active["log_tail"] or "Waiting for output…", language="text")
        if active["status"] != "running":
            break
        time.sleep(1.0)
    if active["stage"] == "pipeline":
        if active["status"] == "succeeded":
            run_id = pipeline.archive_current_run()
            if run_id:
                pipeline.mark_current_run(run_id)
                pipeline.update_current_job("succeeded")
                st.session_state["pending_job_id"] = run_id
            else:
                pipeline.update_current_job("failed")
        else:
            pipeline.update_current_job("failed")
    else:
        marker = pipeline.current_job() or {}
        if marker.get("job_id") == active["id"]:
            pipeline.update_current_job(active["status"])
    st.rerun()
    return True


def start_full_job(url: str) -> None:
    try:
        target = pipeline.validate_target(url)
    except ValueError as exc:
        st.error(str(exc))
        return
    pipeline.archive_current_run()
    try:
        job = pipeline.JOBS.start(
            "pipeline", ["bash", str(pipeline.APP_DIR / "pipeline_job.sh"), target]
        )
    except RuntimeError as exc:
        st.warning(str(exc))
        return
    pipeline.set_current_job(job["id"], target)
    st.rerun()


def start_stage_job(job: dict[str, Any], stage_id: str, url: str | None = None) -> None:
    run_id = job.get("run_id")
    if not run_id:
        st.error("Cannot re-run stage without an archived run_id.")
        return
    try:
        pipeline.prepare_stage_workspace(run_id, stage_id)
        cmd = ["bash", str(pipeline.APP_DIR / "stage_job.sh"), stage_id, run_id]
        if url:
            cmd.append(pipeline.validate_target(url))
        active = pipeline.JOBS.start(stage_id, cmd)
    except (OSError, ValueError, RuntimeError) as exc:
        st.error(str(exc))
        return
    pipeline.set_current_job(active["id"], job_url(job), run_id=run_id)
    st.rerun()


def start_targeted_job(job: dict[str, Any], use_llm: bool = True) -> None:
    run_id = job.get("run_id")
    if not run_id:
        st.error("Cannot run targeted selection without an archived run_id.")
        return
    args = [run_id]
    if not use_llm:
        args.append("--no-llm")
    try:
        active = pipeline.JOBS.start(
            "targeted", ["bash", str(pipeline.APP_DIR / "targeted_job.sh"), *args]
        )
    except RuntimeError as exc:
        st.warning(str(exc))
        return
    pipeline.start_targeted_run(run_id)
    pipeline.set_current_job(active["id"], job_url(job), run_id=run_id)
    st.rerun()


def render_previews(previews: list[dict[str, str]] | None, title: str = "Previews") -> None:
    if not previews:
        return
    with st.expander(title, expanded=False):
        for item in previews:
            st.markdown(f"**{item.get('label', 'Preview')}**")
            st.code(item.get("text", ""), language="text")


def render_detail_expanders(
    source_pairs: list[tuple[str, Any]],
    source_items: list[dict[str, Any]],
    output_items: list[dict[str, Any]],
    general_pairs: list[tuple[str, Any]],
    log_job: dict[str, Any] | None = None,
) -> None:
    with st.expander("Details", expanded=False):
        st.markdown(markdown_pairs(general_pairs))
        st.divider()
        st.markdown("**Source**")
        st.markdown(markdown_pairs(source_pairs))
        st.markdown(files_markdown(source_items))
        st.divider()
        st.markdown("**Outputs**")
        st.markdown(files_markdown(output_items))
        if log_job and log_job.get("log_tail"):
            st.divider()
            st.markdown("**Stage log tail**")
            st.code(log_job["log_tail"], language="text")
