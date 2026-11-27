"""Orchestrator for managing pipeline executions, stage overviews, and handoffs."""

import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from app import analytics, archive, jobs, stages, storage

ROOT = storage.ROOT
APP_DIR = storage.APP_DIR
HISTORY_DIR = storage.HISTORY_DIR
JOBS = jobs.JOBS
STAGE_IDS = stages.STAGE_IDS
STAGES = stages.STAGES

resolve_run_id = storage.resolve_run_id
current_since = storage.current_since
current_job = storage.current_job
read_json = storage.read_json
read_json_path = storage.read_json_path
file_info = stages.file_info
file_after = storage.file_after
format_path = stages.format_path


def activity(bin_seconds: int = 10, base: str | Path | None = None) -> dict[str, Any] | None:
    """Compute time-binned activity summary for current or specified output folder."""
    if base is None:
        run_id = resolve_run_id()
        base_path = (
            storage.stage_output_dir("2-transcribe", run_id)
            if run_id
            else ROOT / "2-transcribe" / "output"
        )
        if not (base_path / "audio_tags.json").is_file():
            legacy = ROOT / "2-transcribe" / "output"
            info = file_info("2-transcribe/output/audio_tags.json")
            if not info["exists"] or not file_after(info["mtime"], current_since()):
                return None
            base_path = legacy
    else:
        base_path = Path(base)
    meta = read_json_path(base_path / "audio_tags.json")
    words = read_json_path(base_path / "whisper_words.json") or []
    return analytics.calculate_activity(meta, words, bin_seconds)


def summary(stage_id: str, run_id: str | None = None) -> dict[str, Any]:
    """Retrieve key metrics and summary information for a given stage."""
    if stage_id == "1-ingest":
        data = storage.ingest_for_run(run_id)
        if not data:
            return {}
        return {
            "duration": f"{data.get('duration_seconds', '?')}s",
            "sample_rate": data.get("sample_rate"),
            "source": Path(data.get("source_file", "")).name,
        }
    if stage_id == "2-transcribe":
        run_id = resolve_run_id(run_id)
        if run_id and storage.stage_output_dir("2-transcribe", run_id).is_dir():
            return storage.transcribe_summary_from_path(
                storage.stage_output_dir("2-transcribe", run_id)
            )
        since = current_since()
        words = read_json("2-transcribe/output/whisper_words.json")
        segments = read_json("2-transcribe/output/whisper_segments.json")
        tags = read_json("2-transcribe/output/audio_tags.json")
        manifest = read_json("2-transcribe/output/run_manifest.json") or {}
        transcript_info = file_info("2-transcribe/output/transcript.txt")
        vtt_info = file_info("2-transcribe/output/transcript_with_audio_tags.vtt")
        tag_info = file_info("2-transcribe/output/audio_tags.json")
        if not any(
            info["exists"] and file_after(info["mtime"], since)
            for info in (transcript_info, tag_info)
        ):
            return {}
        cues = 0
        if vtt_info["exists"] and file_after(vtt_info["mtime"], since):
            with open(
                ROOT / "2-transcribe/output/transcript_with_audio_tags.vtt",
                encoding="utf-8",
                errors="replace",
            ) as fh:
                cues = sum(1 for line in fh if "-->" in line)
        data = {
            "words": len(words) if isinstance(words, list) else 0,
            "segments": len(segments) if isinstance(segments, list) else 0,
            "tags": len(tags.get("windows", [])) if isinstance(tags, dict) else 0,
            "transcript_lines": storage.line_count_path(
                ROOT / "2-transcribe/output/transcript.txt"
            ),
            "tagged_lines": storage.line_count_path(
                ROOT / "2-transcribe/output/transcript_with_audio_tags.txt"
            ),
            "cues": cues,
            "vtt_cues": cues,
            "model": manifest.get("model")
            or (manifest.get("whisper") or {}).get("model"),
        }
        return data
    return {}


