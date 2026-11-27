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
    echo "usage: 3-select/scripts/run.sh [RUN_ID]" >&2
    exit 2
fi

OUT="$ROOT/3-select/output/$RUN_ID"
mkdir -p "$OUT"

USE_LLM=1
for arg in "$@"; do
    [[ "$arg" == "--no-llm" ]] && USE_LLM=0
done
if [[ "$USE_LLM" == "1" ]]; then
    "$ROOT/.venv/bin/python" "$ROOT/app/qwen_server.py" ensure || echo "[select] Qwen unavailable; using fallback"
fi

exec "$ROOT/.venv/bin/python" "$ROOT/app/selection.py" \
    --run-id "$RUN_ID" \
    --out "$OUT" \
    --persist \
    "${@:2}"
