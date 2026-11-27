"""Archive and historical snapshot management for pipeline jobs and targeted runs."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app import analytics, storage

ROOT = storage.ROOT
APP_DIR = storage.APP_DIR
HISTORY_DIR = storage.HISTORY_DIR
TRANSCRIBE_FILES = storage.TRANSCRIBE_FILES
TARGETED_DIR = storage.TARGETED_DIR

now_iso = storage.now_iso
read_json_path = storage.read_json_path
archive_files = storage.archive_files
clock = analytics.clock


def prepare_stage_workspace(run_id: str, stage_id: str) -> None:
    """Prepare input audio files in stage directories before re-running a stage."""
    if stage_id != "2-transcribe":
        return
    archive = HISTORY_DIR / run_id
    audio = archive / "audio16k_full.wav"
    if not audio.is_file():
        raise FileNotFoundError(f"archived audio missing for {run_id}")
    destination = storage.stage_input_dir("2-transcribe", run_id) / "audio16k_full.wav"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(audio, destination)


def update_job_after_stage(run_id: str, stage_id: str) -> dict[str, Any]:
    """Sync stage execution artifacts back into the job's history archive."""
    archive = HISTORY_DIR / run_id
    record = read_json_path(archive / "run.json")
    if not record:
        raise FileNotFoundError(f"history entry missing: {run_id}")
    if stage_id == "1-ingest":
        job_root = storage.stage_output_dir("1-ingest", run_id)
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
        shutil.rmtree(storage.stage_output_dir("2-transcribe", run_id), ignore_errors=True)
        for filename in TRANSCRIBE_FILES:
            stale = archive / filename
            if stale.exists():
                stale.unlink()
        ingest = read_json_path(archive / "ingest.json") or {}
        record["ingest"] = ingest
        record["video"] = storage.video_from_ingest(ingest)
        record["summary"] = {}
    elif stage_id == "2-transcribe":
        job_root = storage.stage_output_dir("2-transcribe", run_id)
        for filename in TRANSCRIBE_FILES:
            source = job_root / filename
            if source.is_file():
                shutil.copy2(source, archive / filename)
        record["summary"] = storage.transcribe_summary_from_path(archive)
    else:
        raise ValueError(f"unsupported stage: {stage_id}")
    record["files"] = archive_files(archive)
    record["updated_at"] = now_iso()
    with open(archive / "run.json", "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=1)
    return record


def _write_targeted_record(run_id: str, targeted: dict[str, Any]) -> dict[str, Any]:
    archive = HISTORY_DIR / run_id
    record = read_json_path(archive / "run.json")
    if not record:
        raise FileNotFoundError(f"history entry missing: {run_id}")
    record["targeted"] = targeted
    record["updated_at"] = now_iso()
    with open(archive / "run.json", "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=1)
    return record


def start_targeted_run(run_id: str) -> dict[str, Any]:
    """Mark targeted stage as running in the archive manifest."""
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


def _targeted_summary(path: Path) -> dict[str, Any]:
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


def _targeted_previews(path: Path) -> list[dict[str, str]]:
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


def update_targeted_after_run(run_id: str, out_dir: str | Path | None = None) -> dict[str, Any]:
    """Copy targeted outputs to archive and record metadata."""
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


def mark_targeted_failed(run_id: str, error: Any) -> dict[str, Any] | None:
    """Record targeted execution failure into archive manifest."""
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


def targeted_detail(run_id: str) -> dict[str, Any] | None:
    """Retrieve structured targeted results and selections for a run."""
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


def run_targeted_archive(run_id: str, extra_args: list[str] | None = None) -> dict[str, Any] | None:
    """Synchronously execute targeted transcription against an archived run."""
    if not (HISTORY_DIR / run_id / "run.json").is_file():
        raise FileNotFoundError(f"history entry missing: {run_id}")
    command = ["bash", str(APP_DIR / "targeted_job.sh"), run_id, *(extra_args or [])]
    result = subprocess.run(command, cwd=ROOT, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"targeted job failed for {run_id}")
    return targeted_detail(run_id)
