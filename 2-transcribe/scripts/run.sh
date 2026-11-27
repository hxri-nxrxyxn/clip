#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT="$(cd "$STAGE/.." && pwd)"
PY="$ROOT/.venv/bin/python"

RUN_ID="${CLIP_RUN_ID:-}"
if [[ -z "$RUN_ID" && -f "$ROOT/1-ingest/output/current_run_id" ]]; then
    RUN_ID="$(tr -d '[:space:]' < "$ROOT/1-ingest/output/current_run_id")"
fi
[[ -n "$RUN_ID" ]] || { echo "[transcribe] ERROR: missing CLIP_RUN_ID" >&2; exit 2; }
export CLIP_RUN_ID="$RUN_ID"

INPUT_DIR="$STAGE/input/$RUN_ID"
OUTPUT_DIR="$STAGE/output/$RUN_ID"
mkdir -p "$INPUT_DIR" "$OUTPUT_DIR/audio"

WHISPER_LOG_PROB_THRESHOLD="$("$PY" "$ROOT/app/config.py" --get whisper.log_prob_threshold)"

DC=(docker compose -f "$STAGE/services/whisper/docker-compose.yml" run --rm -T
    -w "/work/output/$RUN_ID"
    -e "AUDIO=/work/input/$RUN_ID/audio16k_full.wav")
if [[ -f "$INPUT_DIR/selected_threshold.txt" ]]; then
    LP="$(tr -d '[:space:]' < "$INPUT_DIR/selected_threshold.txt")"
elif [[ -f "$STAGE/input/selected_threshold.txt" ]]; then
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
