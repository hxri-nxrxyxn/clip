"""Ingest view for starting jobs and fetching media."""

import json

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
    start_full_job,
    start_stage_job,
    time_label,
)


def render() -> None:
    job = job_picker()
    if render_running_log():
        return
    st.title("Ingest")
    st.caption("Start a new job, or re-run ingest for the selected job.")

    with st.container(border=True):
        st.subheader(":material/add_circle: New job")
        url = st.text_input(
            "Video URL or local media path",
            key="new_job_url",
            placeholder="https://… or path/to/media",
        )
        if st.button(
            "Start new job",
            type="primary",
            icon=":material/play_arrow:",
            width="stretch",
        ):
            start_full_job(url)

    if not job:
        return
    if job.get("status") == "failed" and not job.get("run_id"):
        st.error("Last job failed.")
        latest = pipeline.JOBS.latest("pipeline")
        if latest:
            with st.expander("Last job log", expanded=False):
                st.code(latest["log_tail"][-4000:] or "No output.", language="text")
        return
    detail = pipeline.job_detail(job["id"])
    if not detail:
        if job.get("status") == "failed":
            st.error("Last job failed.")
            latest = pipeline.JOBS.latest("pipeline")
            if latest:
                with st.expander("Last job log", expanded=False):
                    st.code(latest["log_tail"][-4000:] or "No output.", language="text")
        return

    video = detail.get("video") or {}
    ingest = detail.get("ingest") or {}
    source_url = job_url(job)
    st.subheader(video.get("title") or job["label"])
    if job.get("status") == "failed":
        st.caption("Last run failed. See the log under Files & logs.")
    st.caption(
        " · ".join(
            value
            for value in [
                source_url,
                f"duration {pipeline.clock(video.get('duration') or 0)}",
                video.get("uploader") or "",
            ]
            if value
        )
    )

    busy = pipeline.JOBS.current() is not None
    if st.button(
        "Re-run ingest for this job",
        icon=":material/download:",
        disabled=busy or not source_url,
    ):
        start_stage_job(job, "1-ingest", source_url)
    if not source_url:
        st.caption("This job has no reusable source URL.")

    st.divider()
    render_previews(
        [{"label": "Ingest manifest", "text": json.dumps(ingest, indent=1)}],
        title="Previews",
    )
    render_detail_expanders(
        [
            ("title", video.get("title") or "—"),
            ("url", source_url or "—"),
            ("uploader", video.get("uploader") or "—"),
            ("duration", pipeline.clock(video.get("duration") or 0)),
        ],
        archive_items(detail.get("files") or []),
        [],
        [
            ("sample rate", ingest.get("sample_rate", "—")),
            ("channels", ingest.get("channels", "—")),
            ("codec", ingest.get("codec", "—")),
            ("updated", time_label(detail.get("updated_at") or detail.get("archived_at"))),
        ],
        log_job=job_log(job, "1-ingest"),
    )
