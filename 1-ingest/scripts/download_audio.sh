#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT="$(cd "$STAGE/.." && pwd)"
OUT="$STAGE/output"
TRANS_INPUT="$ROOT/2-transcribe/input"
URL="${1:-}"
RUN_ID="${CLIP_RUN_ID:-}"
CREATED_AT="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"
PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || PY="python3"

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

if [[ "${CLIP_SKIP_ARCHIVE:-0}" != "1" && -x "$PY" && -f "$ROOT/app/pipeline.py" ]]; then
    "$PY" -c "import sys; sys.path.insert(0, '$ROOT/app'); import pipeline; pipeline.archive_current_run()" || true
fi

mkdir -p "$OUT" "$TRANS_INPUT"
INCOMING="$OUT/.incoming"
rm -rf "$INCOMING"
mkdir -p "$INCOMING"
INFO_TMP=""
SOURCE_TMP=""

if [[ -f "$URL" ]]; then
    SOURCE_TMP="$INCOMING/source.${URL##*.}"
    cp -f "$URL" "$SOURCE_TMP"
    printf '[ingest] local source: %s\n' "$URL"
else
    [[ -n "$YTDLP" ]] || die "yt-dlp not found"
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
    SOURCE_TMP="$(find "$INCOMING" -maxdepth 1 -type f -name 'source.*' ! -name '*.part' ! -name '*.ytdl' ! -name '*.json' -printf '%T@ %p\n' | sort -nr | head -n 1 | cut -d' ' -f2-)"
    [[ -n "$SOURCE_TMP" && -f "$SOURCE_TMP" ]] || die "download produced no source file"
    [[ -f "$INCOMING/source.info.json" ]] && INFO_TMP="$INCOMING/source.info.json"
fi

if [[ -z "$RUN_ID" ]]; then
    RUN_ID="$("$PY" - "$INFO_TMP" "$URL" "$CREATED_AT" "$ROOT" <<'PY'
import datetime
import json
import os
import sys

info_file, url, created_at, root = sys.argv[1:5]
sys.path.insert(0, os.path.join(root, "app"))
import pipeline

info = {}
if info_file:
    try:
        with open(info_file, encoding="utf-8") as fh:
            info = json.load(fh)
    except (OSError, ValueError):
        info = {}
video_id = info.get("id") or pipeline.slug(os.path.splitext(os.path.basename(url))[0] or "video")
created = datetime.datetime.fromisoformat(created_at)
print(pipeline.run_id_for_ingest({"created_at": created.isoformat()}, {"video_id": video_id}))
PY
)"
fi

JOB_OUT="$OUT/$RUN_ID"
AUDIO_DIR="$JOB_OUT/audio"
TRANS_JOB="$TRANS_INPUT/$RUN_ID"
HANDOFF="$TRANS_JOB/audio16k_full.wav"
INFO_FILE=""
mkdir -p "$AUDIO_DIR" "$TRANS_JOB"
rm -f "$AUDIO_DIR"/source.* "$JOB_OUT/ingest.json" "$JOB_OUT/source.info.json"

EXT="${SOURCE_TMP##*.}"
SRC="$AUDIO_DIR/source.$EXT"
mv -f "$SOURCE_TMP" "$SRC"
if [[ -n "$INFO_TMP" ]]; then
    INFO_FILE="$JOB_OUT/source.info.json"
    mv -f "$INFO_TMP" "$INFO_FILE"
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

"$PY" - "$URL" "$SRC" "$AUDIO_DIR/audio16k_full.wav" "$HANDOFF" \
    "$sample_rate" "$channels" "$codec" "$duration" "$JOB_OUT/ingest.json" "$INFO_FILE" \
    "$RUN_ID" "$CREATED_AT" <<'PY'
import json
import sys

(
    url,
    src,
    wav,
    handoff,
    rate,
    channels,
    codec,
    duration,
    out,
    info_file,
    run_id,
    created_at,
) = sys.argv[1:13]
payload = {
    "run_id": run_id,
    "source_url": url,
    "source_file": src,
    "audio_16k": "audio/audio16k_full.wav",
    "transcribe_input": f"2-transcribe/input/{run_id}/audio16k_full.wav",
    "sample_rate": int(rate),
    "channels": int(channels),
    "codec": codec,
    "duration_seconds": round(float(duration), 3),
    "created_at": created_at,
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

rm -rf "$INCOMING"
printf '%s' "$RUN_ID" > "$OUT/current_run_id"
printf '[ingest] run_id: %s\n' "$RUN_ID"
printf '[ingest] source: %s\n' "$SRC"
printf '[ingest] normalized: %s (%s Hz, %s ch, %ss)\n' \
    "$AUDIO_DIR/audio16k_full.wav" "$sample_rate" "$channels" "$duration"
printf '[ingest] 2-transcribe input: %s\n' "$HANDOFF"
ls -lh "$AUDIO_DIR/audio16k_full.wav" "$HANDOFF"
