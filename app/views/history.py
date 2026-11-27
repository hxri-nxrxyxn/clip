"""History view for past jobs and archived runs."""

import streamlit as st

from app import pipeline
from app.views._shared import (
    archive_items,
    job_picker,
    job_url,
    render_detail_expanders,
    render_previews,
    start_full_job,
    time_label,
)
from app.views.select import render_selection, render_visual
from app.views.transcribe import render_activity_charts, render_targeted_extract


def render_history_details(job: dict) -> None:
    detail = pipeline.job_detail(job["id"])
    if not detail:
        st.caption("No archived data for this job.")
        return
    video = detail.get("video") or {}
    st.subheader(video.get("title") or job["label"])
    st.caption(
        " · ".join(
            value
            for value in [
                job_url(job),
                f"duration {pipeline.clock(video.get('duration') or 0)}",
                video.get("uploader") or "",
                f"updated {time_label(detail.get('updated_at') or detail.get('archived_at'))}",
            ]
            if value
        )
    )
    render_previews(detail.get("previews") or [], title="Previews")
    targeted = detail.get("targeted")
    if targeted:
        render_targeted_extract(targeted)
    selection = detail.get("selection")
    if selection:
        render_selection(selection)
    visual = detail.get("visual")
    if visual:
        render_visual(visual)
    summary = detail.get("summary") or {}
    render_detail_expanders(
        [
            ("title", video.get("title") or "—"),
            ("url", job_url(job) or "—"),
            ("uploader", video.get("uploader") or "—"),
            ("duration", pipeline.clock(video.get("duration") or 0)),
        ],
        archive_items(detail.get("files") or []),
        [],
        [
            ("words", summary.get("words", 0)),
            ("transcript lines", summary.get("transcript_lines", 0)),
            ("tagged lines", summary.get("tagged_lines", 0)),
            ("vtt cues", summary.get("vtt_cues", 0)),
        ],
    )
    if detail.get("activity"):
        with st.expander("Activity", expanded=False):
            render_activity_charts(detail["activity"])


def render() -> None:
    job = job_picker()
    st.title("History")
    st.caption("Past jobs. The current job is excluded from this list.")
    entries = pipeline.history()
    busy = pipeline.JOBS.current() is not None

    left, right = st.columns([2, 1])
    with left, st.container(border=True):
        st.subheader(":material/history: Past jobs")
        if entries:
            rows = [
                {
                    "job": (entry.get("video") or {}).get("title") or entry.get("run_id"),
                    "duration": pipeline.clock((entry.get("video") or {}).get("duration") or 0),
                    "updated": time_label(entry.get("updated_at") or entry.get("archived_at")),
                    "words": (entry.get("summary") or {}).get("words", 0),
                    "tagged lines": (entry.get("summary") or {}).get("tagged_lines", 0),
                    "targeted": (entry.get("targeted") or {}).get("status") or "—",
                    "selection": (entry.get("selection") or {}).get("status") or "—",
                    "visual": (entry.get("visual") or {}).get("status") or "—",
                }
                for entry in entries
            ]
            event = st.dataframe(
                rows,
                hide_index=True,
                width="stretch",
                on_select="rerun",
                selection_mode="single-row",
                key="history_table",
            )
            selected_rows = event.selection.rows
            if selected_rows:
                st.session_state["pending_job_id"] = entries[selected_rows[0]]["run_id"]
        else:
            st.caption("No past jobs yet.")
    with right, st.container(border=True):
        st.subheader(":material/add_circle: New job")
        st.caption("Start from a new video or audio source.")
        if st.button(
            "Create new job",
            type="primary",
            icon=":material/add:",
            width="stretch",
        ):
            st.session_state["nav_to"] = "ingest"
            st.rerun()
        if job:
            url = job_url(job)
            if st.button(
                "Run again",
                icon=":material/replay:",
                disabled=busy or not url,
                width="stretch",
            ):
                start_full_job(url)

    if job and job.get("is_current"):
        st.divider()
        st.caption(
            "The current job is not shown as a past job. Open Ingest or Transcribe to work with it."
        )

    if job and not job.get("is_current"):
        st.divider()
        render_history_details(job)
