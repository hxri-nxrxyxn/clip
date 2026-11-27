"""Web monitor entry point for the clip2 transcription and clipping pipeline."""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

from app import pipeline
from app.views import history, ingest, scaffold, select, settings, transcribe

if pipeline.JOBS.current() is None:
    pipeline.reconcile_current_job()

st.set_page_config(page_title="clip", layout="wide", initial_sidebar_state="expanded")

HISTORY_PAGE = st.Page(
    history.render,
    title="History",
    icon=":material/history:",
    default=True,
)
INGEST_PAGE = st.Page(
    ingest.render,
    title="Ingest",
    icon=":material/download:",
    url_path="ingest",
)
TRANSCRIBE_PAGE = st.Page(
    transcribe.render,
    title="Transcribe",
    icon=":material/graphic_eq:",
    url_path="transcribe",
)
SELECT_PAGE = st.Page(
    select.render,
    title="Select",
    icon=":material/filter_alt:",
    url_path="select",
)
REFRAME_PAGE = st.Page(
    scaffold.page_reframe,
    title="Reframe",
    icon=":material/crop:",
    url_path="reframe",
)
CAPTION_PAGE = st.Page(
    scaffold.page_caption,
    title="Caption",
    icon=":material/subtitles:",
    url_path="caption",
)
EXPORT_PAGE = st.Page(
    scaffold.page_export,
    title="Export",
    icon=":material/ios_share:",
    url_path="export",
)
SETTINGS_PAGE = st.Page(
    settings.render,
    title="Settings",
    icon=":material/settings:",
    url_path="settings",
)

pages = {
    "Jobs": [HISTORY_PAGE],
    "Pipeline": [
        INGEST_PAGE,
        TRANSCRIBE_PAGE,
        SELECT_PAGE,
        REFRAME_PAGE,
        CAPTION_PAGE,
        EXPORT_PAGE,
    ],
    "System": [SETTINGS_PAGE],
}

if "nav_to" in st.session_state:
    target = st.session_state.pop("nav_to")
    if target == "ingest":
        st.switch_page(INGEST_PAGE)

page = st.navigation(pages, position="sidebar", expanded=True)
page.run()
