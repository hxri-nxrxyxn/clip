import argparse
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageDraw, ImageFont

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(APP_DIR))

import llm_select
import pipeline
import vlm

if TYPE_CHECKING:
    from app import config
else:
    import config

YOUTUBE_FORMAT = "bv*[height<=720]+ba/b[height<=720]/bestaudio/best"


def _has_video(path: Path) -> bool:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(result.stdout.strip())


def _archive_video(run_id: str) -> Path | None:
    video_dir = pipeline.HISTORY_DIR / run_id / "video"
    if not video_dir.is_dir():
        return None
    for path in sorted(video_dir.glob("source.*")):
        if path.is_file() and _has_video(path):
            return path
    return None


def _job_video(run_id: str) -> Path | None:
    video_dir = pipeline.stage_output_dir("1-ingest", run_id) / "video"
    if not video_dir.is_dir():
        return None
    for path in sorted(video_dir.glob("source.*")):
        if path.is_file() and _has_video(path):
            return path
    return None


def _download_video(run_id: str, out_dir: Path) -> Path | None:
    ingest = pipeline.ingest_for_run(run_id)
    source = ingest.get("source_file") or ""
    if source:
        candidate = Path(source)
        if candidate.is_file() and _has_video(candidate):
            return candidate
    url = ingest.get("webpage_url") or ingest.get("source_url") or ""
    if not url.startswith(("http://", "https://")):
        return None
    ytdlp = ROOT / ".venv" / "bin" / "yt-dlp"
    if not ytdlp.is_file():
        found = shutil.which("yt-dlp")
        if not found:
            return None
        ytdlp = Path(found)
    video_dir = out_dir / "video"
    video_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(ytdlp),
        "--no-playlist",
        "--no-warnings",
        "--format",
        YOUTUBE_FORMAT,
        "--merge-output-format",
        "mp4",
        "--output",
        str(video_dir / "source.%(ext)s"),
        url,
    ]
    print(f"[visual] downloading video for frames: {url}", flush=True)
    subprocess.run(command, check=True)
    for path in sorted(video_dir.glob("source.*")):
        if path.is_file() and _has_video(path):
            return path
    return None


def resolve_video(run_id: str, out_dir: Path, allow_download: bool = True) -> Path | None:
    local_dir = out_dir / "video"
    if local_dir.is_dir():
        for path in sorted(local_dir.glob("source.*")):
            if path.is_file() and _has_video(path):
                return path
    for resolver in (_archive_video, _job_video):
        found = resolver(run_id)
        if found:
            return found
    if allow_download:
        return _download_video(run_id, out_dir)
    return None


def frame_times(start: float, end: float, count: int) -> list[float]:
    duration = max(0.1, float(end) - float(start))
    margin = min(0.4, duration * 0.08)
    low = float(start) + margin
    high = float(end) - margin
    if high <= low:
        return [float(start) + duration / 2]
    if count <= 1:
        return [(low + high) / 2]
    return [low + index * (high - low) / (count - 1) for index in range(count)]


def extract_frame(video: Path, timestamp: float, out_path: Path, width: int) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{timestamp:.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-vf",
        f"scale={width}:-2",
        "-q:v",
        "2",
        str(out_path),
    ]
    try:
        subprocess.run(command, check=True)
    except (OSError, subprocess.SubprocessError):
        return False
    return out_path.is_file()


def _font(size: int):
    for name in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ):
        if Path(name).is_file():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default()


def make_contact_sheet(
    frames: list[Path],
    labels: list[str],
    out_path: Path,
    columns: int,
    tile_width: int,
) -> bool:
    if not frames:
        return False
    columns = max(1, columns)
    rows = math.ceil(len(frames) / columns)
    label_height = 28
    tile_height = int(round(tile_width * 9 / 16))
    canvas = Image.new(
        "RGB",
        (columns * tile_width, rows * (tile_height + label_height)),
        "white",
    )
    draw = ImageDraw.Draw(canvas)
    font = _font(18)
    for index, (frame_path, label) in enumerate(zip(frames, labels)):
        if not frame_path.is_file():
            continue
        try:
            image = Image.open(frame_path).convert("RGB")
        except OSError:
            continue
        image.thumbnail((tile_width, tile_height), Image.Resampling.LANCZOS)
        column = index % columns
        row = index // columns
        x = column * tile_width
        y = row * (tile_height + label_height)
        canvas.paste(image, (x, y))
        draw.rectangle(
            (x, y + tile_height, x + tile_width, y + tile_height + label_height),
            fill="#111111",
        )
        draw.text(
            (x + 6, y + tile_height + 4),
            label,
            fill="white",
            font=font,
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, quality=90)
    return True


def _load_selection(run_id: str) -> dict[str, Any]:
    candidates = [
        pipeline.stage_output_dir("3-select", run_id) / "selection.json",
        pipeline.HISTORY_DIR / run_id / "selection" / "selection.json",
    ]
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        raise SystemExit(f"selection missing for {run_id}; run Qwen selection first")
    return json.loads(path.read_text(encoding="utf-8"))