def overview(
    stage_id: str, stage_dict: dict[str, Any], active_job: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Generate high-level status and readiness details for a stage."""
    run_id = resolve_run_id()
    required = [format_path(item, run_id) for item in stage_dict["required"]]
    return {
        "id": stage_id,
        "title": stage_dict["title"],
        "number": stage_dict["number"],
        "description": stage_dict["description"],
        "status": stages.status(stage_id, stage_dict, active_job),
        "ready": all((ROOT / item).exists() for item in required),
        "summary": summary(stage_id, run_id),
    }


def detail(
    stage_id: str, stage_dict: dict[str, Any], job: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Provide comprehensive details on inputs, outputs, previews, and handoffs."""
    active = job if job and job["status"] == "running" else None
    run_id = resolve_run_id()
    data = overview(stage_id, stage_dict, active)
    data["command"] = stage_dict["command"]
    data["accepts_url"] = stage_dict["url"]
    data["inputs"] = stages.inputs(stage_id, stage_dict, run_id)
    since = None if stage_id == "1-ingest" else current_since(run_id)
    data["outputs"] = stages.outputs(stage_id, since, run_id=run_id)
    data["handoffs"] = [
        {
            "target": target,
            "label": label,
            "available": all((ROOT / format_path(source, run_id)).exists() for source, _ in files),
        }
        for target, label, files in stage_dict["handoffs"]
    ]
    previews = []
    for label, path, kind in stage_dict["previews"]:
        resolved = format_path(path, run_id)
        info = file_info(resolved)
        if not info["exists"] or (since is not None and not file_after(info["mtime"], since)):
            continue
        previews.append({"label": label, "text": stages.preview(resolved, kind)})
    data["previews"] = previews
    data["job"] = job
    return data


def media(run_id: str | None = None) -> dict[str, Any]:
    """Return media metadata for a run, falling back to ingest metadata."""
    run_id = resolve_run_id(run_id)
    info: dict[str, Any] = {}
    if run_id:
        info = read_json_path(
            storage.stage_output_dir("1-ingest", run_id) / "source.info.json"
        ) or {}
    if not info:
        info = read_json("1-ingest/output/source.info.json") or {}
    if info:
        return {
            "title": info.get("title"),
            "uploader": info.get("uploader"),
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail"),
            "url": info.get("webpage_url") or info.get("original_url"),
        }
    ingest = storage.ingest_for_run(run_id)
    return storage.video_from_ingest(ingest) if ingest else {}


def history_detail(run_id: str) -> dict[str, Any] | None:
    """Retrieve full details of an archived run from app/history."""
    archive_dir = HISTORY_DIR / run_id
    record = read_json_path(archive_dir / "run.json")
    if not record:
        return None
    record["files"] = storage.archive_files(archive_dir)
    previews = []
    for filename, label in (
        ("transcript.txt", "Transcript"),
        ("transcript_with_audio_tags.txt", "Tagged transcript"),
        ("transcript_with_audio_tags.vtt", "WebVTT"),
    ):
        file_path = archive_dir / filename
        if file_path.is_file():
            try:
                with open(file_path, encoding="utf-8", errors="replace") as fh:
                    previews.append({"label": label, "text": fh.read(2000)})
            except OSError:
                pass
    record["previews"] = previews
    record["activity"] = activity(10, archive_dir)
    record["targeted"] = archive.targeted_detail(run_id)
    return record


def job_label(job: dict[str, Any]) -> str:
    """Create human-readable label for a job in the UI selector."""
    video = job.get("video") or {}
    title = video.get("title")
    if title:
        return f"{job['id']} · {title[:48]}"
    url = job.get("url") or ""
    if url:
        return f"{job['id']} · {url[:48]}"
    return job["id"]


def jobs_list() -> list[dict[str, Any]]:
    """List historical, current, and live jobs for the job picker."""
    current = storage.current_run_id()
    marker = current_job() or {}
    archived = storage.archived_runs(include_current=True)
    result: list[dict[str, Any]] = []

    has_current_archive = any(item.get("run_id") == current for item in archived)
    if marker and not has_current_archive:
        live_run = marker.get("run_id") or storage.read_current_run_pointer()
        ingest = storage.ingest_for_run(live_run)
        live_url = marker.get("url") or ""
        video = storage.video_from_ingest(ingest) if ingest else {}
        video.setdefault("title", live_url or "New job")
        video.setdefault("url", live_url)
        video.setdefault("duration", 0)
        live = {
            "id": marker.get("job_id") or "current",
            "run_id": None,
            "video": video,
            "ingest": ingest,
            "summary": {},
            "files": [],
            "status": marker.get("status", "running"),
            "archived_at": marker.get("started_at"),
            "updated_at": marker.get("started_at"),
            "is_current": True,
            "path": None,
        }
        live["label"] = job_label(live)
        result.append(live)

    for item in archived:
        item["id"] = item.get("run_id")
        item["is_current"] = item.get("run_id") == current
        if item["is_current"]:
            status_val = marker.get("status")
            if status_val:
                item["status"] = status_val
        item["label"] = job_label(item)
        result.append(item)

    result.sort(
        key=lambda item: item.get("updated_at") or item.get("archived_at") or "",
        reverse=True,
    )
    return result


jobs_fn = jobs_list


def job_detail(job_id: str) -> dict[str, Any] | None:
    """Find and return full details for either an archived or active job."""
    if not job_id:
        return None
    archive_dir = HISTORY_DIR / job_id
    if (archive_dir / "run.json").is_file():
        return history_detail(job_id)
    marker = current_job() or {}
    if marker.get("job_id") == job_id or marker.get("run_id") == job_id:
        live_run = marker.get("run_id") or storage.read_current_run_pointer()
        media_data = media(live_run)
        ingest = storage.ingest_for_run(live_run)
        return {
            "run_id": marker.get("run_id"),
            "video": media_data,
            "ingest": ingest,
            "summary": {},
            "files": [],
            "previews": [],
            "activity": activity(10),
            "path": None,
            "status": marker.get("status"),
        }
    return None


def validate_target(value: str) -> str:
    """Validate target URL or local media filepath."""
    if not value:
        raise ValueError("missing URL or media path")
    if len(value) > 2048 or any(ord(char) < 32 for char in value):
        raise ValueError("invalid URL or media path")
    if value.startswith(("http://", "https://")):
        return value
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise ValueError("local media path does not exist")
    return str(path.resolve())


def handoff(stage_id: str, target: str) -> dict[str, Any]:
    """Execute atomic handoff of output files from one stage to another."""
    stage = STAGES[stage_id]
    handoff_list: list[Any] = stage.get("handoffs", [])  # type: ignore[assignment]
    selected = next((item for item in handoff_list if item[0] == target), None)
    if not selected:
        raise ValueError(f"no handoff from {stage_id} to {target}")
    run_id = resolve_run_id()
    file_pairs: list[tuple[str, str]] = selected[2]
    pairs = [
        (ROOT / format_path(source, run_id), ROOT / format_path(dest, run_id))
        for source, dest in file_pairs
    ]
    for source, _ in pairs:
        if not source.is_file():
            raise FileNotFoundError(str(source))
    temps = []
    try:
        for source, dest in pairs:
            dest.parent.mkdir(parents=True, exist_ok=True)
            temp = dest.with_name(dest.name + f".tmp.{uuid.uuid4().hex}")
            shutil.copy2(source, temp)
            temps.append((temp, dest))
        for temp, dest in temps:
            os.replace(temp, dest)
    finally:
        for temp, _ in temps:
            if temp.exists():
                temp.unlink()
    return {"to": target, "files": len(pairs)}
