#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
URL="${1:-}"
export CLIP_SKIP_ARCHIVE=1

if [[ -n "$URL" ]]; then
    bash "$ROOT/1-ingest/scripts/run.sh" "$URL"
else
    bash "$ROOT/1-ingest/scripts/run.sh"
fi

RUN_ID="$(tr -d '[:space:]' < "$ROOT/1-ingest/output/current_run_id")"
export CLIP_RUN_ID="$RUN_ID"
bash "$ROOT/2-transcribe/scripts/run.sh"
