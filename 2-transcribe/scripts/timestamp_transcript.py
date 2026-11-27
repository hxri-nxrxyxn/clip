import json
import math
import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
STAGE = SCRIPT_DIR.parent
ROOT = STAGE.parent

RUN_ID = os.environ.get("CLIP_RUN_ID", "").strip()
if not RUN_ID:
    try:
        RUN_ID = (ROOT / "1-ingest" / "output" / "current_run_id").read_text(encoding="utf-8").strip()
    except OSError:
        RUN_ID = ""
OUT = STAGE / "output" / RUN_ID if RUN_ID else STAGE / "output"
SEGMENTS = OUT / "whisper_segments.json"
TRANSCRIPT = OUT / "transcript.txt"


def hhmmss(seconds):
    total = max(0, int(math.floor(seconds)))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def main():
    segments = json.load(open(SEGMENTS, encoding="utf-8"))
    lines = []
    for segment in segments:
        text = segment.get("text", "").strip()
        if not text:
            continue
        lines.append(f"[{hhmmss(segment['start'])}] {text}")
    with open(TRANSCRIPT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"[transcript] {len(lines)} lines -> {TRANSCRIPT.name}")


if __name__ == "__main__":
    main()
