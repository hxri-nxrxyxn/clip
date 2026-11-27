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

exec "$ROOT/.venv/bin/python" "$ROOT/app/targeted.py" \
    --run-id "$RUN_ID" \
    --out "$OUT" \
    --persist \
    "${@:2}"
