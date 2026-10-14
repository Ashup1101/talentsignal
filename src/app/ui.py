"""Shared Streamlit setup for every page (Phase 6 step 4).

Each page starts with `from src.app import ui`: importing the src.app package pins
OMP_NUM_THREADS before PyTorch or XGBoost load (see src/app/__init__.py). Pages
run as separate scripts, so anything they share lives here.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import streamlit as st
from dotenv import load_dotenv
from xgboost import XGBRegressor

from src.app import data, serving

T = TypeVar("T")

# A made-up, text-based resume (the test fixture) for visitors without one at hand.
SAMPLE_RESUME = Path(__file__).with_name("assets") / "sample_resume.pdf"


def setup_page(title: str, icon: str) -> None:
    """First call on every page: browser tab title/icon, wide layout, settings from .env.

    Args:
        title: Page name.
        icon: A Material icon, e.g. ':material/description:'.
    """
    st.set_page_config(page_title=f"{title} · TalentSignal", page_icon=icon, layout="wide")
    load_dotenv()  # the laptop's .env; on the server the environment comes from Docker


def load(func: Callable[[], T], what: str) -> T:
    """Call a data loader; if it fails, show a friendly error and stop the page.

    Args:
        func: e.g. data.postings.
        what: What it loads, for the message ('the job postings').

    Returns:
        The loader's result.
    """
    try:
        return func()
    except Exception as exc:  # any backend failure: say so plainly, no stack trace
        st.error(
            f"Couldn't load {what} right now ({type(exc).__name__}). "
            "The data service may be briefly unavailable; please try again in a minute."
        )
        st.stop()
        raise  # unreachable: st.stop() ends the script


@st.cache_resource(ttl=3600)
def salary_model() -> XGBRegressor:
    """The exported salary model, loaded once per process and refreshed hourly.

    Returns:
        The single-threaded model (serving.load_model).
    """
    return serving.load_model(data.salary_model_json())


def privacy_note() -> None:
    """The promise shown wherever a resume is involved."""
    st.caption(
        ":material/lock: Your resume is read in memory only to compute this page. "
        "It is never saved, logged or shared, and it is gone when you close the tab."
    )
