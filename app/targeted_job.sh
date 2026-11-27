#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_ID="${1:-}"

if [[ -z "$RUN_ID" ]]; then
    echo "usage: targeted_job.sh RUN_ID [targeted_prototype.py args...]" >&2
    exit 2
fi
shift

OUT="$ROOT/app/history/$RUN_ID/targeted"
exec "$ROOT/.venv/bin/python" "$SCRIPT_DIR/targeted_prototype.py" \
    --run-id "$RUN_ID" \
    --out "$OUT" \
    --persist \
    "$@"
