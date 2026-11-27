import json
import sys
import time
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import pipeline

st.set_page_config(page_title="clip", layout="wide", initial_sidebar_state="expanded")

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


def size_label(value):
    value = float(value or 0)
    if value < 1024:
        return f"{int(value)} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KB"
    if value < 1024 * 1024 * 1024:
        return f"{value / 1024 / 1024:.1f} MB"
    return f"{value / 1024 / 1024 / 1024:.1f} GB"


def time_label(value):
    if not value:
        return "—"
    return value[:16].replace("T", " ")


def status_badge(status):
    st.badge(
        status,
        icon=STATUS_ICONS.get(status, ":material/info:"),
        color=STATUS_COLORS.get(status, "gray"),
    )


def files_markdown(items, limit=10):
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


def markdown_pairs(pairs):
    return "\n".join(f"- **{key}:** {value}" for key, value in pairs)


def job_picker():
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
        st.session_state["job_picker_widget"] = (
            preferred if preferred in ids else ids[0]
        )
    selected = st.selectbox(
        "Job",
        ids,
        key="job_picker_widget",
        format_func=lambda job_id: labels.get(job_id, job_id),
    )
    st.session_state["selected_job_id"] = selected
    return next(job for job in jobs if job["id"] == selected)


def job_url(job):
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


def archive_items(files):
    return [
        {"path": file.get("name", ""), "exists": True, "size": file.get("size", 0)}
        for file in files or []
    ]


def job_log(job, stage_id):
    if not job.get("is_current"):
        return None
    return pipeline.JOBS.latest(stage_id) or pipeline.JOBS.latest("pipeline")


def render_running_log():
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
            pipeline.update_current_job(active["status"])
    else:
        marker = pipeline.current_job()
        if marker and marker.get("job_id") == active["id"]:
            pipeline.update_current_job(active["status"])
    st.rerun()
    return True


def start_full_job(url):
    argv = ["bash", "app/pipeline_job.sh"]
    marker = pipeline.current_job() or {}
    if marker.get("run_id"):
        pipeline.archive_current_run()
    value = url.strip()
    if value:
        try:
            argv.append(pipeline.validate_target(value))
        except ValueError as exc:
            st.error(str(exc))
            return
    elif not (pipeline.ROOT / "1-ingest" / "input" / "url.txt").exists():
        st.error("Enter a URL, or add one to 1-ingest/input/url.txt.")
        return
    try:
        job = pipeline.JOBS.start("pipeline", argv)
    except RuntimeError as exc:
        st.warning(str(exc))
        return
    pipeline.set_current_job(job["id"], value)
    st.session_state["pending_job_id"] = job["id"]
    st.switch_page(INGEST_PAGE)


def start_stage_job(job, stage_id, url=None):
    run_id = job.get("run_id")
    if not run_id:
        st.error("This job has no archived data yet.")
        return
    argv = ["bash", "app/stage_job.sh", stage_id, run_id]
    if url:
        argv.append(url)
    if stage_id == "2-transcribe" and not (pipeline.HISTORY_DIR / run_id / "audio16k_full.wav").is_file():
        st.error("This job has no archived audio for transcribe.")
        return
    try:
        active = pipeline.JOBS.start(stage_id, argv)
    except RuntimeError as exc:
        st.warning(str(exc))
        return
    pipeline.set_current_job(active["id"], job_url(job), run_id=run_id)
    st.rerun()


def start_targeted_job(job, use_llm=True):
    run_id = job.get("run_id")
    if not run_id:
        st.error("This job has no archived data yet.")
        return
    if not (pipeline.HISTORY_DIR / run_id / "audio16k_full.wav").is_file():
        st.error("This job has no archived audio for targeted transcribe.")
        return
    argv = ["bash", "app/targeted_job.sh", run_id]
    if not use_llm:
        argv.append("--no-llm")
    pipeline.start_targeted_run(run_id)
    try:
        active = pipeline.JOBS.start("targeted", argv)
    except RuntimeError as exc:
        pipeline.mark_targeted_failed(run_id, exc)
        st.warning(str(exc))
        return
    pipeline.set_current_job(active["id"], job_url(job), run_id=run_id)
    st.rerun()


