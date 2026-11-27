# clip2

Production-grade stage-based audio transcription, YAMNet tagging, and LLM clip selection pipeline.

```mermaid
flowchart LR
    Source([URL or Media File]) --> Ingest[1-ingest\nyt-dlp]
    Ingest --> Transcribe[2-transcribe\nWhisper + YAMNet]
    Transcribe --> Select[3-select\nTargeted Whisper + Qwen]
    Select --> Reframe[4-reframe\nscaffold]
    Reframe --> Caption[5-caption\nscaffold]
    Caption --> Export[6-export\nscaffold]

    subgraph Core App Architecture
        cli[app.cli\nUnified CLI]
        orch[app.orchestrator\nExecution & Handoffs]
        store[app.storage\nState & Archives]
        models[app.models\nTyped Dataclasses]
        views[app.views\nStreamlit Dashboard]
    end

    orch --> Ingest
    orch --> Transcribe
    orch --> Select
```

## Stages

Each stage contains `input/`, `output/`, `services/`, and `scripts/`.

| Stage | Purpose |
| --- | --- |
| `1-ingest` | Download and normalize source audio to 16 kHz mono WAV |
| `2-transcribe` | Whisper transcription, YAMNet audio event tagging, timestamped TXT/VTT/JSON |
| `3-select` | YAMNet-guided targeted Whisper transcription and Qwen LLM clip selection |
| `4-reframe` | Reframe selected clips (scaffold) |
| `5-caption` | Render captions onto video (scaffold) |
| `6-export` | Final video packaging (scaffold) |

## Quickstart

### 1. Unified Command Line Interface (CLI)

```bash
# Run full pipeline with a YouTube URL or local file
python3 -m app.cli run pipeline --target "https://www.youtube.com/watch?v=..."

# Run an individual stage
python3 -m app.cli run 2-transcribe --run-id <run_id>

# Run targeted clip selection with Qwen LLM
python3 -m app.cli targeted <run_id>

# Migrate or cleanup workspace files
python3 -m app.cli layout migrate --run-id <run_id>
python3 -m app.cli layout cleanup --run-id <run_id>
```

### 2. Streamlit Web Monitor

```bash
app/run.sh
```
Opens the web monitor on `http://127.0.0.1:8501/` to visualize audio activity heatmaps, inspect transcripts, launch targeted runs, and configure settings.

## Developer Quality & Verification

The project adheres to strict code quality standards:
- **Linting & Formatting:** `ruff check app tests` & `ruff format app tests`
- **Type Checking:** `mypy` type analysis on all core application modules
- **Automated Tests:** Comprehensive unit test suite covering audio DSP, VTT cues, layout, CLI, LLM selection, and analytics.

```bash
# Run all quality checks
make check

# Run test suite with coverage
make coverage

# Format codebase
make fmt
```

## Directory Structure

```text
├── app/
│   ├── cli.py             # Main CLI entrypoint
│   ├── models.py          # Typed domain dataclasses
│   ├── orchestrator.py    # Pipeline execution & stage coordination
│   ├── storage.py         # State, run pointers, & archival helpers
│   ├── archive.py         # Historical run & targeted job persistence
│   ├── audio_utils.py     # Reusable audio DSP (WAV reading, RMS dB, YAMNet classes)
│   ├── vtt_utils.py       # WebVTT formatting, cue timestamps, sanitization
│   ├── llm_select.py      # Qwen client & heuristic clip selection fallback
│   ├── views/             # Decomposed Streamlit view modules (History, Ingest, etc.)
│   └── streamlit_app.py   # Multi-page web dashboard router
├── 1-ingest/              # Stage 1: Media ingestion
├── 2-transcribe/          # Stage 2: Whisper + YAMNet transcription & tagging
├── 3-select/              # Stage 3: Targeted selection
└── tests/                 # Automated pytest unit test suite (60+ tests)
```
