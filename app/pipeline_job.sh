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

bash "$ROOT/2-transcribe/scripts/run.sh"