def _vlm_settings() -> dict[str, Any]:
    return {
        "enabled": bool(config.get("vlm", "enabled", True)),
        "frames": int(config.get("vlm", "frames_per_clip", 6)),
        "columns": int(config.get("vlm", "tile_columns", 3)),
        "width": int(config.get("vlm", "tile_width", 480)),
        "max_clips": int(config.get("vlm", "max_clips", 6)),
        "timeout": float(config.get("vlm", "timeout", 180.0)),
        "max_tokens": int(config.get("vlm", "max_tokens", 700)),
    }


def run(args, started: float, run_id: str) -> Path:
    out_dir = Path(args.out) if args.out else ROOT / "3-select" / "output" / run_id
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    settings = _vlm_settings()
    if args.max_clips:
        settings["max_clips"] = args.max_clips
    selection = _load_selection(run_id)
    clips = selection.get("selections") or []
    video = resolve_video(run_id, out_dir)
    if video is None:
        raise SystemExit("no video available for frame extraction")
    print(f"[visual] run_id={run_id}", flush=True)
    print(f"[visual] video={video}", flush=True)
    print(f"[visual] clips={len(clips)}", flush=True)

    api_key = llm_select.find_api_key(explicit_file=args.llm_api_key_file)
    base_url = llm_select.resolve_base_url(args.llm_base_url, api_key)
    vlm_ready = (
        settings["enabled"]
        and not args.no_vlm
        and llm_select.server_ready(base_url, api_key)
    )
    if settings["enabled"] and not args.no_vlm:
        print(
            f"[visual] VLM {'available' if vlm_ready else 'unavailable'}: {base_url}",
            flush=True,
        )
    model = args.llm_model or llm_select.DEFAULT_MODEL
    frames_dir = out_dir / "frames"
    sheets_dir = out_dir / "contact_sheets"
    results = []
    for index, clip in enumerate(clips[: settings["max_clips"]]):
        start = float(clip.get("start") or 0)
        end = float(clip.get("end") or 0)
        times = frame_times(start, end, settings["frames"])
        frames = []
        labels = []
        for frame_index, timestamp in enumerate(times):
            frame_path = frames_dir / f"clip_{index:02d}_{frame_index:02d}.jpg"
            if extract_frame(video, timestamp, frame_path, settings["width"]):
                frames.append(frame_path)
                labels.append(f"#{index}  {pipeline.clock(timestamp)}")
        sheet = sheets_dir / f"clip_{index:02d}.jpg"
        sheet_ok = make_contact_sheet(
            frames,
            labels,
            sheet,
            settings["columns"],
            settings["width"],
        )
        analysis = vlm.unavailable("VLM unavailable")
        if vlm_ready and sheet_ok:
            try:
                analysis = vlm.analyze_contact_sheet(
                    sheet,
                    clip,
                    base_url=base_url,
                    model=model,
                    api_key=api_key,
                    timeout=settings["timeout"],
                    max_tokens=settings["max_tokens"],
                )
            except Exception as exc:
                analysis = vlm.unavailable(str(exc))
        results.append(
            {
                "candidate_id": clip.get("candidate_id"),
                "start": start,
                "end": end,
                "contact_sheet": sheet.relative_to(out_dir).as_posix() if sheet_ok else None,
                "frames": len(frames),
                **analysis,
            }
        )
        print(
            f"[visual] clip {index + 1}: frames={len(frames)} "
            f"score={analysis.get('visual_score')} vlm={analysis.get('vlm_used')}",
            flush=True,
        )
    payload = {
        "run_id": run_id,
        "video": video.relative_to(ROOT).as_posix()
        if video.is_relative_to(ROOT)
        else str(video),
        "vlm_ready": vlm_ready,
        "clips": results,
    }
    (out_dir / "visual_analysis.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    timings = {
        "run_id": run_id,
        "clips": len(results),
        "vlm_ready": vlm_ready,
        "total_seconds": round(time.time() - started, 1),
    }
    (out_dir / "visual_timings.json").write_text(
        json.dumps(timings, indent=1),
        encoding="utf-8",
    )
    print(f"[visual] done: {len(results)} clips", flush=True)
    return out_dir


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id")
    parser.add_argument("--out")
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--no-vlm", action="store_true")
    parser.add_argument("--max-clips", type=int, default=0)
    parser.add_argument("--llm-base-url", default=llm_select.DEFAULT_BASE_URL)
    parser.add_argument("--llm-model", default=llm_select.DEFAULT_MODEL)
    parser.add_argument("--llm-api-key-file")
    args = parser.parse_args()

    started = time.time()
    run_id = pipeline.resolve_run_id(args.run_id)
    if not run_id:
        raise SystemExit("missing run_id")
    archive = pipeline.HISTORY_DIR / run_id
    if not (archive / "run.json").is_file():
        raise SystemExit(f"history entry not found: {run_id}")
    if args.persist:
        pipeline.start_visual_run(run_id)
    try:
        out_dir = run(args, started, run_id)
    except Exception as exc:
        if args.persist:
            pipeline.mark_visual_failed(run_id, exc)
        raise
    if args.persist:
        pipeline.update_visual_after_run(run_id, out_dir)


if __name__ == "__main__":
    main()
