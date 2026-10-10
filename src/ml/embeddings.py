"""Text embeddings with sentence-transformers (Phase 5.1b).

all-MiniLM-L6-v2 turns a text into 384 numbers; texts with similar meaning get
vectors pointing in similar directions (cosine similarity near 1). The model reads
at most 256 word-pieces (~190 words) while a median job description has ~790
words, so a text is split into CHUNK_WORDS-word chunks, every chunk is embedded,
and the chunk vectors are averaged (weighted by words) and scaled to length 1.
Postings and, in Phase 6, resumes go through this same function, so their
vectors are comparable.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from typing import Any, Protocol

import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
# Pinned so the pipeline and the app always load identical weights.
MODEL_REVISION = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"
EMBEDDING_DIM = 384
# Our postings average ~1.3 word-pieces per word: 150-word chunks fit the 256-piece
# window 99% of the time (200-word chunks overflowed 55%, measured 2026-10-09).
CHUNK_WORDS = 150
BATCH_SIZE = 64


class Encoder(Protocol):
    """Anything with SentenceTransformer's encode(); lets tests pass a stand-in."""

    def encode(self, sentences: list[str], **kwargs: Any) -> np.ndarray: ...


@lru_cache(maxsize=1)
def load_model() -> SentenceTransformer:
    """Load the pinned embedding model once per process, on CPU.

    CPU (not the Mac's GPU) gives the same numbers as the CPU-only app server.
    The local cache is tried first: a cached model then needs no Hugging Face
    requests (each load otherwise makes ~9, against an anonymous rate limit).

    Returns:
        The SentenceTransformer model.
    """
    try:
        return SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION, device="cpu", local_files_only=True)
    except OSError:  # not cached yet: download it once
        return SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION, device="cpu")


def chunk_text(text: str, chunk_words: int = CHUNK_WORDS) -> list[str]:
    """Split a text into consecutive chunks of at most chunk_words words.

    Args:
        text: Any text; whitespace is normalized.
        chunk_words: Maximum words per chunk.

    Returns:
        The chunks in order.

    Raises:
        ValueError: If the text has no words (an empty text has no meaning to embed).
    """
    words = text.split()
    if not words:
        raise ValueError("Cannot embed an empty text")
    return [" ".join(words[i : i + chunk_words]) for i in range(0, len(words), chunk_words)]


def embed_texts(texts: Sequence[str], model: Encoder | None = None) -> np.ndarray:
    """Embed whole texts of any length: chunk, embed each chunk, average.

    Args:
        texts: Texts to embed (e.g. posting title + description, or a resume).
        model: Encoder to use; defaults to the pinned all-MiniLM-L6-v2.

    Returns:
        float32 array of shape (len(texts), 384); every row has length 1, so a dot
        product between two rows is their cosine similarity.

    Raises:
        ValueError: If any text is empty.
    """
    if not texts:
        return np.empty((0, EMBEDDING_DIM), dtype=np.float32)
    chunks: list[str] = []
    owners: list[int] = []
    for i, text in enumerate(texts):
        for chunk in chunk_text(text):
            chunks.append(chunk)
            owners.append(i)

    encoder = model if model is not None else load_model()
    vectors = np.asarray(
        encoder.encode(chunks, batch_size=BATCH_SIZE, normalize_embeddings=True, show_progress_bar=False),
        dtype=np.float32,
    )
    # Weight by words so a short tail chunk counts less than a full one.
    weights = np.array([len(c.split()) for c in chunks], dtype=np.float32)[:, None]
    summed = np.zeros((len(texts), vectors.shape[1]), dtype=np.float32)
    np.add.at(summed, owners, vectors * weights)
    return summed / np.linalg.norm(summed, axis=1, keepdims=True)
