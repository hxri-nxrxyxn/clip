#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOST="${APP_HOST:-0.0.0.0}"
PORT="${APP_PORT:-8501}"

cd "$ROOT"

exec "$ROOT/.venv/bin/python" -m streamlit run "$SCRIPT_DIR/streamlit_app.py" \
    --server.address "$HOST" \
    --server.port "$PORT" \
    --server.headless true \
    --server.fileWatcherType none \
    --browser.gatherUsageStats false
