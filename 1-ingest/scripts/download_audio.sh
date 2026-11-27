#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT="$(cd "$STAGE/.." && pwd)"
OUT="$STAGE/output"
AUDIO_DIR="$OUT/audio"
TRANS_INPUT="$ROOT/2-transcribe/input"
HANDOFF="$TRANS_INPUT/audio16k_full.wav"
URL="${1:-}"

die() { printf '[ingest] ERROR: %s\n' "$*" >&2; exit 1; }

if [[ -z "$URL" && -f "$STAGE/input/url.txt" ]]; then
    URL="$(head -n 1 "$STAGE/input/url.txt" | tr -d '\r[:space:]')"
fi
if [[ -z "$URL" ]]; then
    printf 'usage: %s <url-or-media-file>\n' "$(basename "$0")" >&2
    printf '       or put a URL in %s\n' "$STAGE/input/url.txt" >&2
    exit 2
fi

command -v ffmpeg >/dev/null 2>&1 || die "ffmpeg not found"
command -v ffprobe >/dev/null 2>&1 || die "ffprobe not found"

YTDLP="$ROOT/.venv/bin/yt-dlp"
[[ -x "$YTDLP" ]] || YTDLP="$(command -v yt-dlp || true)"

mkdir -p "$AUDIO_DIR" "$TRANS_INPUT"
INFO_FILE=""

ARCHIVE_PY="$ROOT/.venv/bin/python"
if [[ "${CLIP_SKIP_ARCHIVE:-0}" != "1" && -x "$ARCHIVE_PY" && -f "$ROOT/app/pipeline.py" ]]; then
    "$ARCHIVE_PY" -c "import sys; sys.path.insert(0, '$ROOT/app'); import pipeline; pipeline.archive_current_run()" || true
fi

if [[ -f "$URL" ]]; then
    SRC="$(cd "$(dirname "$URL")" && pwd)/$(basename "$URL")"
    printf '[ingest] local source: %s\n' "$SRC"
else
    [[ -n "$YTDLP" ]] || die "yt-dlp not found"
    INCOMING="$AUDIO_DIR/.incoming"
    rm -rf "$INCOMING"
    mkdir -p "$INCOMING"
    YTDLP_ARGS=(
        --no-playlist
        --no-warnings
        --format "bestaudio/best"
        --write-info-json
        --output "$INCOMING/source.%(ext)s"
    )
    [[ -n "${YTDLP_COOKIES:-}" ]] && YTDLP_ARGS+=(--cookies "$YTDLP_COOKIES")
    [[ -n "${YTDLP_COOKIES_FROM_BROWSER:-}" ]] && YTDLP_ARGS+=(--cookies-from-browser "$YTDLP_COOKIES_FROM_BROWSER")
    printf '[ingest] downloading: %s\n' "$URL"
    "$YTDLP" "${YTDLP_ARGS[@]}" "$URL"
    SRC="$(find "$INCOMING" -maxdepth 1 -type f -name 'source.*' ! -name '*.part' ! -name '*.ytdl' ! -name '*.json' -printf '%T@ %p\n' | sort -nr | head -n 1 | cut -d' ' -f2-)"
    [[ -n "$SRC" && -f "$SRC" ]] || die "download produced no source file"
    if [[ -f "$INCOMING/source.info.json" ]]; then
        INFO_FILE="$OUT/source.info.json"
        mv -f "$INCOMING/source.info.json" "$INFO_FILE"
    fi
    EXT="${SRC##*.}"
    DEST="$AUDIO_DIR/source.$EXT"
    rm -f "$AUDIO_DIR"/source.*
    mv -f "$SRC" "$DEST"
    SRC="$DEST"
    rm -rf "$INCOMING"
fi

TMP="$AUDIO_DIR/audio16k_full.wav.tmp"
ffmpeg -nostdin -hide_banner -loglevel error -y -i "$SRC" \
    -vn -ac 1 -ar 16000 -c:a pcm_s16le -f wav "$TMP"

sample_rate="$(ffprobe -v error -select_streams a:0 -show_entries stream=sample_rate -of default=nw=1:nk=1 "$TMP")"
channels="$(ffprobe -v error -select_streams a:0 -show_entries stream=channels -of default=nw=1:nk=1 "$TMP")"
codec="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of default=nw=1:nk=1 "$TMP")"
[[ "$sample_rate" == "16000" && "$channels" == "1" && "$codec" == "pcm_s16le" ]] \
    || die "unexpected audio format: rate=$sample_rate channels=$channels codec=$codec"

duration="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$TMP")"
mv -f "$TMP" "$AUDIO_DIR/audio16k_full.wav"
cp -f "$AUDIO_DIR/audio16k_full.wav" "$HANDOFF.tmp"
mv -f "$HANDOFF.tmp" "$HANDOFF"

PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || PY="python3"
"$PY" - "$URL" "$SRC" "$AUDIO_DIR/audio16k_full.wav" "$HANDOFF" \
    "$sample_rate" "$channels" "$codec" "$duration" "$OUT/ingest.json" "$INFO_FILE" <<'PY'
import datetime
import json
import sys

url, src, wav, handoff, rate, channels, codec, duration, out, info_file = sys.argv[1:11]
payload = {
    "source_url": url,
    "source_file": src,
    "audio_16k": "output/audio/audio16k_full.wav",
    "transcribe_input": "2-transcribe/input/audio16k_full.wav",
    "sample_rate": int(rate),
    "channels": int(channels),
    "codec": codec,
    "duration_seconds": round(float(duration), 3),
    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
if info_file:
    try:
        with open(info_file, encoding="utf-8") as fh:
            info = json.load(fh)
    except (OSError, ValueError):
        info = {}
    payload["video_id"] = info.get("id")
    payload["title"] = info.get("title")
    payload["webpage_url"] = info.get("webpage_url") or info.get("original_url")
    payload["uploader"] = info.get("uploader")
    payload["source_duration_seconds"] = info.get("duration")
with open(out, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=1)
PY

printf '[ingest] source: %s\n' "$SRC"
printf '[ingest] normalized: %s (%s Hz, %s ch, %ss)\n' \
    "$AUDIO_DIR/audio16k_full.wav" "$sample_rate" "$channels" "$duration"
printf '[ingest] 2-transcribe input: %s\n' "$HANDOFF"
ls -lh "$AUDIO_DIR/audio16k_full.wav" "$HANDOFF"
