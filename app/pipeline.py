import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import config

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
RUNS_DIR = APP_DIR / "runs"
HISTORY_DIR = APP_DIR / "history"
CURRENT_JOB_PATH = APP_DIR / "current_job.json"

STAGES = {
    "1-ingest": {
        "number": 1,
        "title": "Ingest",
        "description": "Download audio with yt-dlp and normalize it to 16 kHz mono WAV.",
        "command": ["bash", "1-ingest/scripts/run.sh"],
        "url": True,
        "required": [],
        "handoffs": [
            (
                "2-transcribe",
                "Send to Transcribe",
                [
                    (
                        "1-ingest/output/audio/audio16k_full.wav",
                        "2-transcribe/input/audio16k_full.wav",
                    )
                ],
            )
        ],
        "previews": [("Ingest manifest", "1-ingest/output/ingest.json", "json")],
    },
    "2-transcribe": {
        "number": 2,
        "title": "Transcribe",
        "description": "Run Whisper, trim the outro, tag audio with YAMNet, and write timestamped and tagged transcripts.",
        "command": ["bash", "2-transcribe/scripts/run.sh"],
        "url": False,
        "required": ["2-transcribe/input/audio16k_full.wav"],
        "handoffs": [
            (
                "3-select",
                "Send to Select",
                [("2-transcribe/output/audio/audio16k.wav", "3-select/input/audio16k.wav")],
            )
        ],
        "previews": [
            ("Timestamped transcript", "2-transcribe/output/transcript.txt", "text"),
            ("Tagged transcript", "2-transcribe/output/transcript_with_audio_tags.txt", "text"),
            ("Tagged WebVTT", "2-transcribe/output/transcript_with_audio_tags.vtt", "text"),
        ],
    },
    "3-select": {
        "number": 3,
        "title": "Select",
        "description": "Highlight selection. This stage is a scaffold.",
        "command": None,
        "url": False,
        "required": [],
        "handoffs": [],
        "previews": [],
    },
    "4-reframe": {
        "number": 4,
        "title": "Reframe",
        "description": "Reframe selected clips. This stage is a scaffold.",
        "command": None,
        "url": False,
        "required": [],
        "handoffs": [],
        "previews": [],
    },
    "5-caption": {
        "number": 5,
        "title": "Caption",
        "description": "Render captions onto video. This stage is a scaffold.",
        "command": None,
        "url": False,
        "required": [],
        "handoffs": [],
        "previews": [],
    },
    "6-export": {
        "number": 6,
        "title": "Export",
        "description": "Final packaging. This stage is a scaffold.",
        "command": None,
        "url": False,
        "required": [],
        "handoffs": [],
        "previews": [],
    },
}


def now_iso(value=None):
    value = value or time.time()
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def file_info(relpath):
    path = ROOT / relpath
    if not path.is_file():
        return {"path": relpath, "name": path.name, "exists": False, "size": 0, "mtime": None}
    stat = path.stat()
    return {
        "path": relpath,
        "name": path.name,
        "exists": True,
        "size": stat.st_size,
        "mtime": now_iso(stat.st_mtime),
    }


def scan(directory):
    base = ROOT / directory
    if not base.is_dir():
        return []
    return [
        file_info(path.relative_to(ROOT).as_posix())
        for path in sorted(base.rglob("*"))
        if path.is_file() and path.name != ".gitkeep"
    ]


def read_json_path(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def read_json(relpath):
    return read_json_path(ROOT / relpath)


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def current_since():
    ingest = read_json("1-ingest/output/ingest.json") or {}
    return ingest.get("created_at")


def slug(value):
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value)).strip("-")
    return cleaned[:80] or "run"


def file_after(mtime, since):
    if not since or not mtime:
        return True
    stamp = parse_iso(mtime)
    threshold = parse_iso(since)
    if not stamp or not threshold:
        return True
    return stamp.timestamp() >= threshold.timestamp() - 2


def line_count(relpath):
    try:
        with open(ROOT / relpath, encoding="utf-8") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def preview(relpath, kind, max_lines=40):
    if not (ROOT / relpath).exists():
        return ""
    if kind == "json":
        data = read_json(relpath)
        return json.dumps(data, indent=1) if data is not None else ""
    try:
        with open(ROOT / relpath, encoding="utf-8", errors="replace") as fh:
            return "".join(line for _, line in zip(range(max_lines), fh))
    except OSError:
        return ""


