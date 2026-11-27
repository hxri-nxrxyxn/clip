"""Scaffold view placeholder for unimplemented stages."""

import streamlit as st

from app import pipeline
from app.views._shared import job_picker


def render(stage_id: str) -> None:
    job = job_picker()
    stage = pipeline.STAGES[stage_id]
    st.title(stage["title"])
    st.caption(stage["description"])
    if job:
        st.caption(job["label"])
    st.caption("This stage is a scaffold and is not implemented yet.")


def page_reframe() -> None:
    render("4-reframe")


def page_caption() -> None:
    render("5-caption")


def page_export() -> None:
    render("6-export")