def stage_general(stage_id, state):
    pairs = [("ready", "yes" if state["ready"] else "no")]
    pairs.extend(
        (str(key).replace("_", " "), value)
        for key, value in state["summary"].items()
    )
    return pairs


def render_previews(previews, title="Previews"):
    if not previews:
        return
    st.subheader(f":material/visibility: {title}")
    for preview in previews:
        if not preview["text"]:
            continue
        with st.expander(preview["label"], expanded=False):
            st.code(preview["text"], language="text")


def render_targeted(targeted, log_job=None):
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
            f'{summary.get("targeted_whisper_seconds") or 0:.1f}s',
        ),
        ("qwen", f'{summary.get("llm_seconds") or 0:.1f}s'),
        ("total", f'{summary.get("total_seconds") or 0:.1f}s'),
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


def render_detail_expanders(source_pairs, source_items, output_items, general_pairs, log_job=None):
    with st.expander("Source", expanded=False):
        st.markdown(markdown_pairs(source_pairs))
    with st.expander("Files & logs", expanded=False):
        st.markdown(files_markdown(source_items + output_items))
        if log_job:
            st.caption("Latest log")
            st.code(log_job["log_tail"][-4000:] or "No output.", language="text")
    with st.expander("General", expanded=False):
        st.markdown(markdown_pairs(general_pairs))


def chart_axes(chart):
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


def render_activity_charts(data):
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


def render_ingest():
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
                f'duration {pipeline.clock(video.get("duration") or 0)}',
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


def render_transcribe():
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


def render_scaffold(stage_id):
    job = job_picker()
    stage = pipeline.STAGES[stage_id]
    st.title(stage["title"])
    st.caption(stage["description"])
    if job:
        st.caption(job["label"])
    st.caption("This stage is a scaffold and is not implemented yet.")


def render_history_details(job):
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
                f'duration {pipeline.clock(video.get("duration") or 0)}',
                video.get("uploader") or "",
                f'updated {time_label(detail.get("updated_at") or detail.get("archived_at"))}',
            ]
            if value
        )
    )
    render_previews(detail.get("previews") or [], title="Previews")
    targeted = detail.get("targeted")
    if targeted:
        render_targeted(targeted)
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


