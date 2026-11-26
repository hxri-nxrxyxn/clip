#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT="$(cd "$STAGE/.." && pwd)"
OUT="$STAGE/output"
AUDIO_DIR="$OUT/audio"
URL="${1:-https://www.youtube.com/watch?v=Q9BVIwyUr9k}"

mkdir -p "$AUDIO_DIR"
rm -f "$AUDIO_DIR"/source.*

YTDLP="$ROOT/.venv/bin/yt-dlp"
if [[ ! -x "$YTDLP" ]]; then
    YTDLP="yt-dlp"
fi

"$YTDLP" --no-warnings -f "bestaudio" -o "$AUDIO_DIR/source.%(ext)s" "$URL"
SRC="$(find "$AUDIO_DIR" -maxdepth 1 -type f -name 'source.*' | sort | tail -n 1)"

ffmpeg -hide_banner -loglevel error -y -i "$SRC" \
    -ac 1 -ar 16000 -c:a pcm_s16le "$AUDIO_DIR/audio16k_full.wav"

echo "source: $SRC"
ls -lh "$AUDIO_DIR"
