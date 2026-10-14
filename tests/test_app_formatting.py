"""Tests for src/app/formatting.py: how the app words and rounds numbers."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.app import formatting as fmt


def test_money_rounds_to_the_nearest_thousand() -> None:
    assert fmt.money(143_669) == "$144,000"
    assert fmt.money(None) == "—" and fmt.money(float("nan")) == "—"
    assert fmt.money_range(116_064, 171_274) == "$116,000 – $171,000"
    assert fmt.signed_money(15_250) == "+$15,000" and fmt.signed_money(-6_000) == "-$6,000"


def test_a_what_if_that_would_show_as_zero_reads_no_measurable_effect() -> None:
    assert fmt.model_impact_text(0.0) == "no measurable effect"
    assert fmt.model_impact_text(499.0) == "no measurable effect"
    assert fmt.model_impact_text(-120.0) == "no measurable effect"
    assert fmt.model_impact_text(786.0) == "+$1,000"
    assert fmt.model_impact_text(-4_200.0) == "-$4,000"
    assert fmt.model_impact_text(None) == "not enough data"


def test_median_difference_shows_its_sample_sizes() -> None:
    assert fmt.median_difference_text(14_500.0, 25, 28) == "+$15,000 (25 vs 28 postings)"  # half up, not to even
    assert fmt.median_difference_text(None, 2, 48) == "too few salaries to compare"


def test_window_text_explains_which_postings_were_searched() -> None:
    assert fmt.window_text({"window": "last_7_days", "since": date(2026, 10, 7)}) == (
        "Postings collected in the last 7 days (since Oct 7)."
    )
    latest = fmt.window_text({"window": "latest_collection", "since": date(2026, 10, 3)})
    assert latest.startswith("No postings for this role were collected in the last 7 days") and "(Oct 3)" in latest
    assert fmt.window_text({"window": "none", "since": None}) == "No postings for this role yet."


def test_labels_and_ages() -> None:
    assert fmt.role_label("machine learning engineer") == "Machine Learning Engineer"
    assert fmt.percent(0.3449) == "34%"
    now = datetime(2026, 10, 14, 9, tzinfo=timezone.utc)
    assert fmt.age_text(datetime(2026, 10, 14, 1, tzinfo=timezone.utc), now) == "today"
    assert fmt.age_text(datetime(2026, 10, 13, 22, tzinfo=timezone.utc), now) == "1 day ago"
    assert fmt.age_text(datetime(2026, 10, 3, tzinfo=timezone.utc), now) == "11 days ago"