def summary(stage_id):
    if stage_id == "1-ingest":
        data = read_json("1-ingest/output/ingest.json")
        if not data:
            return {}
        return {
            "duration": f"{data.get('duration_seconds', '?')}s",
            "sample_rate": data.get("sample_rate"),
            "source": Path(data.get("source_file", "")).name,
        }
    if stage_id == "2-transcribe":
        since = current_since()

        def current_json(relpath):
            info = file_info(relpath)
            if not info["exists"] or not file_after(info["mtime"], since):
                return None
            return read_json(relpath)

        words = current_json("2-transcribe/output/whisper_words.json")
        segments = current_json("2-transcribe/output/whisper_segments.json")
        tags = current_json("2-transcribe/output/audio_tags.json")
        manifest = current_json("2-transcribe/output/run_manifest.json") or {}
        transcript_info = file_info("2-transcribe/output/transcript.txt")
        tagged_info = file_info("2-transcribe/output/transcript_with_audio_tags.txt")
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
            "tagged_lines": line_count("2-transcribe/output/transcript_with_audio_tags.txt") if file_after(tagged_info["mtime"], since) else 0,
            "vtt_cues": cues,
        }
        if manifest.get("model"):
            data["model"] = manifest["model"]
        return data
    return {}


def current_job():
    return read_json_path(CURRENT_JOB_PATH)


def run_id_for_ingest(ingest, video=None):
    created = parse_iso(ingest.get("created_at")) or datetime.now(timezone.utc)
    video_id = (video or {}).get("video_id") or ingest.get("video_id") or "video"
    return f"{slug(video_id)}-{created.strftime('%Y%m%d-%H%M%S')}"


def current_run_id():
    marker = current_job()
    if marker:
        return marker.get("run_id")
    ingest = read_json("1-ingest/output/ingest.json") or {}
    if not ingest:
        return None
    candidate = run_id_for_ingest(ingest, media())
    if (HISTORY_DIR / candidate / "run.json").exists():
        return candidate
    return None


def set_current_job(job_id, url, run_id=None):
    record = {
        "job_id": job_id,
        "url": url,
        "run_id": run_id,
        "started_at": now_iso(),
        "status": "running",
    }
    with open(CURRENT_JOB_PATH, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=1)
    return record


def mark_current_run(run_id):
    record = current_job()
    if not record:
        return None
    record["run_id"] = run_id
    with open(CURRENT_JOB_PATH, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=1)
    return record


def update_current_job(status):
    record = current_job()
    if not record:
        return None
    record["status"] = status
    with open(CURRENT_JOB_PATH, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=1)
    return record


def clear_current_job():
    try:
        CURRENT_JOB_PATH.unlink()
    except FileNotFoundError:
        pass


def media():
    ingest = read_json("1-ingest/output/ingest.json") or {}
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


