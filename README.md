# clip

Stage-based audio transcription and captioning pipeline.

## Stages

Each stage contains `input/`, `output/`, `services/`, and `scripts/`.

| Stage | Purpose |
| --- | --- |
| `1-ingest` | Download and normalize source audio |
| `2-transcribe` | Whisper transcription, YAMNet audio tags, timestamped transcript |
| `3-select` | Highlight selection (scaffold) |
| `4-reframe` | Reframe selected clips (scaffold) |
| `5-caption` | Build transcript captions with audio tags |
| `6-export` | Final packaging (scaffold) |

## Current status

- `1-ingest` and `2-transcribe` are implemented.
- `5-caption` builds the tagged transcript from `2-transcribe` output.
- `3-select`, `4-reframe`, and `6-export` are scaffolds.
- Speaker diarization is not implemented yet.

## Run

```bash
1-ingest/scripts/run.sh
cp 1-ingest/output/audio/audio16k_full.wav 2-transcribe/input/
2-transcribe/scripts/run.sh
```

Then hand off to captioning:

```bash
cp 2-transcribe/output/whisper_words.json \
   2-transcribe/output/audio_tags.json \
   2-transcribe/output/metadata.json \
   5-caption/input/
5-caption/scripts/run.sh
```

Golden transcription checks:

```bash
2-transcribe/scripts/test_golden_clips.sh
```

## Required local assets

These are intentionally not committed:

- `2-transcribe/services/yamnet/yamnet.tflite`
- `2-transcribe/services/whisper/models/` (Whisper model cache)
- input audio under `1-ingest/output/` or `2-transcribe/input/`
- the host `.venv` used by scripts such as `audio_tags.py` and `merge_tags.py`

Generated audio, transcripts, model caches, and the virtual environment are ignored by Git.
