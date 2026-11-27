#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_ID="${1:-}"

if [[ -z "$RUN_ID" ]]; then
    echo "usage: targeted_job.sh RUN_ID [targeted.py args...]" >&2
    exit 2
fi
shift

exec bash "$ROOT/3-select/scripts/run.sh" "$RUN_ID" "$@"
