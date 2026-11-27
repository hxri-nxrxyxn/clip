import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
STAGE = SCRIPT_DIR.parent
ROOT = STAGE.parent


def run_id():
    value = os.environ.get("CLIP_RUN_ID", "").strip()
    if value:
        return value
    pointer = ROOT / "1-ingest" / "output" / "current_run_id"
    try:
        return pointer.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def stage_paths(resolved=None):
    resolved = resolved or run_id()
    if resolved:
        return resolved, STAGE / "input" / resolved, STAGE / "output" / resolved
    return "", STAGE / "input", STAGE / "output"


if __name__ == "__main__":
    print(run_id())