def render_history():
    job = job_picker()
    st.title("History")
    st.caption("Past jobs. The current job is excluded from this list.")
    entries = pipeline.history()
    busy = pipeline.JOBS.current() is not None

    left, right = st.columns([2, 1])
    with left:
        with st.container(border=True):
            st.subheader(":material/history: Past jobs")
            if entries:
                rows = [
                    {
                        "job": (entry.get("video") or {}).get("title")
                        or entry.get("run_id"),
                        "duration": pipeline.clock(
                            (entry.get("video") or {}).get("duration") or 0
                        ),
                        "updated": time_label(
                            entry.get("updated_at") or entry.get("archived_at")
                        ),
                        "words": (entry.get("summary") or {}).get("words", 0),
                        "tagged lines": (entry.get("summary") or {}).get(
                            "tagged_lines", 0
                        ),
                        "targeted": (entry.get("targeted") or {}).get("status")
                        or "—",
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
    with right:
        with st.container(border=True):
            st.subheader(":material/add_circle: New job")
            st.caption("Start from a new video or audio source.")
            if st.button(
                "Create new job",
                type="primary",
                icon=":material/add:",
                width="stretch",
            ):
                st.switch_page(INGEST_PAGE)
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
        st.caption("The current job is not shown as a past job. Open Ingest or Transcribe to work with it.")

    if job and not job.get("is_current"):
        st.divider()
        render_history_details(job)


SETTINGS_SECTIONS = [
    (
        "targeted",
        "Targeted transcription",
        "Window expansion, trigger filtering, and quiet-gap snapping.",
    ),
    (
        "llm",
        "Qwen selection",
        "Local endpoint, model, clip limits, and fallback behavior.",
    ),
    (
        "whisper",
        "Whisper",
        "Model, revision, decoding threshold, and determinism.",
    ),
    (
        "yamnet",
        "YAMNet",
        "Tag thresholds, trigger groups, scan window, and model paths.",
    ),
    (
        "merge_tags",
        "Tagged transcript",
        "Line splitting, cue timing, duplicate cleanup, and VTT wrapping.",
    ),
    (
        "outro",
        "Outro trim",
        "Speech-end confidence and tail padding.",
    ),
]

SETTINGS_FIELDS = {
    "targeted": [
        ("pre", "Pre-roll seconds", "float", {"min_value": 0.0, "step": 1.0}),
        ("post", "Post-roll seconds", "float", {"min_value": 0.0, "step": 1.0}),
        ("merge_gap", "Merge gap seconds", "float", {"min_value": 0.0, "step": 1.0}),
        ("limit", "Candidate limit (0 = all)", "int", {"min_value": 0, "step": 1}),
        ("use_llm", "Use Qwen by default", "bool", {}),
        ("quiet_rel_db", "Quiet relative dB", "float", {"step": 0.5}),
        ("snap_max_shift", "Snap max shift seconds", "float", {"min_value": 0.0, "step": 0.5}),
        ("music_threshold", "Music tag threshold", "float", {"min_value": 0.0, "max_value": 1.0, "step": 0.05}),
    ],
    "llm": [
        ("base_url", "Base URL", "text", {}),
        ("model", "Model name", "text", {}),
        ("timeout", "Timeout seconds", "float", {"min_value": 1.0, "step": 10.0}),
        ("disable_thinking", "Disable thinking", "bool", {}),
        ("max_tokens", "Max tokens", "int", {"min_value": 1, "step": 64}),
        ("min_clip", "Minimum clip seconds", "float", {"min_value": 0.1, "step": 0.5}),
        ("max_clip", "Maximum clip seconds", "float", {"min_value": 0.1, "step": 1.0}),
        ("heuristic_radius", "Fallback radius seconds", "float", {"min_value": 0.1, "step": 0.5}),
        ("api_key", "API key", "password", {}),
        ("api_key_file", "API key file", "text", {}),
        ("api_key_container", "API key container", "text", {}),
    ],
    "whisper": [
        ("model", "Model", "text", {}),
        ("revision", "Revision", "text", {}),
        ("log_prob_threshold", "Log-probability threshold", "float", {"step": 0.05}),
        ("seed", "Seed", "int", {"min_value": 0, "step": 1}),
        ("local_files_only", "Local files only", "bool", {}),
    ],
    "yamnet": [
        ("sample_rate", "Sample rate", "int", {"min_value": 8000, "step": 1000}),
        ("window", "Window samples", "int", {"min_value": 1000, "step": 1000}),
        ("hop", "Hop samples", "int", {"min_value": 100, "step": 100}),
        ("yamnet_samples", "YAMNet samples", "int", {"min_value": 1000, "step": 100}),
        ("tag_membership", "Tag membership", "float", {"min_value": 0.0, "max_value": 1.0, "step": 0.05}),
        ("peak_floor", "Peak floor", "float", {"min_value": 0.0, "max_value": 1.0, "step": 0.05}),
        ("loud_db", "Loud dB threshold", "float", {"step": 0.5}),
        ("music_threshold", "Music threshold", "float", {"min_value": 0.0, "max_value": 1.0, "step": 0.05}),
        ("music_index", "Music class index", "int", {"min_value": 0, "step": 1}),
        ("trigger_groups", "Trigger groups", "list", {"help": "Comma-separated class groups"}),
        ("model", "Model path", "text", {}),
        ("class_map", "Class map path", "text", {}),
    ],
    "merge_tags": [
        ("membership", "Membership", "float", {"min_value": 0.0, "max_value": 1.0, "step": 0.05}),
        ("peak_floor", "Peak floor", "float", {"min_value": 0.0, "max_value": 1.0, "step": 0.05}),
        ("abs_high", "High absolute score", "float", {"min_value": 0.0, "max_value": 1.0, "step": 0.05}),
        ("abs_med", "Medium absolute score", "float", {"min_value": 0.0, "max_value": 1.0, "step": 0.05}),
        ("abs_low", "Low absolute score", "float", {"min_value": 0.0, "max_value": 1.0, "step": 0.05}),
        ("max_bridge", "Max bridge seconds", "float", {"min_value": 0.0, "step": 0.5}),
        ("chunk_seconds", "Percentile chunk seconds", "float", {"min_value": 1.0, "step": 10.0}),
        ("percentile_min_spans", "Percentile min spans", "int", {"min_value": 1, "step": 1}),
        ("loud_gap", "Loud gap seconds", "float", {"min_value": 0.0, "step": 0.5}),
        ("music_threshold", "Music threshold", "float", {"min_value": 0.0, "max_value": 1.0, "step": 0.05}),
        ("music_gap", "Music gap seconds", "float", {"min_value": 0.0, "step": 0.5}),
        ("pause", "Line pause seconds", "float", {"min_value": 0.0, "step": 0.1}),
        ("max_words", "Max words per line", "int", {"min_value": 1, "step": 1}),
        ("max_line_seconds", "Max line seconds", "float", {"min_value": 0.1, "step": 0.5}),
        ("min_cue_seconds", "Min cue seconds", "float", {"min_value": 0.01, "step": 0.1}),
        ("max_cue_seconds", "Max cue seconds", "float", {"min_value": 0.1, "step": 0.5}),
        ("tag_attach_lead", "Tag attach lead", "float", {"min_value": 0.0, "step": 0.1}),
        ("vtt_wrap_columns", "VTT wrap columns", "int", {"min_value": 10, "step": 1}),
        ("max_repeat", "Max repeated words", "int", {"min_value": 1, "step": 1}),
        ("dup_window", "Duplicate window seconds", "float", {"min_value": 0.0, "step": 0.5}),
        ("dup_ratio", "Duplicate ratio", "float", {"min_value": 0.0, "max_value": 1.0, "step": 0.01}),
        ("low_conf_p", "Low confidence probability", "float", {"min_value": 0.0, "max_value": 1.0, "step": 0.01}),
        ("high_conf_p", "High confidence probability", "float", {"min_value": 0.0, "max_value": 1.0, "step": 0.01}),
        ("isolation_window", "Isolation window seconds", "float", {"min_value": 0.0, "step": 0.1}),
        ("min_word_dur", "Min word duration", "float", {"min_value": 0.0, "step": 0.01}),
        ("max_word_dur", "Max word duration", "float", {"min_value": 0.0, "step": 0.1}),
    ],
    "outro": [
        ("tail_seconds", "Tail seconds", "float", {"min_value": 0.0, "step": 0.5}),
        ("confidence_threshold", "Confidence threshold", "float", {"min_value": 0.0, "max_value": 1.0, "step": 0.01}),
    ],
}


def setting_widget(section, key, label, kind, options, value):
    widget_key = f"setting_{section}_{key}"
    help_text = options.get("help")
    if kind == "bool":
        return st.toggle(label, value=bool(value), key=widget_key, help=help_text)
    if kind in {"float", "int"}:
        kwargs = {name: options[name] for name in ("min_value", "max_value", "step") if name in options}
        if kind == "float":
            return float(
                st.number_input(
                    label,
                    value=float(value),
                    format="%.3f",
                    key=widget_key,
                    help=help_text,
                    **kwargs,
                )
            )
        return int(
            st.number_input(
                label,
                value=int(value),
                step=int(kwargs.get("step", 1)),
                min_value=kwargs.get("min_value"),
                max_value=kwargs.get("max_value"),
                key=widget_key,
                help=help_text,
            )
        )
    if kind == "list":
        raw = st.text_input(
            label,
            value=", ".join(str(item) for item in value or []),
            key=widget_key,
            help=help_text,
        )
        return [item.strip() for item in raw.split(",") if item.strip()]
    return st.text_input(
        label,
        value=str(value or ""),
        key=widget_key,
        help=help_text,
        type="password" if kind == "password" else "default",
    )


def render_settings():
    st.title("Settings")
    st.caption(
        "Edit the pipeline settings. Values are saved directly to the single "
        "config file."
    )
    notice = st.session_state.pop("settings_notice", None)
    if notice:
        st.success(notice)
    st.caption(f"Config file: {config.config_path()}")
    st.caption("Secrets such as the Qwen API key may be stored here.")
    if st.button("Reset config to defaults", icon=":material/restart_alt:"):
        config.reset_config()
        st.session_state["settings_notice"] = "Config reset to defaults."
        st.rerun()

    with st.form("settings_form"):
        values = {}
        for section, title, description in SETTINGS_SECTIONS:
            with st.expander(title, expanded=section in {"targeted", "llm"}):
                st.caption(description)
                fields = SETTINGS_FIELDS[section]
                for index in range(0, len(fields), 2):
                    columns = st.columns(2)
                    for column, field in zip(columns, fields[index : index + 2]):
                        key, label, kind, options = field
                        with column:
                            values.setdefault(section, {})[key] = setting_widget(
                                section,
                                key,
                                label,
                                kind,
                                options,
                                config.get(section, key),
                            )
        submitted = st.form_submit_button(
            "Save config",
            type="primary",
            icon=":material/save:",
        )
        if submitted:
            try:
                config.save_config(values)
                st.session_state["settings_notice"] = (
                    f"Saved config to {config.config_path()}."
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Could not save config: {exc}")

    with st.expander("Effective config", expanded=False):
        st.json(config.CONFIG)


def page_select():
    render_scaffold("3-select")


def page_reframe():
    render_scaffold("4-reframe")


def page_caption():
    render_scaffold("5-caption")


def page_export():
    render_scaffold("6-export")


HISTORY_PAGE = st.Page(
    render_history,
    title="History",
    icon=":material/history:",
    default=True,
)
INGEST_PAGE = st.Page(
    render_ingest,
    title="Ingest",
    icon=":material/download:",
    url_path="ingest",
)
TRANSCRIBE_PAGE = st.Page(
    render_transcribe,
    title="Transcribe",
    icon=":material/graphic_eq:",
    url_path="transcribe",
)
SELECT_PAGE = st.Page(
    page_select,
    title="Select",
    icon=":material/filter_alt:",
    url_path="select",
)
REFRAME_PAGE = st.Page(
    page_reframe,
    title="Reframe",
    icon=":material/crop:",
    url_path="reframe",
)
CAPTION_PAGE = st.Page(
    page_caption,
    title="Caption",
    icon=":material/subtitles:",
    url_path="caption",
)
EXPORT_PAGE = st.Page(
    page_export,
    title="Export",
    icon=":material/ios_share:",
    url_path="export",
)
SETTINGS_PAGE = st.Page(
    render_settings,
    title="Settings",
    icon=":material/settings:",
    url_path="settings",
)

pages = {
    "Jobs": [HISTORY_PAGE],
    "Pipeline": [
        INGEST_PAGE,
        TRANSCRIBE_PAGE,
        SELECT_PAGE,
        REFRAME_PAGE,
        CAPTION_PAGE,
        EXPORT_PAGE,
    ],
    "System": [SETTINGS_PAGE],
}

page = st.navigation(pages, position="sidebar", expanded=True)
page.run()
