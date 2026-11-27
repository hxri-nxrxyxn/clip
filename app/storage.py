import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
HISTORY_DIR = APP_DIR / "history"
CURRENT_JOB_PATH = APP_DIR / "current_job.json"
INGEST_OUTPUT = ROOT / "1-ingest" / "output"
CURRENT_RUN_POINTER = INGEST_OUTPUT / "current_run_id"
TARGETED_DIR = "targeted"

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


def now_iso(value=None):
    value = value or time.time()
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def read_json_path(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def read_json(relpath):
    return read_json_path(ROOT / relpath)


def slug(value):
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value)).strip("-")
    return cleaned[:80] or "run"


def stage_output_dir(stage_id, run_id):
    return ROOT / stage_id / "output" / run_id


def stage_input_dir(stage_id, run_id):
    return ROOT / stage_id / "input" / run_id


def write_current_run_pointer(run_id):
    INGEST_OUTPUT.mkdir(parents=True, exist_ok=True)
    CURRENT_RUN_POINTER.write_text(str(run_id), encoding="utf-8")
    return run_id


def read_current_run_pointer():
    try:
        value = CURRENT_RUN_POINTER.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def current_job():
    return read_json_path(CURRENT_JOB_PATH)


def set_current_job(job_id, url, run_id=None):
    if not run_id:
        archive_current_run()
    record = {
        "job_id": job_id,
        "url": url,
        "run_id": run_id,
        "started_at": now_iso(),
        "status": "running",
    }
    with open(CURRENT_JOB_PATH, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=1)
    if run_id:
        write_current_run_pointer(run_id)
    else:
        try:
            CURRENT_RUN_POINTER.unlink()
        except FileNotFoundError:
            pass
    return record


def mark_current_run(run_id):
    record = current_job()
    if not record:
        return None
    record["run_id"] = run_id
    with open(CURRENT_JOB_PATH, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=1)
    write_current_run_pointer(run_id)
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


def run_id_for_ingest(ingest, video=None):
    created = parse_iso(ingest.get("created_at")) or datetime.now(timezone.utc)
    video_id = (video or {}).get("video_id") or ingest.get("video_id") or "video"
    return f"{slug(video_id)}-{created.strftime('%Y%m%d-%H%M%S')}"


def resolve_run_id(run_id=None):
    if run_id:
        return str(run_id)
    marker = current_job() or {}
    if marker.get("run_id"):
        return marker["run_id"]
    pointer = read_current_run_pointer()
    if pointer:
        return pointer
    ingest = read_json("1-ingest/output/ingest.json") or {}
    if ingest:
        return run_id_for_ingest(ingest)
    return None


def current_run_id():
    marker = current_job() or {}
    if marker.get("run_id"):
        return marker["run_id"]
    pointer = read_current_run_pointer()
    if pointer:
        return pointer
    ingest = read_json("1-ingest/output/ingest.json") or {}
    if not ingest:
        return None
    candidate = run_id_for_ingest(ingest)
    if (HISTORY_DIR / candidate / "run.json").exists():
        return candidate
    return None


def ingest_for_run(run_id=None):
    resolved = resolve_run_id(run_id)
    if resolved:
        data = read_json_path(stage_output_dir("1-ingest", resolved) / "ingest.json")
        if data:
            return data
    return read_json("1-ingest/output/ingest.json") or {}


def current_since(run_id=None):
    ingest = ingest_for_run(run_id)
    return ingest.get("created_at")


def file_after(mtime, since):
    if not since or not mtime:
        return True
    stamp = parse_iso(mtime)
    threshold = parse_iso(since)
    if not stamp or not threshold:
        return True
    return stamp.timestamp() >= threshold.timestamp() - 2


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


def archive_current_run(run_id=None):
    if not run_id:
        marker = current_job() or {}
        marker_run = marker.get("run_id")
        if marker_run and (HISTORY_DIR / marker_run / "run.json").is_file():
            return marker_run
    run_id = resolve_run_id(run_id)
    if not run_id:
        return None
    if (HISTORY_DIR / run_id / "run.json").is_file():
        return run_id
    ingest = ingest_for_run(run_id)
    if not ingest:
        return None
    transcribe_dir = stage_output_dir("2-transcribe", run_id)
    if not transcribe_dir.is_dir():
        transcribe_dir = ROOT / "2-transcribe" / "output"
    destination = HISTORY_DIR / run_id
    temporary = HISTORY_DIR / f".{run_id}.tmp"
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True, exist_ok=True)
    ingest_source = stage_output_dir("1-ingest", run_id) / "ingest.json"
    if not ingest_source.is_file():
        ingest_source = ROOT / "1-ingest" / "output" / "ingest.json"
    files = []
    seen = set()
    skip_suffixes = {".wav", ".mp3", ".opus", ".webm", ".m4a", ".mp4"}
    source_candidates = [ingest_source]
    if transcribe_dir.is_dir():
        source_candidates.extend(transcribe_dir.glob("*"))
    for source in source_candidates:
        if not source.is_file() or source.name in seen or source.suffix.lower() in skip_suffixes:
            continue
        target = temporary / source.name
        shutil.copy2(source, target)
        seen.add(source.name)
        files.append(
            {
                "name": source.name,
                "source": source.relative_to(ROOT).as_posix(),
                "size": target.stat().st_size,
                "mtime": now_iso(target.stat().st_mtime),
            }
        )
    audio_name = None
    for candidate in (
        stage_input_dir("2-transcribe", run_id) / "audio16k_full.wav",
        stage_output_dir("1-ingest", run_id) / "audio" / "audio16k_full.wav",
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
        "video": {
            "title": ingest.get("title") or Path(ingest.get("source_file", "")).name or "No media loaded",
            "url": ingest.get("webpage_url") or ingest.get("source_url") or "",
            "duration": ingest.get("duration_seconds"),
            "source": ingest.get("source_file", ""),
            "video_id": ingest.get("video_id"),
            "uploader": ingest.get("uploader"),
            "sample_rate": ingest.get("sample_rate"),
        },
        "ingest": ingest,
        "summary": transcribe_summary_from_path(transcribe_dir) if transcribe_dir.is_dir() else {},
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
    write_current_run_pointer(run_id)
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
        if not record or (current and record.get("run_id") == current):
            continue
        record["path"] = str(path)
        entries.append(record)
    entries.sort(
        key=lambda item: item.get("updated_at") or item.get("archived_at") or "",
        reverse=True,
    )
    return entries
