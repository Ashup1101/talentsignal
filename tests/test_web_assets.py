"""The web app's sample resume is the made-up test fixture (no personal data ships)."""

from __future__ import annotations

from pathlib import Path

from tests.fixtures.make_resume_pdf import RESUME_PATH

WEB_SAMPLE = Path(__file__).resolve().parents[1] / "web" / "public" / "sample-resume.pdf"


def test_web_sample_resume_is_the_made_up_fixture() -> None:
    assert WEB_SAMPLE.read_bytes() == RESUME_PATH.read_bytes()
