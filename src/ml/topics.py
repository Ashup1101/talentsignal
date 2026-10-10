"""Topic clustering of job postings with BERTopic (Phase 5.1b).

Posting embeddings (src/ml/embeddings.py) → UMAP (384 → 10 dims, keeping
neighbours together) → HDBSCAN (dense groups; postings in no group are outliers,
topic -1, kept as "unassigned") → c-TF-IDF (each topic's most distinctive words).

Settings were chosen on the real postings (2026-10-09) for stability: HDBSCAN's
default "eom" selection swung between 2 and 17 topics depending only on the
random seed; "leaf" selection kept 8–9 topics (seed-to-seed adjusted Rand index
0.65 on average) at the cost of ~half the postings staying unassigned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from bertopic import BERTopic
from bertopic.vectorizers import ClassTfidfTransformer
from hdbscan import HDBSCAN
from scipy import sparse
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, CountVectorizer
from umap import UMAP

OUTLIER_TOPIC = -1
OUTLIER_LABEL = "unassigned"
RANDOM_STATE = 42  # UMAP is random; a fixed seed gives the same topics for the same data
UMAP_NEIGHBORS = 30  # wider neighbourhoods than the default 15 gave steadier topics
UMAP_DIMENSIONS = 10
MIN_TOPIC_SIZE = 10  # with ~700 postings; 15+ merged everything into a handful of topics
TOP_WORDS = 10
LABEL_WORDS = 4
# A keyword must appear in postings from this many employers, so employer names and
# in-house jargon ("slickdeals", "bmo") can't become a topic's keywords.
MIN_KEYWORD_EMPLOYERS = 3
# Words nearly every posting uses; they would top every topic's keywords.
# ("data" stays: removing it would also remove bigrams like "data engineer".)
GENERIC_JOB_WORDS = frozenset(
    "experience experienced work working team teams role roles job jobs position years year "
    "skills skill ability strong including required preferred requirements qualifications "
    "responsibilities candidate candidates opportunity opportunities company join using use "
    "new help support related knowledge understanding excellent level plus etc".split()
)


@dataclass(frozen=True)
class Topic:
    """One topic: its id, a short label, its most distinctive words and its size."""

    topic_id: int
    label: str
    top_words: tuple[str, ...]
    n_postings: int


@dataclass(frozen=True)
class TopicResult:
    """Topics (sorted by id, the outlier topic first if present) and per-posting assignments."""

    topics: list[Topic]
    assignments: list[int]
    probabilities: list[float]  # HDBSCAN membership strength, 0–1; 0 for outliers


def _label(words: list[str]) -> str:
    # "machine, learning, machine learning, ml" → "machine learning, ml": skip single
    # words already covered by a two-word phrase among the top words.
    phrases = [w for w in words if " " in w]
    covered = {part for p in phrases for part in p.split()}
    kept = [w for w in words if " " in w or w not in covered]
    return ", ".join(kept[:LABEL_WORDS])


def _clean(doc: str) -> str:
    # Exactly what BERTopic does to English text before counting words. The keyword
    # vocabulary must come from identical text: a listed term BERTopic never counts
    # ("data-driven" → "datadriven") makes c-TF-IDF divide by zero.
    return re.sub(r"[^A-Za-z0-9 ]+", "", doc.replace("\n", " ").replace("\t", " "))


def _vectorizer(vocabulary: list[str] | None = None) -> CountVectorizer:
    return CountVectorizer(
        stop_words=sorted(ENGLISH_STOP_WORDS | GENERIC_JOB_WORDS), ngram_range=(1, 2), vocabulary=vocabulary
    )


def keyword_vocabulary(docs: list[str], employers: list[str]) -> list[str]:
    """Words and two-word phrases used by at least MIN_KEYWORD_EMPLOYERS employers.

    Args:
        docs: Posting texts.
        employers: Each posting's employer, aligned with docs.

    Returns:
        The allowed keywords, sorted.

    Raises:
        ValueError: If docs and employers don't line up.
    """
    if len(docs) != len(employers):
        raise ValueError(f"{len(docs)} docs but {len(employers)} employers")
    vectorizer = _vectorizer()
    used = (vectorizer.fit_transform(docs) > 0).astype(np.int32)  # posting × term
    names = sorted(set(employers))
    index = {name: i for i, name in enumerate(names)}
    rows = [index[e] for e in employers]
    by_employer = sparse.csr_matrix((np.ones(len(rows)), (rows, range(len(rows)))), shape=(len(names), len(rows)))
    n_employers = np.asarray(((by_employer @ used) > 0).sum(axis=0)).ravel()
    terms = vectorizer.get_feature_names_out()
    return sorted(terms[n_employers >= MIN_KEYWORD_EMPLOYERS].tolist())


def build_model(vocabulary: list[str] | None = None) -> BERTopic:
    """Assemble BERTopic with this project's UMAP, HDBSCAN and keyword settings.

    Args:
        vocabulary: Allowed keywords (see keyword_vocabulary); None allows all words.

    Returns:
        An unfitted BERTopic model (embeddings are passed in, never computed by it).
    """
    return BERTopic(
        umap_model=UMAP(
            n_neighbors=UMAP_NEIGHBORS,
            n_components=UMAP_DIMENSIONS,
            min_dist=0.0,
            metric="cosine",
            random_state=RANDOM_STATE,
            n_jobs=1,  # a fixed random_state runs single-threaded anyway; saying so silences a warning
        ),
        hdbscan_model=HDBSCAN(
            min_cluster_size=MIN_TOPIC_SIZE, cluster_selection_method="leaf", prediction_data=True
        ),
        # No min_df: BERTopic counts words on one combined document PER TOPIC, so
        # min_df=2 would drop every word unique to one topic (the most telling ones).
        vectorizer_model=_vectorizer(vocabulary),
        ctfidf_model=ClassTfidfTransformer(reduce_frequent_words=True),
        top_n_words=TOP_WORDS,
    )


def fit_topics(docs: list[str], embeddings: np.ndarray, employers: list[str]) -> TopicResult:
    """Cluster documents into topics and describe each topic by its keywords.

    Args:
        docs: The texts that were embedded (used only to find each topic's keywords).
        embeddings: Their vectors, one row per doc (from embeddings.embed_texts).
        employers: Each doc's employer (keywords must be used by several employers).

    Returns:
        The topics and each doc's topic; outliers get topic -1 ("unassigned").

    Raises:
        ValueError: If docs, embeddings and employers don't line up.
    """
    if len(docs) != len(embeddings):
        raise ValueError(f"{len(docs)} docs but {len(embeddings)} embeddings")
    cleaned = [_clean(d) for d in docs]
    model = build_model(keyword_vocabulary(cleaned, employers))
    assignments, probabilities = model.fit_transform(cleaned, embeddings)
    assignments = [int(t) for t in assignments]
    sizes = {t: assignments.count(t) for t in set(assignments)}

    topics = []
    for topic_id in sorted(sizes):
        if topic_id == OUTLIER_TOPIC:
            topics.append(Topic(OUTLIER_TOPIC, OUTLIER_LABEL, (), sizes[topic_id]))
            continue
        words = [w for w, _ in model.get_topic(topic_id)][:TOP_WORDS]
        topics.append(Topic(topic_id, _label(words), tuple(words), sizes[topic_id]))
    probs = [0.0 if t == OUTLIER_TOPIC else float(p) for t, p in zip(assignments, probabilities, strict=True)]
    return TopicResult(topics, assignments, probs)
