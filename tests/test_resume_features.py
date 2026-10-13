"""Tests for src/ml/resume_features.py (resume PDF → skills → salary-model features).

Uses tests/fixtures/resume_sample.pdf, a made-up text-based resume. Skipped where
pdfplumber isn't installed (the CI pytest job); runs in the `ml` job.
"""

from __future__ import annotations

import builtins

import pytest

pytest.importorskip("pdfplumber")

from src.ml import features, resume_features  # noqa: E402
from src.ml.features import UNKNOWN, FeatureSpec, Profile  # noqa: E402
from tests.fixtures.make_resume_pdf import RESUME_LINES, RESUME_PATH, pdf_with_lines  # noqa: E402

EXPECTED_SKILLS = {"Python", "SQL", "Spark", "Airflow", "AWS", "dbt", "Docker", "PostgreSQL"}
SPEC = FeatureSpec(
    roles=("data analyst", "data engineer"),
    seniorities=("mid", "senior", UNKNOWN),
    states=("NY", "TX", UNKNOWN),
    skills=("AWS", "Excel", "Python", "Spark", "Tableau"),
)


def test_fixture_matches_its_generator() -> None:
    assert RESUME_PATH.read_bytes() == pdf_with_lines(RESUME_LINES)


def test_extract_text_reads_every_line() -> None:
    text = resume_features.extract_text(RESUME_PATH.read_bytes())

    assert text.splitlines() == RESUME_LINES


def test_skills_come_from_the_shared_dictionary() -> None:
    text = resume_features.extract_text(RESUME_PATH.read_bytes())

    assert set(resume_features.find_skills(text)) == EXPECTED_SKILLS  # "Apache Spark"/"PySpark" → Spark


def test_build_features_is_the_training_function() -> None:
    skills = resume_features.find_skills(resume_features.extract_text(RESUME_PATH.read_bytes()))

    row = resume_features.build_features(skills, "data engineer", "senior", "TX", False, SPEC)

    expected = features.build_features([Profile("data engineer", "senior", "TX", False, frozenset(skills))], SPEC)
    assert row.equals(expected)
    assert list(row.columns) == SPEC.names
    assert row.loc[0, "skill=Spark"] == 1.0 and row.loc[0, "skill=Excel"] == 0.0
    assert row.loc[0, "skill_count"] == len(EXPECTED_SKILLS)


def test_scanned_pdf_without_text_gets_a_clear_message() -> None:
    with pytest.raises(resume_features.NoTextError, match="Scanned or image-only"):
        resume_features.extract_text(pdf_with_lines([]))


def test_non_pdf_bytes_are_rejected() -> None:
    with pytest.raises(ValueError, match="isn't a readable PDF"):
        resume_features.extract_text(b"not a pdf at all")


def test_extraction_never_writes_a_file(monkeypatch: pytest.MonkeyPatch) -> None:
    # Resumes are personal data: parsing must stay in memory.
    real_open = builtins.open

    def read_only_open(file: object, mode: str = "r", *args: object, **kwargs: object) -> object:
        assert not set(mode) & set("wax+"), f"tried to open {file!r} with mode {mode!r}"
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", read_only_open)

    assert resume_features.extract_text(RESUME_PATH.read_bytes())
