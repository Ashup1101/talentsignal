"""Tests for src/ml/topics.py (BERTopic with this project's settings).

Synthetic data with a known answer: three well-separated groups of vectors, each
with its own vocabulary. Skipped where BERTopic isn't installed (the CI pytest
job); runs in the `ml` job.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("bertopic")

from src.ml import topics  # noqa: E402

_VOCAB = [
    "spark pipelines airflow warehouse ingestion",
    "patients clinical hospital nursing care",
    "dashboards tableau reporting stakeholders kpis",
]


def _three_groups(per_group: int = 40) -> tuple[list[str], np.ndarray, np.ndarray]:
    # Every doc gets its own employer, so the employer rule allows every word.
    rng = np.random.default_rng(0)
    centers = rng.normal(size=(len(_VOCAB), 384))
    docs, vectors, truth = [], [], []
    for group, words in enumerate(_VOCAB):
        for _ in range(per_group):
            v = centers[group] + 0.05 * rng.normal(size=384)
            vectors.append(v / np.linalg.norm(v))
            truth.append(group)
            docs.append(f"{words} {words}")
    return docs, np.array(vectors, dtype=np.float32), np.array(truth)


@pytest.fixture(scope="module")
def fitted() -> tuple[topics.TopicResult, np.ndarray]:
    docs, vectors, truth = _three_groups()
    return topics.fit_topics(docs, vectors, _employers(docs)), truth


def _employers(docs: list[str]) -> list[str]:
    return [f"employer {i}" for i in range(len(docs))]


def test_every_topic_is_one_group_and_every_group_is_found(fitted: tuple[topics.TopicResult, np.ndarray]) -> None:
    result, truth = fitted
    assigned = np.array(result.assignments)

    found = set()
    for topic in result.topics:
        if topic.topic_id == topics.OUTLIER_TOPIC:
            continue
        groups = set(truth[assigned == topic.topic_id])
        assert len(groups) == 1, f"topic {topic.topic_id} mixes groups {groups}"
        found |= groups
        # The keywords come from that group's vocabulary.
        assert topic.top_words[0] in _VOCAB[groups.pop()].split()
    assert found == {0, 1, 2}


def test_sizes_and_probabilities_are_consistent(fitted: tuple[topics.TopicResult, np.ndarray]) -> None:
    result, truth = fitted

    assert sum(t.n_postings for t in result.topics) == len(truth) == len(result.assignments)
    for topic_id, probability in zip(result.assignments, result.probabilities, strict=True):
        assert 0.0 <= probability <= 1.0
        if topic_id == topics.OUTLIER_TOPIC:
            assert probability == 0.0


def test_same_input_gives_same_topics(fitted: tuple[topics.TopicResult, np.ndarray]) -> None:
    result, _ = fitted
    docs, vectors, _ = _three_groups()

    assert topics.fit_topics(docs, vectors, _employers(docs)).assignments == result.assignments


def test_punctuated_text_fits() -> None:
    # Regression: the keyword vocabulary once kept "data-driven" while BERTopic counted
    # "datadriven" → a zero count → "Input contains infinity".
    docs, vectors, _ = _three_groups()
    punctuated = [f"{d} data-driven, e.g. (A/B) tests;\nhands-on" for d in docs]

    result = topics.fit_topics(punctuated, vectors, _employers(punctuated))

    assert len(result.assignments) == len(docs)


def test_label_skips_words_covered_by_a_phrase() -> None:
    words = ["machine", "learning", "machine learning", "ml", "models", "model"]

    assert topics._label(words) == "machine learning, ml, models, model"


def test_keyword_vocabulary_drops_words_of_too_few_employers() -> None:
    docs = ["clinical analytics acme", "clinical reporting acme", "clinical analytics", "clinical analytics"]
    employers = ["Acme", "Acme", "Beta", "Gamma"]

    vocabulary = topics.keyword_vocabulary(docs, employers)

    # "clinical" and "analytics" are used by 3 employers; "acme" and "reporting" by one.
    assert {"clinical", "analytics", "clinical analytics"} <= set(vocabulary)
    assert not {"acme", "reporting"} & set(vocabulary)


def test_fit_topics_rejects_misaligned_input() -> None:
    with pytest.raises(ValueError, match="2 docs but 1 embeddings"):
        topics.fit_topics(["a", "b"], np.zeros((1, 384), dtype=np.float32), ["x", "y"])
