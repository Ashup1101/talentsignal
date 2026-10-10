"""Tests for src/ml/nlp_pipeline.py (years-of-experience extraction).

Skipped where spaCy isn't installed (the CI pytest job); runs in the `ml` job.
"""

from __future__ import annotations

import pytest

pytest.importorskip("spacy")

from src.ml import nlp_pipeline  # noqa: E402


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("5+ years of experience in data engineering", (5, None)),
        ("3-5 years of experience", (3, 5)),
        ("3–5 yrs experience with SQL", (3, 5)),  # en dash
        ("three to five years of professional experience", (3, 5)),
        ("at least 4 years of experience", (4, None)),
        ("Minimum of 2 years building pipelines", (2, None)),
        ("Experience: 7 years", (7, 7)),
        ("5+yrs Python", (5, None)),
        ("(5+) years in analytics", (5, None)),
        ("1 year of experience preferred", (1, 1)),
    ],
)
def test_extract_years_reads_requirements(text: str, expected: tuple[float, float | None]) -> None:
    mentions = nlp_pipeline.extract_years(text)

    assert [(m.years_min, m.years_max) for m in mentions] == [expected]


@pytest.mark.parametrize(
    "text",
    [
        "Bachelor's degree or 4-year degree in Computer Science",
        "We have been in business for 25 years",
        "The company was founded 10 years ago",
        "Applicants must be 18 years old",
        "50+ years of combined experience on our team",
        "",
        None,
    ],
)
def test_extract_years_ignores_non_requirements(text: str | None) -> None:
    assert nlp_pipeline.extract_years(text) == []


def test_summary_uses_the_largest_minimum() -> None:
    mentions = nlp_pipeline.extract_years("5+ years overall, 2+ years with Spark and 3 years of AWS experience")

    summary = nlp_pipeline.summarize_years(mentions)

    assert (summary.years_min, summary.years_max, summary.n_mentions) == (5, None, 3)
    assert summary.evidence == "5+ years"


def test_summarize_texts_matches_one_by_one() -> None:
    texts = ["3-5 years of experience", None, "no numbers here", "at least 4 years of experience"]

    batched = nlp_pipeline.summarize_texts(texts)

    assert batched == [nlp_pipeline.summarize_years(nlp_pipeline.extract_years(t)) for t in texts]
    assert [s.years_min for s in batched] == [3, None, None, 4]


def test_posting_rows_shape_and_largest_minimum() -> None:
    from datetime import datetime, timezone

    loaded_at = datetime(2026, 10, 10, tzinfo=timezone.utc)
    rows = nlp_pipeline.posting_rows(
        ["a", "b"], ["5+ years overall, 2+ years with Spark", None], loaded_at
    )

    assert rows == [("a", 5.0, None, 2, "5+ years", loaded_at), ("b", None, None, 0, None, loaded_at)]
