#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STAGE="${1:-}"
RUN_ID="${2:-}"
URL="${3:-}"
PY="$ROOT/.venv/bin/python"

export CLIP_ROOT="$ROOT"
export CLIP_RUN_ID="$RUN_ID"
export CLIP_STAGE="$STAGE"

case "$STAGE" in
    1-ingest)
        if [[ -n "$URL" ]]; then
            CLIP_SKIP_ARCHIVE=1 bash "$ROOT/1-ingest/scripts/run.sh" "$URL"
        else
            CLIP_SKIP_ARCHIVE=1 bash "$ROOT/1-ingest/scripts/run.sh"
        fi
        "$PY" - <<'PY'
import os
import sys

sys.path.insert(0, os.path.join(os.environ["CLIP_ROOT"], "app"))
import pipeline

pipeline.update_job_after_stage(os.environ["CLIP_RUN_ID"], "1-ingest")
PY
        ;;
    2-transcribe)
        "$PY" - <<'PY'
import os
import sys

sys.path.insert(0, os.path.join(os.environ["CLIP_ROOT"], "app"))
import pipeline

pipeline.prepare_stage_workspace(os.environ["CLIP_RUN_ID"], "2-transcribe")
PY
        bash "$ROOT/2-transcribe/scripts/run.sh"
        "$PY" - <<'PY'
import os
import sys

sys.path.insert(0, os.path.join(os.environ["CLIP_ROOT"], "app"))
import pipeline

pipeline.update_job_after_stage(os.environ["CLIP_RUN_ID"], "2-transcribe")
PY
        ;;
    *)
        echo "unsupported stage: $STAGE" >&2
        exit 2
        ;;
esac
