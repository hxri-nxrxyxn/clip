#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUN_ID="${1:-${CLIP_RUN_ID:-}}"

if [[ -z "$RUN_ID" ]]; then
    if [[ -f "$ROOT/1-ingest/output/current_run_id" ]]; then
        RUN_ID="$(tr -d '[:space:]' < "$ROOT/1-ingest/output/current_run_id")"
    fi
fi

if [[ -z "$RUN_ID" ]]; then
    echo "usage: targeted_extract.sh [RUN_ID]" >&2
    exit 2
fi

OUT="$ROOT/2-transcribe/output/$RUN_ID/targeted"
mkdir -p "$OUT"
"$ROOT/.venv/bin/python" "$ROOT/app/qwen_server.py" stop || true

exec "$ROOT/.venv/bin/python" "$ROOT/app/targeted_extract.py" \
    --run-id "$RUN_ID" \
    --out "$OUT" \
    --persist \
    "${@:2}"