def clock(seconds):
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def activity(bin_seconds=10, base=None):
    if base is None:
        base_path = ROOT / "2-transcribe" / "output"
        info = file_info("2-transcribe/output/audio_tags.json")
        if not info["exists"] or not file_after(info["mtime"], current_since()):
            return None
    else:
        base_path = Path(base)
    meta = read_json_path(base_path / "audio_tags.json")
    words = read_json_path(base_path / "whisper_words.json") or []
    if not isinstance(meta, dict) or not meta.get("windows"):
        return None
    windows = meta["windows"]
    duration = float(
        meta.get("duration_seconds")
        or max(float(window["end"]) for window in windows)
    )
    if duration <= 0:
        return None
    bin_seconds = max(1, int(bin_seconds))
    count = max(1, math.ceil(duration / bin_seconds))
    bins = []
    for index in range(count):
        start = index * bin_seconds
        bins.append(
            {
                "index": index,
                "start": start,
                "end": min(start + bin_seconds, duration),
                "time": clock(start),
                "windows": 0,
                "words": 0,
                "loud": 0,
                "rel_db": 0.0,
                "laugh": 0.0,
                "scream": 0.0,
                "shout": 0.0,
                "music": 0.0,
            }
        )

    loud_threshold = float(config.get("yamnet", "loud_db", 6.0))
    for window in windows:
        center = (float(window["start"]) + float(window["end"])) / 2
        index = min(int(center // bin_seconds), count - 1)
        item = bins[index]
        item["windows"] += 1
        item["rel_db"] += float(window.get("rel_db", 0.0))
        scores = window.get("scores") or {}
        item["laugh"] = max(item["laugh"], float(scores.get("LAUGHTER", 0.0)))
        item["scream"] = max(item["scream"], float(scores.get("SCREAMING", 0.0)))
        item["shout"] = max(item["shout"], float(scores.get("SHOUTING", 0.0)))
        item["music"] = max(item["music"], float(window.get("music", 0.0)))
        if float(window.get("rel_db", -999.0)) >= loud_threshold:
            item["loud"] += 1

    for word in words:
        if not isinstance(word, dict) or "start" not in word:
            continue
        index = min(int(float(word["start"]) // bin_seconds), count - 1)
        bins[index]["words"] += 1

    for item in bins:
        windows_in_bin = item["windows"] or 1
        item["rel_db"] = item["rel_db"] / windows_in_bin
        item["loud"] = item["loud"] / windows_in_bin
        item["speech"] = item["words"] / bin_seconds

    metrics = [
        ("Loudness", "rel_db", "minmax"),
        ("Speech", "speech", "max"),
        ("Loud", "loud", "fixed"),
        ("Laughter", "laugh", "fixed"),
        ("Screaming", "scream", "fixed"),
        ("Shouting", "shout", "fixed"),
        ("Music", "music", "fixed"),
    ]
    heatmap = []
    for label, key, mode in metrics:
        values = [float(item[key]) for item in bins]
        if mode == "minmax":
            low, high = min(values), max(values)
            span = high - low if high > low else 1.0
            normalized = [(value - low) / span for value in values]
        elif mode == "max":
            high = max(values) or 1.0
            normalized = [value / high for value in values]
        else:
            normalized = [max(0.0, min(1.0, value)) for value in values]
        for item, value in zip(bins, normalized):
            heatmap.append(
                {
                    "time": item["time"],
                    "index": item["index"],
                    "metric": label,
                    "value": round(float(value), 4),
                    "raw": round(float(item[key]), 3),
                }
            )

    minute_count = max(1, math.ceil(duration / 60.0))
    minutes = []
    for index in range(minute_count):
        start = index * 60.0
        end = min(start + 60.0, duration)
        selected = [item for item in bins if item["start"] < end and item["end"] > start]
        weighted = [item for item in selected if item["windows"]]
        rel_db = (
            sum(item["rel_db"] * item["windows"] for item in weighted)
            / sum(item["windows"] for item in weighted)
            if weighted
            else 0.0
        )
        minutes.append(
            {
                "time": clock(start),
                "start": start,
                "words": sum(item["words"] for item in selected),
                "loud": round(sum(item["loud"] for item in selected), 2),
                "laugh": round(max((item["laugh"] for item in selected), default=0.0), 3),
                "scream": round(max((item["scream"] for item in selected), default=0.0), 3),
                "shout": round(max((item["shout"] for item in selected), default=0.0), 3),
                "music": round(max((item["music"] for item in selected), default=0.0), 3),
                "rel_db": round(rel_db, 2),
            }
        )
    max_words = max((item["words"] for item in minutes), default=0) or 1
    max_loud = max((item["loud"] for item in minutes), default=0) or 1
    for item in minutes:
        item["activity"] = round(
            item["words"] / max_words
            + item["loud"] / max_loud
            + max(item["laugh"], item["scream"], item["shout"])
            + item["music"],
            3,
        )

    tag_membership = float(config.get("yamnet", "tag_membership", 0.2))
    totals = {
        "duration": round(duration, 1),
        "words": len(words),
        "loud_windows": sum(
            1
            for window in windows
            if float(window.get("rel_db", -999.0)) >= loud_threshold
        ),
        "laughter_windows": sum(
            1
            for window in windows
            if float((window.get("scores") or {}).get("LAUGHTER", 0.0)) >= tag_membership
        ),
        "screaming_windows": sum(
            1
            for window in windows
            if float((window.get("scores") or {}).get("SCREAMING", 0.0)) >= tag_membership
        ),
        "shouting_windows": sum(
            1
            for window in windows
            if float((window.get("scores") or {}).get("SHOUTING", 0.0)) >= tag_membership
        ),
        "music_windows": sum(
            1
            for window in windows
            if float(window.get("music", 0.0)) >= 0.5
        ),
    }
    return {
        "duration": round(duration, 1),
        "bin_seconds": bin_seconds,
        "bins": bins,
        "heatmap": heatmap,
        "minutes": minutes,
        "totals": totals,
    }


def outputs(stage_id, since=None):
    items = []
    for item in scan(f"{stage_id}/output"):
        if since and not file_after(item["mtime"], since):
            continue
        relative = Path(item["path"]).relative_to(Path(stage_id) / "output")
        item["url"] = f"/files/{stage_id}/{relative.as_posix()}"
        items.append(item)
    return items


def inputs(stage_id, stage):
    items = scan(f"{stage_id}/input")
    present = {item["path"] for item in items}
    for required in stage["required"]:
        if required not in present:
            items.append(file_info(required))
    required = set(stage["required"])
    for item in items:
        item["required"] = item["path"] in required
    return items


def status(stage_id, stage, active_job=None):
    if not stage["command"]:
        return "scaffold"
    if active_job and active_job["stage"] == stage_id and active_job["status"] == "running":
        return "running"
    since = None if stage_id == "1-ingest" else current_since()
    if outputs(stage_id, since):
        return "complete"
    return "ready" if all((ROOT / item).exists() for item in stage["required"]) else "blocked"


def overview(stage_id, stage, active_job=None):
    return {
        "id": stage_id,
        "number": stage["number"],
        "title": stage["title"],
        "description": stage["description"],
        "status": status(stage_id, stage, active_job),
        "ready": all((ROOT / item).exists() for item in stage["required"]),
        "summary": summary(stage_id),
    }


def detail(stage_id, stage, job=None):
    active = job if job and job["status"] == "running" else None
    data = overview(stage_id, stage, active)
    data["implemented"] = bool(stage["command"])
    data["accepts_url"] = stage["url"]
    data["inputs"] = inputs(stage_id, stage)
    since = None if stage_id == "1-ingest" else current_since()
    data["outputs"] = outputs(stage_id, since)
    data["handoffs"] = [
        {
            "to": target,
            "label": label,
            "available": all((ROOT / source).exists() for source, _ in files),
        }
        for target, label, files in stage["handoffs"]
    ]
    data["previews"] = [
        {"label": label, "text": preview(path, kind)}
        for label, path, kind in stage["previews"]
        if (ROOT / path).exists()
        and (since is None or file_after(file_info(path)["mtime"], since))
    ]
    data["job"] = job
    return data


def archive_current_run():
    marker = current_job() or {}
    marker_run = marker.get("run_id")
    if marker_run and (HISTORY_DIR / marker_run / "run.json").is_file():
        return marker_run
    ingest = read_json("1-ingest/output/ingest.json") or {}
    if not ingest:
        return None
    since = ingest.get("created_at")
    current_outputs = outputs("2-transcribe", since)
    if not current_outputs:
        return None
    media_data = media()
    created = parse_iso(since) or datetime.now(timezone.utc)
    run_id = f"{slug(media_data.get('video_id') or 'video')}-{created.strftime('%Y%m%d-%H%M%S')}"
    destination = HISTORY_DIR / run_id
    temporary = HISTORY_DIR / f".{run_id}.tmp"
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True, exist_ok=True)
    sources = ["1-ingest/output/ingest.json"] + [item["path"] for item in current_outputs]
    files = []
    seen = set()
    skip_suffixes = {".wav", ".mp3", ".opus", ".webm", ".m4a", ".mp4"}
    for relpath in sources:
        source = ROOT / relpath
        if not source.is_file() or source.name in seen:
            continue
        if source.suffix.lower() in skip_suffixes:
            continue
        target = temporary / source.name
        shutil.copy2(source, target)
        seen.add(source.name)
        files.append(
            {
                "name": source.name,
                "source": relpath,
                "size": target.stat().st_size,
                "mtime": now_iso(target.stat().st_mtime),
            }
        )
    audio_name = None
    for candidate in (
        ROOT / "2-transcribe" / "input" / "audio16k_full.wav",
        ROOT / "1-ingest" / "output" / "audio" / "audio16k_full.wav",
    ):
        if not candidate.is_file():
            continue
        target = temporary / "audio16k_full.wav"
        shutil.copy2(candidate, target)
        audio_name = "audio16k_full.wav"
        files.append(
            {
                "name": audio_name,
                "source": candidate.relative_to(ROOT).as_posix(),
                "size": target.stat().st_size,
                "mtime": now_iso(target.stat().st_mtime),
            }
        )
        break
    record = {
        "run_id": run_id,
        "video": media_data,
        "ingest": ingest,
        "summary": summary("2-transcribe"),
        "files": files,
        "audio": audio_name,
        "archived_at": now_iso(),
        "updated_at": now_iso(),
    }
    with open(temporary / "run.json", "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=1)
    if destination.exists():
        shutil.rmtree(destination)
    temporary.rename(destination)
    return run_id


def history():
    if not HISTORY_DIR.is_dir():
        return []
    current = current_run_id()
    entries = []
    for path in sorted(HISTORY_DIR.iterdir(), reverse=True):
        if not path.is_dir():
            continue
        record = read_json_path(path / "run.json")
        if not record:
            continue
        if current and record.get("run_id") == current:
            continue
        record["path"] = str(path)
        entries.append(record)
    entries.sort(
        key=lambda item: item.get("updated_at") or item.get("archived_at") or "",
        reverse=True,
    )
    return entries

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


TRANSCRIBE_FILES = [
    "transcript.txt",
    "whisper_transcript.txt",
    "whisper_words.json",
    "whisper_segments.json",
    "audio_tags.json",
    "metadata.json",
    "run_manifest.json",
    "vad.json",
    "transcript_with_audio_tags.txt",
    "transcript_with_audio_tags.vtt",
    "transcript_with_audio_tags.json",
    "whisper_words_clean.json",
]

TARGETED_DIR = "targeted"
TARGETED_FILES = [
    "audio_tags.json",
    "candidates.json",
    "targeted_segments.json",
    "targeted_words.json",
    "targeted_transcript.txt",
    "targeted_with_events.json",
    "targeted_with_events.txt",
    "selection.json",
    "timings.json",
]


def line_count_path(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def transcribe_summary_from_path(path):
    words = read_json_path(path / "whisper_words.json")
    segments = read_json_path(path / "whisper_segments.json")
    tags = read_json_path(path / "audio_tags.json")
    manifest = read_json_path(path / "run_manifest.json") or {}
    vtt = path / "transcript_with_audio_tags.vtt"
    cues = 0
    if vtt.is_file():
        with open(vtt, encoding="utf-8", errors="replace") as fh:
            cues = sum(1 for line in fh if "-->" in line)
    data = {
        "words": len(words) if isinstance(words, list) else 0,
        "segments": len(segments) if isinstance(segments, list) else 0,
        "tags": len(tags.get("windows", [])) if isinstance(tags, dict) else 0,
        "transcript_lines": line_count_path(path / "transcript.txt"),
        "tagged_lines": line_count_path(path / "transcript_with_audio_tags.txt"),
        "vtt_cues": cues,
    }
    if manifest.get("model"):
        data["model"] = manifest["model"]
    return data


def archive_files(path):
    return [
        {
            "name": child.name,
            "size": child.stat().st_size,
            "mtime": now_iso(child.stat().st_mtime),
        }
        for child in sorted(path.iterdir())
        if child.is_file() and child.name != "run.json"
    ]


def job_label(record):
    video = record.get("video") or {}
    title = video.get("title") or video.get("url") or record.get("run_id") or "Job"
    duration = clock(video.get("duration") or 0)
    stamp = record.get("updated_at") or record.get("archived_at")
    when = parse_iso(stamp)
    date = when.strftime("%Y-%m-%d %H:%M") if when else ""
    status = record.get("status")
    if status in ("running", "failed"):
        suffix = status
    elif record.get("is_current"):
        suffix = "current"
    else:
        suffix = "past"
    return f"{title} · {duration} · {date} · {suffix}"


def jobs():
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
    marker_run = marker.get("run_id")
    marker_job = marker.get("job_id")
    result = []
    has_current_archive = any(record.get("run_id") == current for record in archives)
    if marker and not has_current_archive:
        ingest = read_json("1-ingest/output/ingest.json") or {}
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
            status = (current_job() or {}).get("status")
            if status:
                item["status"] = status
        item["label"] = job_label(item)
        result.append(item)
    return result


def job_detail(job_id):
    if not job_id:
        return None
    archive = HISTORY_DIR / job_id
    if (archive / "run.json").is_file():
        return history_detail(job_id)
    marker = current_job() or {}
    if marker.get("job_id") == job_id or marker.get("run_id") == job_id:
        media_data = media()
        ingest = read_json("1-ingest/output/ingest.json") or {}
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
    destination = ROOT / "2-transcribe" / "input" / "audio16k_full.wav"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(audio, destination)


def update_job_after_stage(run_id, stage_id):
    archive = HISTORY_DIR / run_id
    record = read_json_path(archive / "run.json")
    if not record:
        raise FileNotFoundError(f"history entry missing: {run_id}")
    if stage_id == "1-ingest":
        ingest_path = ROOT / "1-ingest" / "output" / "ingest.json"
        if not ingest_path.is_file():
            raise FileNotFoundError("ingest output missing")
        shutil.copy2(ingest_path, archive / "ingest.json")
        audio = ROOT / "1-ingest" / "output" / "audio" / "audio16k_full.wav"
        if audio.is_file():
            shutil.copy2(audio, archive / "audio16k_full.wav")
            record["audio"] = "audio16k_full.wav"
        for filename in TRANSCRIBE_FILES:
            stale = archive / filename
            if stale.exists():
                stale.unlink()
        ingest = read_json_path(archive / "ingest.json") or {}
        record["ingest"] = ingest
        record["video"] = media()
        record["summary"] = {}
    elif stage_id == "2-transcribe":
        for filename in TRANSCRIBE_FILES:
            source = ROOT / "2-transcribe" / "output" / filename
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


def _targeted_dir(run_id):
    return HISTORY_DIR / run_id / TARGETED_DIR


def _targeted_path(run_id, out_dir=None):
    archive = HISTORY_DIR / run_id
    path = Path(out_dir) if out_dir else archive / TARGETED_DIR
    try:
        stored = path.resolve().relative_to(archive.resolve()).as_posix()
    except ValueError:
        stored = str(path.resolve())
    return path, stored


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
    path, stored = _targeted_path(run_id, out_dir)
    record = read_json_path(HISTORY_DIR / run_id / "run.json")
    if not record:
        raise FileNotFoundError(f"history entry missing: {run_id}")
    targeted = record.get("targeted") or {}
    targeted.update(
        {
            "status": "succeeded",
            "mode": "yamnet_qwen",
            "path": stored,
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


class Jobs:
    def __init__(self):
        self.lock = threading.Lock()
        self.jobs = {}
        self.processes = {}
        self.active = None

    def tail(self, path, max_bytes=20000, max_lines=200):
        try:
            with open(path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - max_bytes))
                text = fh.read().decode("utf-8", "replace")
            return "\n".join(text.splitlines()[-max_lines:])
        except OSError:
            return ""

    def public(self, job):
        end = job["ended"] or time.time()
        return {
            "id": job["id"],
            "stage": job["stage"],
            "status": job["status"],
            "returncode": job["returncode"],
            "elapsed": round(end - job["started"], 1),
            "log_tail": self.tail(job["log_path"]),
        }

    def start(self, stage_id, argv):
        with self.lock:
            if self.active and self.jobs[self.active]["status"] == "running":
                raise RuntimeError("another job is already running")
            job_id = uuid.uuid4().hex[:12]
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            log_path = RUNS_DIR / f"{stamp}-{stage_id}-{job_id}.log"
            log_file = open(log_path, "w", encoding="utf-8", errors="replace")
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            try:
                process = subprocess.Popen(
                    argv,
                    cwd=str(ROOT),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                    env=env,
                )
            finally:
                log_file.close()
            job = {
                "id": job_id,
                "stage": stage_id,
                "status": "running",
                "started": time.time(),
                "ended": None,
                "returncode": None,
                "log_path": str(log_path),
            }
            self.jobs[job_id] = job
            self.processes[job_id] = process
            self.active = job_id
            data = self.public(job)
        threading.Thread(target=self._wait, args=(job_id, process), daemon=True).start()
        return data

    def _wait(self, job_id, process):
        returncode = process.wait()
        with self.lock:
            job = self.jobs[job_id]
            job["returncode"] = returncode
            job["ended"] = time.time()
            job["status"] = "succeeded" if returncode == 0 else "failed"
            if self.active == job_id:
                self.active = None
            self.processes.pop(job_id, None)

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            return self.public(job) if job else None

    def latest(self, stage_id):
        with self.lock:
            result = None
            for job in self.jobs.values():
                if job["stage"] == stage_id:
                    if result is None or job["started"] > result["started"]:
                        result = job
            return self.public(result) if result else None

    def current(self):
        with self.lock:
            job = self.jobs.get(self.active) if self.active else None
            return self.public(job) if job else None


JOBS = Jobs()


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
