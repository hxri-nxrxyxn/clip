"""Qwen selection findings over YAMNet-targeted transcripts."""

from pathlib import Path

import streamlit as st

from app import pipeline
from app.views._shared import (
    archive_items,
    files_markdown,
    job_log,
    job_picker,
    render_previews,
    render_running_log,
    start_selection_job,
    start_visual_job,
    status_badge,
)


def render_selection(selection: dict, log_job: dict | None = None) -> None:
    if not selection:
        return
    status = selection.get("status")
    st.subheader(":material/psychology: Qwen selection")
    st.caption("Qwen analyzes the targeted transcript and chooses the best clips.")
    if status:
        status_badge(status)
    if status == "failed":
        st.error(selection.get("error") or "Selection failed.")
    summary = selection.get("summary") or {}
    metrics = [
        ("candidates", summary.get("candidates", 0)),
        ("selections", summary.get("selections", 0)),
        ("qwen", f"{summary.get('llm_seconds') or 0:.1f}s"),
        ("total", f"{summary.get('total_seconds') or 0:.1f}s"),
        ("qwen ready", "yes" if summary.get("llm_ready") else "no"),
    ]
    for column, (label, value) in zip(st.columns(5), metrics):
        column.metric(label, value)
    selections = selection.get("selections") or []
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
    render_previews(selection.get("previews") or [], title="Qwen findings")
    with st.expander("Selection files & log", expanded=False):
        st.markdown(files_markdown(archive_items(selection.get("files") or [])))
        if log_job:
            st.caption("Latest selection log")
            st.code(log_job["log_tail"][-4000:] or "No output.", language="text")


def render_visual(visual: dict, log_job: dict | None = None) -> None:
    if not visual:
        return
    status = visual.get("status")
    st.subheader(":material/theaters: Visual story")
    st.caption(
        "Contact sheets sampled chronologically from selected clips, "
        "reviewed by the local vision model."
    )
    if status:
        status_badge(status)
    if status == "failed":
        st.error(visual.get("error") or "Visual analysis failed.")
    summary = visual.get("summary") or {}
    metrics = [
        ("clips", summary.get("clips", 0)),
        ("vlm clips", summary.get("vlm_clips", 0)),
        ("avg visual", summary.get("average_visual_score", 0)),
        ("vlm ready", "yes" if visual.get("vlm_ready") else "no"),
    ]
    for column, (label, value) in zip(st.columns(4), metrics):
        column.metric(label, value)
    for clip in visual.get("clips") or []:
        candidate = clip.get("candidate_id")
        with st.expander(
            f"Clip #{candidate} · "
            f"{pipeline.clock(clip.get('start') or 0)}-"
            f"{pipeline.clock(clip.get('end') or 0)}",
            expanded=False,
        ):
            sheet = clip.get("contact_sheet_path")
            if sheet and Path(sheet).is_file():
                st.image(sheet, width="stretch")
            else:
                st.caption("Contact sheet missing.")
            if clip.get("summary"):
                st.markdown(f"**{clip['summary']}**")
            sequence = clip.get("sequence") or []
            if sequence:
                st.markdown("\n".join(f"- {item}" for item in sequence))
            score_columns = st.columns(2)
            score_columns[0].metric("Visual score", clip.get("visual_score", 0))
            score_columns[1].metric(
                "Transcript support", clip.get("transcript_support", 0)
            )
            flags = clip.get("flags") or []
            if flags:
                st.caption("Flags: " + ", ".join(str(flag) for flag in flags))
            if clip.get("reason"):
                st.caption(clip["reason"])
    with st.expander("Visual files & log", expanded=False):
        st.markdown(files_markdown(archive_items(visual.get("files") or [])))
        if log_job:
            st.caption("Latest visual log")
            st.code(log_job["log_tail"][-4000:] or "No output.", language="text")


def render_rankings(rankings: list[dict], visual_present: bool) -> None:
    if not rankings:
        return
    st.subheader(":material/emoji_events: Best moments")
    st.caption(
        "Ranked by a blend of YAMNet trigger strength, Qwen transcript match, "
        "VLM visual score, and event type. Click columns to re-sort."
    )
    top_overall = rankings[0]
    top_funny = max(rankings, key=lambda item: item.get("funny", 0))
    st.info(
        f"Best overall: clip #{top_overall['candidate_id']} "
        f"({top_overall['overall']:.1f}) · "
        f"Funniest: clip #{top_funny['candidate_id']} "
        f"({top_funny['funny']:.1f})"
    )
    st.dataframe(
        [
            {
                "rank": item.get("rank"),
                "clip": item.get("candidate_id"),
                "start": pipeline.clock(item.get("start") or 0),
                "end": pipeline.clock(item.get("end") or 0),
                "sec": item.get("duration"),
                "overall": item.get("overall"),
                "funny": item.get("funny"),
                "action": item.get("action"),
                "match": item.get("match"),
                "visual": item.get("visual_score"),
                "support": item.get("transcript_support"),
                "events": item.get("events"),
                "summary": item.get("summary"),
            }
            for item in rankings
        ],
        hide_index=True,
        width="stretch",
    )
    if not visual_present:
        st.caption("Run visual analysis to include VLM visual scores in the ranking.")


def render() -> None:
    job = job_picker()
    if render_running_log():
        return
    st.title("Select")
    st.caption("Qwen findings over the YAMNet-targeted transcript.")
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
    extraction = detail.get("targeted")
    selection = detail.get("selection")
    if extraction:
        summary = extraction.get("summary") or {}
        st.caption(
            f"Targeted extraction: {summary.get('candidates', 0)} candidates, "
            f"{summary.get('segments', 0)} segments, "
            f"{summary.get('words', 0)} words."
        )
    else:
        st.warning("Targeted extraction is missing. Run it from the Transcribe page first.")

    busy = pipeline.JOBS.current() is not None
    use_llm = st.toggle(
        "Use Qwen",
        value=True,
        help="Turn off to use peak-centered fallback selection.",
    )
    if st.button(
        "Run Qwen selection",
        icon=":material/psychology:",
        disabled=busy or not run_id or not extraction,
    ):
        start_selection_job(job, use_llm=use_llm)
    if selection:
        render_selection(selection, log_job=job_log(job, "3-select"))
    elif extraction:
        st.caption("No Qwen selection yet.")

    visual = detail.get("visual")
    use_vlm = st.toggle(
        "Use vision model",
        value=True,
        help="Turn off to create contact sheets without VLM descriptions.",
    )
    if st.button(
        "Analyze frames with VLM",
        icon=":material/theaters:",
        disabled=busy or not run_id or not selection,
    ):
        start_visual_job(job, use_vlm=use_vlm)
    if visual:
        render_visual(visual, log_job=job_log(job, "visual"))
    elif selection:
        st.caption("No visual story yet.")

    rankings = detail.get("rankings") or []
    render_rankings(rankings, bool(visual))
