"""Tests for src/ml/nlp_pipeline.py (years of experience, boilerplate filter, output rows).

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


def test_strip_shared_sentences_removes_text_shared_across_titles() -> None:
    legal = "We are an equal opportunity employer."
    titles = ["data engineer", "data analyst", "ml engineer", "data engineer"]
    descriptions = [
        f"Build Spark pipelines. {legal}",
        f"Build dashboards in Tableau. {legal}",
        f"Train ranking models. {legal}",
        "Build Spark pipelines. Same job, another city.",
    ]

    stripped = nlp_pipeline.strip_shared_sentences(titles, descriptions)

    # The legal line appears under 3 titles → removed; "Build Spark pipelines." appears
    # twice but under one title (the same job in two cities) → kept.
    assert stripped == [
        "Build Spark pipelines.",
        "Build dashboards in Tableau.",
        "Train ranking models.",
        "Build Spark pipelines.\nSame job, another city.",
    ]


def test_strip_shared_sentences_keeps_a_description_it_would_empty() -> None:
    shared = "Join us."
    stripped = nlp_pipeline.strip_shared_sentences(["a", "b", "c"], [shared, shared, shared])

    assert stripped == [shared, shared, shared]


def test_embeddings_parquet_round_trip() -> None:
    import io

    import numpy as np
    import pyarrow.parquet as pq

    vectors = np.array([[0.6, 0.8], [1.0, 0.0]], dtype=np.float32)

    table = pq.read_table(io.BytesIO(nlp_pipeline.embeddings_parquet(["a", "b"], vectors, [3, 1])))

    assert table.column("job_id").to_pylist() == ["a", "b"]
    assert table.column("n_chunks").to_pylist() == [3, 1]
    np.testing.assert_allclose(np.array(table.column("embedding").to_pylist()), vectors)
    assert table.schema.metadata[b"model"] == b"sentence-transformers/all-MiniLM-L6-v2"


def test_topic_rows_and_posting_topic_rows() -> None:
    from datetime import datetime, timezone

    from src.ml.topics import Topic, TopicResult

    loaded_at = datetime(2026, 10, 9, tzinfo=timezone.utc)
    result = TopicResult(
        topics=[Topic(-1, "unassigned", (), 1), Topic(0, "spark, pipelines", ("spark", "pipelines"), 1)],
        assignments=[0, -1],
        probabilities=[0.9, 0.0],
    )

    assert nlp_pipeline.topic_rows(result, loaded_at) == [
        (-1, "unassigned", None, 1, loaded_at),
        (0, "spark, pipelines", "spark, pipelines", 1, loaded_at),
    ]
    assert nlp_pipeline.posting_topic_rows(["a", "b"], result, loaded_at) == [
        ("a", 0, 0.9, loaded_at),
        ("b", -1, 0.0, loaded_at),
    ]
