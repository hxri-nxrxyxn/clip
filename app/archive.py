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
SELECTION_DIR = "selection"

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
        video_dir = job_root / "video"
        shutil.rmtree(archive / "video", ignore_errors=True)
        record["video_file"] = None
        if video_dir.is_dir():
            for source in sorted(video_dir.glob("source.*")):
                if not source.is_file():
                    continue
                target = archive / "video" / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                record["video_file"] = f"video/{source.name}"
                break
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


def _write_record_field(run_id: str, key: str, value: dict[str, Any]) -> dict[str, Any]:
    archive = HISTORY_DIR / run_id
    record = read_json_path(archive / "run.json")
    if not record:
        raise FileNotFoundError(f"history entry missing: {run_id}")
    record[key] = value
    record["updated_at"] = now_iso()
    with open(archive / "run.json", "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=1)
    return record


def start_targeted_extract_run(run_id: str) -> dict[str, Any]:
    archive = HISTORY_DIR / run_id
    record = read_json_path(archive / "run.json")
    if not record:
        raise FileNotFoundError(f"history entry missing: {run_id}")
    targeted = record.get("targeted") or {}
    targeted.update(
        {
            "status": "running",
            "mode": "yamnet_targeted_whisper",
            "started_at": now_iso(),
            "updated_at": now_iso(),
            "path": TARGETED_DIR,
            "error": None,
            "summary": {},
            "previews": [],
        }
    )
    return _write_record_field(run_id, "targeted", targeted)


def _extract_summary(path: Path) -> dict[str, Any]:
    candidates = read_json_path(path / "candidates.json") or {}
    segments = read_json_path(path / "targeted_segments.json") or []
    words = read_json_path(path / "targeted_words.json") or []
    timings = read_json_path(path / "timings.json") or {}
    return {
        "candidates": len(candidates.get("candidates") or []),
        "segments": len(segments) if isinstance(segments, list) else 0,
        "words": len(words) if isinstance(words, list) else 0,
        "candidates_seconds": timings.get("candidates_seconds"),
        "targeted_whisper_seconds": timings.get("targeted_whisper_seconds"),
        "total_seconds": timings.get("total_seconds"),
    }


def _extract_previews(path: Path) -> list[dict[str, str]]:
    transcript = path / "targeted_with_events.txt"
    if not transcript.is_file():
        return []
    try:
        with open(transcript, encoding="utf-8", errors="replace") as fh:
            return [{"label": "Targeted transcript", "text": "".join(list(fh)[:40])}]
    except OSError:
        return []


def update_targeted_extract_after_run(
    run_id: str, out_dir: str | Path | None = None
) -> dict[str, Any]:
    archive = HISTORY_DIR / run_id / TARGETED_DIR
    if out_dir:
        source = Path(out_dir).resolve()
        if source != archive.resolve():
            if archive.exists():
                shutil.rmtree(archive)
            shutil.copytree(source, archive)
    record = read_json_path(HISTORY_DIR / run_id / "run.json")
    if not record:
        raise FileNotFoundError(f"history entry missing: {run_id}")
    targeted = record.get("targeted") or {}
    targeted.update(
        {
            "status": "succeeded",
            "mode": "yamnet_targeted_whisper",
            "path": TARGETED_DIR,
            "updated_at": now_iso(),
            "finished_at": now_iso(),
            "error": None,
            "summary": _extract_summary(archive),
            "previews": _extract_previews(archive),
        }
    )
    return _write_record_field(run_id, "targeted", targeted)


def mark_targeted_extract_failed(run_id: str, error: Any) -> dict[str, Any] | None:
    record = read_json_path(HISTORY_DIR / run_id / "run.json")
    if not record:
        return None
    targeted = record.get("targeted") or {}
    targeted.update(
        {
            "status": "failed",
            "mode": "yamnet_targeted_whisper",
            "path": targeted.get("path", TARGETED_DIR),
            "updated_at": now_iso(),
            "finished_at": now_iso(),
            "error": str(error),
        }
    )
    return _write_record_field(run_id, "targeted", targeted)


def targeted_extract_detail(run_id: str) -> dict[str, Any] | None:
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
    item["previews"] = _extract_previews(path)
    candidates = read_json_path(path / "candidates.json") or {}
    item["candidates"] = candidates.get("candidates") or []
    return item


def run_targeted_extract(
    run_id: str, extra_args: list[str] | None = None
) -> dict[str, Any] | None:
    if not (HISTORY_DIR / run_id / "run.json").is_file():
        raise FileNotFoundError(f"history entry missing: {run_id}")
    command = [
        "bash",
        str(ROOT / "2-transcribe" / "scripts" / "targeted_extract.sh"),
        run_id,
        *(extra_args or []),
    ]
    result = subprocess.run(command, cwd=ROOT, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"targeted extraction failed for {run_id}")
    return targeted_extract_detail(run_id)


def start_selection_run(run_id: str) -> dict[str, Any]:
    archive = HISTORY_DIR / run_id
    record = read_json_path(archive / "run.json")
    if not record:
        raise FileNotFoundError(f"history entry missing: {run_id}")
    selection = record.get("selection") or {}
    selection.update(
        {
            "status": "running",
            "mode": "qwen",
            "started_at": now_iso(),
            "updated_at": now_iso(),
            "path": SELECTION_DIR,
            "error": None,
            "summary": {},
            "previews": [],
        }
    )
    return _write_record_field(run_id, "selection", selection)


def _selection_summary(path: Path) -> dict[str, Any]:
    selection = read_json_path(path / "selection.json") or {}
    timings = read_json_path(path / "timings.json") or {}
    selections = selection.get("selections") or []
    return {
        "candidates": timings.get("candidates", len(selections)),
        "selections": len(selections),
        "llm_ready": bool(selection.get("llm_ready")),
        "llm_seconds": timings.get("llm_seconds"),
        "total_seconds": timings.get("total_seconds"),
    }


def _selection_previews(path: Path) -> list[dict[str, str]]:
    selection = read_json_path(path / "selection.json") or {}
    selections = selection.get("selections") or []
    if not selections:
        return []
    lines = []
    for item in selections[:40]:
        lines.append(
            f"#{item.get('candidate_id')} "
            f"{clock(item.get('start', 0))}-{clock(item.get('end', 0))} "
            f"{item.get('reason', '')}".strip()
        )
    return [{"label": "Qwen selections", "text": "\n".join(lines)}]


def update_selection_after_run(
    run_id: str, out_dir: str | Path | None = None
) -> dict[str, Any]:
    archive = HISTORY_DIR / run_id / SELECTION_DIR
    archive.mkdir(parents=True, exist_ok=True)
    if out_dir:
        source = Path(out_dir).resolve()
        if source != archive.resolve():
            if archive.exists():
                shutil.rmtree(archive)
            shutil.copytree(source, archive)
    record = read_json_path(HISTORY_DIR / run_id / "run.json")
    if not record:
        raise FileNotFoundError(f"history entry missing: {run_id}")
    selection = record.get("selection") or {}
    selection.update(
        {
            "status": "succeeded",
            "mode": "qwen",
            "path": SELECTION_DIR,
            "updated_at": now_iso(),
            "finished_at": now_iso(),
            "error": None,
            "summary": _selection_summary(archive),
            "previews": _selection_previews(archive),
        }
    )
    return _write_record_field(run_id, "selection", selection)


def mark_selection_failed(run_id: str, error: Any) -> dict[str, Any] | None:
    record = read_json_path(HISTORY_DIR / run_id / "run.json")
    if not record:
        return None
    selection = record.get("selection") or {}
    selection.update(
        {
            "status": "failed",
            "mode": "qwen",
            "path": selection.get("path", SELECTION_DIR),
            "updated_at": now_iso(),
            "finished_at": now_iso(),
            "error": str(error),
        }
    )
    return _write_record_field(run_id, "selection", selection)


def selection_detail(run_id: str) -> dict[str, Any] | None:
    archive = HISTORY_DIR / run_id
    record = read_json_path(archive / "run.json")
    if not record:
        return None
    selection = record.get("selection")
    if not selection and record.get("targeted"):
        legacy = dict(record["targeted"])
        legacy_path = archive / legacy.get("path", TARGETED_DIR)
        if (legacy_path / "selection.json").is_file():
            legacy.update(
                {
                    "mode": "qwen",
                    "path": TARGETED_DIR,
                    "summary": _selection_summary(legacy_path),
                    "previews": _selection_previews(legacy_path),
                }
            )
            selection = legacy
    if not selection:
        return None
    path = archive / selection.get("path", SELECTION_DIR)
    item = dict(selection)
    item["path"] = str(path)
    item["files"] = archive_files(path) if path.is_dir() else []
    item["previews"] = _selection_previews(path)
    selection_data = read_json_path(path / "selection.json") or {}
    item["selections"] = selection_data.get("selections") or []
    return item


def run_selection(run_id: str, extra_args: list[str] | None = None) -> dict[str, Any] | None:
    if not (HISTORY_DIR / run_id / "run.json").is_file():
        raise FileNotFoundError(f"history entry missing: {run_id}")
    command = [
        "bash",
        str(ROOT / "3-select" / "scripts" / "run.sh"),
        run_id,
        *(extra_args or []),
    ]
    result = subprocess.run(command, cwd=ROOT, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"selection failed for {run_id}")
    return selection_detail(run_id)


def split_legacy_targeted(run_id: str, dry_run: bool = False) -> bool:
    archive_dir = HISTORY_DIR / run_id
    targeted_dir = archive_dir / TARGETED_DIR
    selection_dir = archive_dir / SELECTION_DIR
    record = read_json_path(archive_dir / "run.json")
    if not record or record.get("selection"):
        return False
    if not (targeted_dir / "selection.json").is_file():
        return False
    if dry_run:
        return True
    selection_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(targeted_dir / "selection.json", selection_dir / "selection.json")
    if (targeted_dir / "timings.json").is_file():
        shutil.copy2(targeted_dir / "timings.json", selection_dir / "timings.json")
    targeted = record.get("targeted") or {}
    status = targeted.get("status", "succeeded")
    record["targeted"] = {
        "status": status,
        "mode": "yamnet_targeted_whisper",
        "path": TARGETED_DIR,
        "updated_at": targeted.get("updated_at", now_iso()),
        "finished_at": targeted.get("finished_at", now_iso()),
        "error": targeted.get("error"),
        "summary": _extract_summary(targeted_dir),
        "previews": _extract_previews(targeted_dir),
    }
    record["selection"] = {
        "status": status,
        "mode": "qwen",
        "path": SELECTION_DIR,
        "updated_at": targeted.get("updated_at", now_iso()),
        "finished_at": targeted.get("finished_at", now_iso()),
        "error": targeted.get("error"),
        "summary": _selection_summary(selection_dir),
        "previews": _selection_previews(selection_dir),
    }
    record["updated_at"] = now_iso()
    with open(archive_dir / "run.json", "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=1)
    return True


def start_visual_run(run_id: str) -> dict[str, Any]:
    archive = HISTORY_DIR / run_id
    record = read_json_path(archive / "run.json")
    if not record:
        raise FileNotFoundError(f"history entry missing: {run_id}")
    visual = record.get("visual") or {}
    visual.update(
        {
            "status": "running",
            "mode": "qwen_vlm",
            "started_at": now_iso(),
            "updated_at": now_iso(),
            "path": SELECTION_DIR,
            "error": None,
            "summary": {},
            "previews": [],
        }
    )
    return _write_record_field(run_id, "visual", visual)


def _visual_summary(path: Path) -> dict[str, Any]:
    analysis = read_json_path(path / "visual_analysis.json") or {}
    clips = analysis.get("clips") or []
    scores = [
        int(clip.get("visual_score"))
        for clip in clips
        if clip.get("vlm_used") and clip.get("visual_score")
    ]
    return {
        "clips": len(clips),
        "vlm_ready": bool(analysis.get("vlm_ready")),
        "vlm_clips": sum(1 for clip in clips if clip.get("vlm_used")),
        "average_visual_score": round(sum(scores) / len(scores), 2) if scores else 0,
    }


def _visual_previews(path: Path) -> list[dict[str, str]]:
    analysis = read_json_path(path / "visual_analysis.json") or {}
    clips = analysis.get("clips") or []
    lines = []
    for clip in clips:
        lines.append(
            f"#{clip.get('candidate_id')} "
            f"{clock(clip.get('start', 0))}-{clock(clip.get('end', 0))} "
            f"score={clip.get('visual_score', 0)} "
            f"{clip.get('summary', '')}".strip()
        )
    return [{"label": "VLM visual stories", "text": "\n".join(lines)}] if lines else []


def update_visual_after_run(
    run_id: str, out_dir: str | Path | None = None
) -> dict[str, Any]:
    archive = HISTORY_DIR / run_id / SELECTION_DIR
    archive.mkdir(parents=True, exist_ok=True)
    if out_dir:
        source = Path(out_dir).resolve()
        if source != archive.resolve():
            for name in ("visual_analysis.json", "visual_timings.json"):
                if (source / name).is_file():
                    shutil.copy2(source / name, archive / name)
            sheets = source / "contact_sheets"
            if sheets.is_dir():
                target = archive / "contact_sheets"
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(sheets, target)
    record = read_json_path(HISTORY_DIR / run_id / "run.json")
    if not record:
        raise FileNotFoundError(f"history entry missing: {run_id}")
    visual = record.get("visual") or {}
    visual.update(
        {
            "status": "succeeded",
            "mode": "qwen_vlm",
            "path": SELECTION_DIR,
            "updated_at": now_iso(),
            "finished_at": now_iso(),
            "error": None,
            "summary": _visual_summary(archive),
            "previews": _visual_previews(archive),
        }
    )
    return _write_record_field(run_id, "visual", visual)


def mark_visual_failed(run_id: str, error: Any) -> dict[str, Any] | None:
    record = read_json_path(HISTORY_DIR / run_id / "run.json")
    if not record:
        return None
    visual = record.get("visual") or {}
    visual.update(
        {
            "status": "failed",
            "mode": "qwen_vlm",
            "path": visual.get("path", SELECTION_DIR),
            "updated_at": now_iso(),
            "finished_at": now_iso(),
            "error": str(error),
        }
    )
    return _write_record_field(run_id, "visual", visual)


def visual_detail(run_id: str) -> dict[str, Any] | None:
    archive = HISTORY_DIR / run_id
    record = read_json_path(archive / "run.json")
    if not record:
        return None
    visual = record.get("visual")
    if not visual:
        return None
    path = archive / visual.get("path", SELECTION_DIR)
    analysis = read_json_path(path / "visual_analysis.json") or {}
    clips = []
    for clip in analysis.get("clips") or []:
        item = dict(clip)
        sheet = item.get("contact_sheet")
        item["contact_sheet_path"] = str(path / sheet) if sheet else None
        clips.append(item)
    item = dict(visual)
    item["path"] = str(path)
    item["files"] = archive_files(path) if path.is_dir() else []
    item["previews"] = _visual_previews(path)
    item["clips"] = clips
    item["vlm_ready"] = bool(analysis.get("vlm_ready"))
    return item


def run_visual(run_id: str, extra_args: list[str] | None = None) -> dict[str, Any] | None:
    if not (HISTORY_DIR / run_id / "run.json").is_file():
        raise FileNotFoundError(f"history entry missing: {run_id}")
    command = [
        "bash",
        str(ROOT / "3-select" / "scripts" / "visual.sh"),
        run_id,
        *(extra_args or []),
    ]
    result = subprocess.run(command, cwd=ROOT, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"visual analysis failed for {run_id}")
    return visual_detail(run_id)
