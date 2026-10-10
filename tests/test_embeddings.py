"""Tests for src/ml/embeddings.py (chunk → embed → weighted average).

Skipped where sentence-transformers isn't installed (the CI pytest job); runs in
the `ml` job. The last test loads the real pinned model (downloaded once, then
cached by CI).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

pytest.importorskip("sentence_transformers")

from src.ml import embeddings  # noqa: E402


class _FirstWordEncoder:
    """Stand-in model: a chunk's vector is a one-hot of its first word ("a" → [1, 0], "b" → [0, 1])."""

    def encode(self, sentences: list[str], **kwargs: Any) -> np.ndarray:
        assert kwargs["normalize_embeddings"] is True
        return np.array([[1.0, 0.0] if s.split()[0] == "a" else [0.0, 1.0] for s in sentences])


def test_chunk_text_splits_every_chunk_words() -> None:
    text = " ".join(f"w{i}" for i in range(320))

    chunks = embeddings.chunk_text(text, chunk_words=150)

    assert [len(c.split()) for c in chunks] == [150, 150, 20]
    assert " ".join(chunks) == text


def test_chunk_text_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="empty"):
        embeddings.chunk_text("   \n ")


def test_embed_texts_weights_chunks_by_words_and_normalizes() -> None:
    # 150 words starting with "a", then 50 starting with "b" → chunk weights 150 and 50.
    text = " ".join(["a"] * 150 + ["b"] * 50)

    vectors = embeddings.embed_texts([text, "b only"], model=_FirstWordEncoder())

    expected = np.array([150.0, 50.0]) / np.hypot(150.0, 50.0)
    np.testing.assert_allclose(vectors[0], expected, rtol=1e-6)
    np.testing.assert_allclose(vectors[1], [0.0, 1.0])
    assert vectors.dtype == np.float32


def test_embed_texts_of_nothing_is_an_empty_matrix() -> None:
    assert embeddings.embed_texts([]).shape == (0, embeddings.EMBEDDING_DIM)


def test_real_model_puts_similar_meanings_close() -> None:
    texts = [
        "Build ETL pipelines with Airflow and Spark",
        "Develop data workflows orchestrated in Airflow on Databricks",
        "Provide bedside care to patients in the ICU",
    ]

    vectors = embeddings.embed_texts(texts)

    assert vectors.shape == (3, embeddings.EMBEDDING_DIM)
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1.0, rtol=1e-5)
    similar, unrelated = vectors[0] @ vectors[1], vectors[0] @ vectors[2]
    assert similar > unrelated + 0.3
    np.testing.assert_allclose(embeddings.embed_texts(texts[:1])[0], vectors[0], atol=1e-5)  # deterministic
