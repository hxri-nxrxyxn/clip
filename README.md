# clip

Stage-based audio transcription and captioning pipeline.

## Stages

Each stage contains `input/`, `output/`, `services/`, and `scripts/`.

| Stage | Purpose |
| --- | --- |
| `1-ingest` | Download and normalize source audio |
| `2-transcribe` | Whisper transcription, YAMNet audio tags, timestamped and tagged transcripts |
| `3-select` | Highlight selection (scaffold) |
| `4-reframe` | Reframe selected clips (scaffold) |
| `5-caption` | Render captions onto video (scaffold) |
| `6-export` | Final packaging (scaffold) |

## Current status

- `1-ingest` and `2-transcribe` are implemented.
- `2-transcribe` produces the timestamped transcript, YAMNet tags, and tagged TXT/VTT/JSON.
- `3-select`, `4-reframe`, `5-caption`, and `6-export` are scaffolds.
- Speaker diarization is not implemented yet.

## Run

```bash
1-ingest/scripts/run.sh "https://www.youtube.com/watch?v=..."
2-transcribe/scripts/run.sh
```

`1-ingest/scripts/run.sh` also accepts a local media file instead of a URL, or reads
the URL from `1-ingest/input/url.txt`. It writes the normalized 16 kHz mono WAV to
`1-ingest/output/audio/audio16k_full.wav` and hands it off to
`2-transcribe/input/audio16k_full.wav` automatically.

Optional yt-dlp inputs:

- `YTDLP_COOKIES=/path/to/cookies.txt`
- `YTDLP_COOKIES_FROM_BROWSER=chrome`

Golden transcription checks:

```bash
2-transcribe/scripts/test_golden_clips.sh
```

## Web monitor

A Streamlit app opens on History, lets you select any job, create new jobs from Ingest, re-run individual stages, and inspect transcripts plus activity charts. Full jobs run ingest and transcribe together.

```bash
.venv/bin/pip install -r app/requirements.txt
app/run.sh
```

Open `http://<host>:8501/`. Defaults:

- `APP_HOST=0.0.0.0`
- `APP_PORT=8501`

Set `APP_HOST=127.0.0.1` to restrict access to this machine. There is no
authentication: anyone who can reach the server can run stages and handoffs.

## Required local assets

These are intentionally not committed:

- `2-transcribe/services/yamnet/yamnet.tflite`
- `2-transcribe/services/whisper/models/` (Whisper model cache)
- input audio under `1-ingest/output/` or `2-transcribe/input/`
- the host `.venv` used by scripts such as `audio_tags.py` and `merge_tags.py`

Generated audio, transcripts, model caches, and the virtual environment are ignored by Git.
