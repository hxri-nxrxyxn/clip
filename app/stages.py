import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from storage import ROOT, file_after, read_json_path, stage_output_dir, stage_input_dir, resolve_run_id, current_since, now_iso

TARGETED_DIR = "targeted"

STAGE_IDS = ["1-ingest", "2-transcribe", "3-select", "4-reframe", "5-caption", "6-export"]

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
        data = read_json_path(ROOT / relpath)
        return json.dumps(data, indent=1) if data is not None else ""
    try:
        with open(ROOT / relpath, encoding="utf-8", errors="replace") as fh:
            return "".join(line for _, line in zip(range(max_lines), fh))
    except OSError:
        return ""


def outputs(stage_id, since=None, run_id=None):
    run_id = resolve_run_id(run_id)
    base = Path(stage_id) / "output"
    source = base / run_id if run_id and (ROOT / base / run_id).is_dir() else base
    items = []
    for item in scan(source.as_posix()):
        if since and not file_after(item["mtime"], since):
            continue
        relative = Path(item["path"]).relative_to(base)
        if relative.parts and relative.parts[0] == TARGETED_DIR:
            continue
        item["url"] = f"/files/{stage_id}/{relative.as_posix()}"
        items.append(item)
    return items


def inputs(stage_id, stage, run_id=None):
    run_id = resolve_run_id(run_id)
    base = Path(stage_id) / "input"
    source = base / run_id if run_id and (ROOT / base / run_id).is_dir() else base
    items = scan(source.as_posix())
    required_names = {Path(item).name for item in stage["required"]}
    for item in items:
        item["required"] = Path(item["path"]).name in required_names
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
