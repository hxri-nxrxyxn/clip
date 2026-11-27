import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analytics
import jobs
import stages
import storage

# Re-export core references
APP_DIR = storage.APP_DIR
ROOT = storage.ROOT
RUNS_DIR = jobs.RUNS_DIR
HISTORY_DIR = storage.HISTORY_DIR
CURRENT_JOB_PATH = storage.CURRENT_JOB_PATH
INGEST_OUTPUT = storage.INGEST_OUTPUT
CURRENT_RUN_POINTER = storage.CURRENT_RUN_POINTER
STAGE_IDS = stages.STAGE_IDS
STAGES = stages.STAGES
TRANSCRIBE_FILES = storage.TRANSCRIBE_FILES
TARGETED_DIR = storage.TARGETED_DIR
JOBS = jobs.JOBS
Jobs = jobs.Jobs

# Re-export storage and time helpers
now_iso = storage.now_iso
parse_iso = storage.parse_iso
read_json_path = storage.read_json_path
read_json = storage.read_json
slug = storage.slug
stage_output_dir = storage.stage_output_dir
stage_input_dir = storage.stage_input_dir
write_current_run_pointer = storage.write_current_run_pointer
read_current_run_pointer = storage.read_current_run_pointer
current_job = storage.current_job
set_current_job = storage.set_current_job
mark_current_run = storage.mark_current_run
update_current_job = storage.update_current_job
clear_current_job = storage.clear_current_job
run_id_for_ingest = storage.run_id_for_ingest
resolve_run_id = storage.resolve_run_id
current_run_id = storage.current_run_id
ingest_for_run = storage.ingest_for_run
current_since = storage.current_since
file_after = storage.file_after
line_count_path = storage.line_count_path
transcribe_summary_from_path = storage.transcribe_summary_from_path
archive_files = storage.archive_files
archive_current_run = storage.archive_current_run
history = storage.history

# Re-export stage and preview helpers
file_info = stages.file_info
scan = stages.scan
line_count = stages.line_count
preview = stages.preview
outputs = stages.outputs
inputs = stages.inputs
status = stages.status

# Re-export analytics
clock = analytics.clock


