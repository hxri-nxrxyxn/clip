#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT="$(cd "$STAGE/.." && pwd)"
PY="$ROOT/.venv/bin/python"

eval "$("$PY" "$ROOT/app/config.py" --env)"
DC=(docker compose -f "$STAGE/services/whisper/docker-compose.yml" run --rm -T)
if [[ -f "$STAGE/input/selected_threshold.txt" ]]; then
    LP="$(tr -d '[:space:]' < "$STAGE/input/selected_threshold.txt")"
else
    LP="$WHISPER_LOG_PROB_THRESHOLD"
fi
DC+=(-e "WHISPER_LOG_PROB_THRESHOLD=$LP")

"${DC[@]}" whisper
"$PY" "$SCRIPT_DIR/trim_outro.py"
"$PY" "$SCRIPT_DIR/audio_tags.py"
"$PY" "$SCRIPT_DIR/timestamp_transcript.py"
"$PY" "$SCRIPT_DIR/merge_tags.py"
