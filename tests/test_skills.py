"""Tests for the shared skill dictionary (src/skills/dictionary.py). No Spark needed."""

from __future__ import annotations

import pytest

from src.skills import dictionary


@pytest.mark.parametrize(
    ("text", "expected", "not_expected"),
    [
        ("Experience with Python, Go, and Rust", {"Python", "Go", "Rust"}, set()),
        ("We go above and beyond. Go-to-market strategy.", set(), {"Go"}),
        ("Golang microservices", {"Go", "Microservices"}, set()),
        ("Statistical modeling in Python or R.", {"Python", "R", "Statistics"}, set()),
        ("Lead R&D initiatives", set(), {"R"}),
        ("C++ and C# required", {"C++", "C#"}, set()),
        ("PostgreSQL and NoSQL stores", {"PostgreSQL", "NoSQL"}, {"SQL"}),
        ("JavaScript and TypeScript", {"JavaScript", "TypeScript"}, {"Java"}),
        ("You will excel at storytelling", set(), {"Excel"}),
        ("Advanced Excel and Power BI", {"Excel", "Power BI"}, set()),
        ("Star and snowflake schema design", set(), {"Snowflake"}),
        ("Snowflake, dbt and Airflow", {"Snowflake", "dbt", "Airflow"}, set()),
        ("Built ETL with PySpark on AWS (S3, EMR)", {"ETL", "Spark", "AWS", "S3", "EMR"}, set()),
        ("Be the glue between teams", set(), {"AWS Glue"}),
        ("Goal setting, forecasting, and monitoring key metrics", set(), {"Time Series"}),
        ("Time-series forecasting models (ARIMA)", {"Time Series"}, set()),
    ],
)
def test_find_skills(text: str, expected: set[str], not_expected: set[str]) -> None:
    found = set(dictionary.find_skills(text))
    assert expected <= found, f"missing {expected - found}"
    assert not (not_expected & found), f"false positives {not_expected & found}"


def test_find_skills_returns_dictionary_order_without_duplicates() -> None:
    found = dictionary.find_skills("SQL and Python. More Python, more SQL.")
    assert found == ["Python", "SQL"]  # SKILLS lists Python before SQL


@pytest.mark.parametrize("text", [None, "", "   ", 42])
def test_find_skills_handles_missing_or_non_text_input(text: object) -> None:
    assert dictionary.find_skills(text) == []  # type: ignore[arg-type]


def test_every_skill_has_a_pattern_and_known_category() -> None:
    categories = {"language", "data_engineering", "database", "cloud", "devops", "ml_ai", "analytics_bi", "web"}
    assert set(dictionary.skill_patterns()) == set(dictionary.SKILLS)
    assert {category for category, _ in dictionary.SKILLS.values()} <= categories