def activity(bin_seconds=10, base=None):
    if base is None:
        run_id = resolve_run_id()
        base_path = (
            stage_output_dir("2-transcribe", run_id)
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


def summary(stage_id, run_id=None):
    if stage_id == "1-ingest":
        data = ingest_for_run(run_id)
        if not data:
            return {}
        return {
            "duration": f"{data.get('duration_seconds', '?')}s",
            "sample_rate": data.get("sample_rate"),
            "source": Path(data.get("source_file", "")).name,
        }
    if stage_id == "2-transcribe":
        run_id = resolve_run_id(run_id)
        if run_id and stage_output_dir("2-transcribe", run_id).is_dir():
            return transcribe_summary_from_path(stage_output_dir("2-transcribe", run_id))
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
            with open(ROOT / "2-transcribe/output/transcript_with_audio_tags.vtt", encoding="utf-8", errors="replace") as fh:
                cues = sum(1 for line in fh if "-->" in line)
        data = {
            "words": len(words) if isinstance(words, list) else 0,
            "segments": len(segments) if isinstance(segments, list) else 0,
            "tags": len(tags.get("windows", [])) if isinstance(tags, dict) else 0,
            "transcript_lines": line_count("2-transcribe/output/transcript.txt") if file_after(transcript_info["mtime"], since) else 0,
            "tagged_lines": line_count("2-transcribe/output/transcript_with_audio_tags.txt") if file_after(transcript_info["mtime"], since) else 0,
            "vtt_cues": cues,
        }
        if manifest.get("model"):
            data["model"] = manifest["model"]
        return data
    return {}


def overview(stage_id, stage_dict, active_job=None):
    return {
        "id": stage_id,
        "number": stage_dict["number"],
        "title": stage_dict["title"],
        "description": stage_dict["description"],
        "status": status(stage_id, stage_dict, active_job),
        "ready": all((ROOT / item).exists() for item in stage_dict["required"]),
        "summary": summary(stage_id),
    }


def detail(stage_id, stage_dict, job=None):
    active = job if job and job["status"] == "running" else None
    data = overview(stage_id, stage_dict, active)
    data["implemented"] = bool(stage_dict["command"])
    data["accepts_url"] = stage_dict["url"]
    data["inputs"] = inputs(stage_id, stage_dict)
    since = None if stage_id == "1-ingest" else current_since()
    data["outputs"] = outputs(stage_id, since)
    data["handoffs"] = [
        {
            "to": target,
            "label": label,
            "available": all((ROOT / source).exists() for source, _ in files),
        }
        for target, label, files in stage_dict["handoffs"]
    ]
    data["previews"] = [
        {"label": label, "text": preview(path, kind)}
        for label, path, kind in stage_dict["previews"]
        if (ROOT / path).exists()
        and (since is None or file_after(file_info(path)["mtime"], since))
    ]
    data["job"] = job
    return data


def media(run_id=None):
    run_id = resolve_run_id(run_id)
    ingest = ingest_for_run(run_id)
    if run_id:
        tag_path = stage_output_dir("2-transcribe", run_id) / "audio_tags.json"
        tags = read_json_path(tag_path) or {}
    else:
        tag_info = file_info("2-transcribe/output/audio_tags.json")
        if tag_info["exists"] and file_after(tag_info["mtime"], ingest.get("created_at")):
            tags = read_json("2-transcribe/output/audio_tags.json") or {}
        else:
            tags = {}
    source = ingest.get("source_file") or ""
    url = ingest.get("webpage_url") or ingest.get("source_url") or ""
    title = ingest.get("title")
    if not title:
        if url.startswith(("http://", "https://")):
            title = url
        elif source:
            title = Path(source).name
        else:
            title = "No media loaded"
    duration = ingest.get("duration_seconds") or tags.get("duration_seconds")
    return {
        "title": title,
        "url": url,
        "duration": duration,
        "source": source,
        "video_id": ingest.get("video_id"),
        "uploader": ingest.get("uploader"),
        "sample_rate": ingest.get("sample_rate"),
    }


def history_detail(run_id):
    path = (HISTORY_DIR / run_id).resolve()
    root = HISTORY_DIR.resolve()
    if path != root and root not in path.parents:
        return None
    record = read_json_path(path / "run.json")
    if not record:
        return None
    record["path"] = str(path)
    record["previews"] = []
    for filename, label in (
        ("transcript.txt", "Transcript"),
        ("transcript_with_audio_tags.txt", "Tagged transcript"),
        ("transcript_with_audio_tags.vtt", "WebVTT"),
    ):
        file_path = path / filename
        if not file_path.is_file():
            continue
        try:
            with open(file_path, encoding="utf-8", errors="replace") as fh:
                text = "".join(line for _, line in zip(range(40), fh))
        except OSError:
            continue
        record["previews"].append({"label": label, "text": text})
    targeted = targeted_detail(run_id)
    if targeted:
        record["targeted"] = targeted
    record["activity"] = activity(10, base=path)
    return record


def job_label(record):
    video = record.get("video") or {}
    title = video.get("title") or video.get("url") or record.get("run_id") or "Job"
    duration = clock(video.get("duration") or 0)
    stamp = record.get("updated_at") or record.get("archived_at")
    when = parse_iso(stamp)
    date = when.strftime("%Y-%m-%d %H:%M") if when else ""
    job_status = record.get("status")
    if job_status in ("running", "failed"):
        suffix = job_status
    elif record.get("is_current"):
        suffix = "current"
    else:
        suffix = "past"
    return f"{title} · {duration} · {date} · {suffix}"


def jobs_list():
    archives = []
    if HISTORY_DIR.is_dir():
        for path in HISTORY_DIR.iterdir():
            if not path.is_dir():
                continue
            record = read_json_path(path / "run.json")
            if not record:
                continue
            record["path"] = str(path)
            archives.append(record)
    archives.sort(
        key=lambda item: item.get("updated_at") or item.get("archived_at") or "",
        reverse=True,
    )
    current = current_run_id()
    marker = current_job() or {}
    marker_job = marker.get("job_id")
    result = []
    has_current_archive = any(record.get("run_id") == current for record in archives)
    if marker and not has_current_archive:
        live_run = marker.get("run_id") or read_current_run_pointer()
        ingest = ingest_for_run(live_run)
        live_url = marker.get("url") or ""
        live = {
            "id": marker_job or "current",
            "run_id": None,
            "video": {
                "title": live_url or "New job",
                "url": live_url,
                "duration": 0,
            },
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
    for record in archives:
        item = dict(record)
        item["id"] = item.get("run_id")
        item["is_current"] = item.get("run_id") == current
        if item["is_current"]:
            status_val = (current_job() or {}).get("status")
            if status_val:
                item["status"] = status_val
        item["label"] = job_label(item)
        result.append(item)
    return result


jobs = jobs_list


def job_detail(job_id):
    if not job_id:
        return None
    archive = HISTORY_DIR / job_id
    if (archive / "run.json").is_file():
        return history_detail(job_id)
    marker = current_job() or {}
    if marker.get("job_id") == job_id or marker.get("run_id") == job_id:
        live_run = marker.get("run_id") or read_current_run_pointer()
        media_data = media(live_run)
        ingest = ingest_for_run(live_run)
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


def prepare_stage_workspace(run_id, stage_id):
    if stage_id != "2-transcribe":
        return
    archive = HISTORY_DIR / run_id
    audio = archive / "audio16k_full.wav"
    if not audio.is_file():
        raise FileNotFoundError(f"archived audio missing for {run_id}")
    destination = stage_input_dir("2-transcribe", run_id) / "audio16k_full.wav"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(audio, destination)


def update_job_after_stage(run_id, stage_id):
    archive = HISTORY_DIR / run_id
    record = read_json_path(archive / "run.json")
    if not record:
        raise FileNotFoundError(f"history entry missing: {run_id}")
    if stage_id == "1-ingest":
        job_root = stage_output_dir("1-ingest", run_id)
        ingest_path = job_root / "ingest.json"
        if not ingest_path.is_file():
            ingest_path = ROOT / "1-ingest" / "output" / "ingest.json"
        if not ingest_path.is_file():
            raise FileNotFoundError("ingest output missing")
        shutil.copy2(ingest_path, archive / "ingest.json")
        audio = job_root / "audio" / "audio16k_full.wav"
        if not audio.is_file():
            audio = ROOT / "1-ingest" / "output" / "audio" / "audio16k_full.wav"
        if audio.is_file():
            shutil.copy2(audio, archive / "audio16k_full.wav")
            record["audio"] = "audio16k_full.wav"
        shutil.rmtree(stage_output_dir("2-transcribe", run_id), ignore_errors=True)
        for filename in TRANSCRIBE_FILES:
            stale = archive / filename
            if stale.exists():
                stale.unlink()
        ingest = read_json_path(archive / "ingest.json") or {}
        record["ingest"] = ingest
        record["video"] = media(run_id)
        record["summary"] = {}
    elif stage_id == "2-transcribe":
        job_root = stage_output_dir("2-transcribe", run_id)
        for filename in TRANSCRIBE_FILES:
            source = job_root / filename
            if source.is_file():
                shutil.copy2(source, archive / filename)
        record["summary"] = transcribe_summary_from_path(archive)
    else:
        raise ValueError(f"unsupported stage: {stage_id}")
    record["files"] = archive_files(archive)
    record["updated_at"] = now_iso()
    with open(archive / "run.json", "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=1)
    return record


def _write_targeted_record(run_id, targeted):
    archive = HISTORY_DIR / run_id
    record = read_json_path(archive / "run.json")
    if not record:
        raise FileNotFoundError(f"history entry missing: {run_id}")
    record["targeted"] = targeted
    record["updated_at"] = now_iso()
    with open(archive / "run.json", "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=1)
    return record


def start_targeted_run(run_id):
    archive = HISTORY_DIR / run_id
    record = read_json_path(archive / "run.json")
    if not record:
        raise FileNotFoundError(f"history entry missing: {run_id}")
    targeted = record.get("targeted") or {}
    targeted.update(
        {
            "status": "running",
            "mode": "yamnet_qwen",
            "started_at": now_iso(),
            "updated_at": now_iso(),
            "path": TARGETED_DIR,
            "error": None,
            "summary": {},
            "previews": [],
        }
    )
    return _write_targeted_record(run_id, targeted)


def _targeted_summary(path):
    candidates = read_json_path(path / "candidates.json") or {}
    segments = read_json_path(path / "targeted_segments.json") or []
    words = read_json_path(path / "targeted_words.json") or []
    selection = read_json_path(path / "selection.json") or {}
    timings = read_json_path(path / "timings.json") or {}
    return {
        "candidates": len(candidates.get("candidates") or []),
        "segments": len(segments) if isinstance(segments, list) else 0,
        "words": len(words) if isinstance(words, list) else 0,
        "selections": len(selection.get("selections") or []),
        "llm_ready": bool(selection.get("llm_ready")),
        "targeted_whisper_seconds": timings.get("targeted_whisper_seconds"),
        "llm_seconds": timings.get("llm_seconds"),
        "total_seconds": timings.get("total_seconds"),
    }


def _targeted_previews(path):
    previews = []
    transcript = path / "targeted_with_events.txt"
    if transcript.is_file():
        try:
            with open(transcript, encoding="utf-8", errors="replace") as fh:
                text = "".join(line for _, line in zip(range(40), fh))
            previews.append({"label": "Targeted transcript", "text": text})
        except OSError:
            pass
    selection = read_json_path(path / "selection.json") or {}
    selections = selection.get("selections") or []
    if selections:
        lines = []
        for item in selections[:40]:
            lines.append(
                f"#{item.get('candidate_id')} "
                f"{clock(item.get('start', 0))}-{clock(item.get('end', 0))} "
                f"{item.get('reason', '')}".strip()
            )
        previews.append({"label": "Targeted selections", "text": "\n".join(lines)})
    return previews


def update_targeted_after_run(run_id, out_dir=None):
    archive = HISTORY_DIR / run_id / TARGETED_DIR
    if out_dir:
        source = Path(out_dir).resolve()
        if source != archive.resolve():
            if archive.exists():
                shutil.rmtree(archive)
            shutil.copytree(source, archive)
    path = archive
    record = read_json_path(HISTORY_DIR / run_id / "run.json")
    if not record:
        raise FileNotFoundError(f"history entry missing: {run_id}")
    targeted = record.get("targeted") or {}
    targeted.update(
        {
            "status": "succeeded",
            "mode": "yamnet_qwen",
            "path": TARGETED_DIR,
            "updated_at": now_iso(),
            "finished_at": now_iso(),
            "error": None,
            "summary": _targeted_summary(path),
            "previews": _targeted_previews(path),
        }
    )
    return _write_targeted_record(run_id, targeted)


def mark_targeted_failed(run_id, error):
    record = read_json_path(HISTORY_DIR / run_id / "run.json")
    if not record:
        return None
    targeted = record.get("targeted") or {}
    targeted.update(
        {
            "status": "failed",
            "mode": "yamnet_qwen",
            "path": targeted.get("path", TARGETED_DIR),
            "updated_at": now_iso(),
            "finished_at": now_iso(),
            "error": str(error),
        }
    )
    return _write_targeted_record(run_id, targeted)


def targeted_detail(run_id):
    archive = HISTORY_DIR / run_id
    record = read_json_path(archive / "run.json")
    if not record:
        return None
    targeted = record.get("targeted")
    if not targeted:
        return None
    path = archive / targeted.get("path", TARGETED_DIR)
    item = dict(targeted)
    item["path"] = str(path)
    item["files"] = archive_files(path) if path.is_dir() else []
    item["previews"] = _targeted_previews(path)
    selection = read_json_path(path / "selection.json") or {}
    item["selections"] = selection.get("selections") or []
    return item


def run_targeted_archive(run_id, extra_args=None):
    if not (HISTORY_DIR / run_id / "run.json").is_file():
        raise FileNotFoundError(f"history entry missing: {run_id}")
    command = ["bash", str(APP_DIR / "targeted_job.sh"), run_id, *(extra_args or [])]
    result = subprocess.run(command, cwd=ROOT, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"targeted job failed for {run_id}")
    return targeted_detail(run_id)


def validate_target(value):
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


def handoff(stage_id, target):
    stage = STAGES[stage_id]
    selected = next((item for item in stage["handoffs"] if item[0] == target), None)
    if not selected:
        raise ValueError(f"no handoff from {stage_id} to {target}")
    pairs = [(ROOT / source, ROOT / dest) for source, dest in selected[2]]
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
