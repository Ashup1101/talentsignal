"""NLP enrichment of job postings (Phase 5.1).

5.1a: years of experience. A spaCy rule-based Matcher finds phrases like "5+ years",
"3-5 yrs" or "three to five years of experience" in job descriptions. Only spaCy's
tokenizer is used (spacy.blank("en")), no statistical model: LIKE_NUM already
treats "five" and "5" alike.

Known limitation: "largest minimum" overstates postings that list education-tiered
alternatives ("diploma + 5 yrs or bachelor's + 3"): ~7% of postings with years
(39 of 521 on 2026-10-09).

5.1b: embeddings + topics. Sentences shared across 3+ different job titles (legal,
benefits and "About us" text) are removed first: left in, they grouped postings
by employer instead of by kind of work. The rest (title + description) is
embedded (src/ml/embeddings.py) to Parquet in the S3 curated bucket, then
clustered (src/ml/topics.py).

One run rebuilds ml.posting_nlp, ml.topics and ml.posting_topics in RDS (dbt
sources) in a single transaction, so the three always come from the same run.

Run locally:  python -m src.ml.nlp_pipeline
"""

from __future__ import annotations

import io
import logging
import re
import sys
from collections import defaultdict
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import spacy
from dotenv import load_dotenv
from psycopg2.extras import execute_values
from spacy.language import Language
from spacy.matcher import Matcher
from spacy.tokens import Doc, Span

from src.ingestion.s3_utils import require_env, upload_bytes
from src.ml.embeddings import CHUNK_WORDS, MODEL_NAME, MODEL_REVISION, chunk_text, embed_texts
from src.ml.topics import TopicResult, fit_topics
from src.processing.postgres import PostgresConfig

logger = logging.getLogger(__name__)

ML_SCHEMA = "ml"
# Table → (columns DDL, column names in insert order). Every run replaces all rows.
_TABLES = {
    "posting_nlp": (
        """job_id text primary key,
        years_min double precision,
        years_max double precision,
        years_mentions integer not null,
        years_evidence text""",
        ("job_id", "years_min", "years_max", "years_mentions", "years_evidence"),
    ),
    "topics": (
        """topic_id integer primary key,
        label text not null,
        top_words text,
        n_postings integer not null""",
        ("topic_id", "label", "top_words", "n_postings"),
    ),
    "posting_topics": (
        """job_id text primary key,
        topic_id integer not null,
        topic_probability double precision not null""",
        ("job_id", "topic_id", "topic_probability"),
    ),
}

# A sentence used under this many different job titles is boilerplate, not a
# description of the job (the same job posted in several cities keeps its text).
BOILERPLATE_MIN_TITLES = 3
EMBEDDINGS_KEY = f"embeddings/{MODEL_NAME.split('/')[-1]}/postings.parquet"
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")

MAX_YEARS = 30  # anything larger is company history or a typo, not a requirement
CONTEXT_WINDOW = 8  # tokens searched on each side for an "experience" word
_YEAR_WORDS = ["year", "years", "yr", "yrs"]
_EXPERIENCE_WORDS = {"experience", "experienced", "exp"}
# "at least 5", "minimum (of) 5", "more than 5", "over 5"
_REQUIREMENT_LEAD_INS = {"least", "minimum", "min", "over", "than"}
_NOT_A_REQUIREMENT_AFTER = {"ago", "old"}  # "10 years ago", "18 years old"
_NUMBER_WORDS = {
    word: value
    for value, word in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen "
        "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
    )
} | {"thirty": 30}


@dataclass(frozen=True)
class YearsMention:
    """One years-of-experience phrase found in a text."""

    text: str
    years_min: float
    years_max: float | None  # None when open-ended ("5+ years", "at least 5 years")


@dataclass(frozen=True)
class YearsSummary:
    """A posting's experience requirement: the mention with the largest minimum."""

    years_min: float | None
    years_max: float | None
    n_mentions: int
    evidence: str | None


def _normalize(text: str) -> str:
    # Make the tokenizer split "3–5" (en/em dash), "5+yrs" and "5yrs" into tokens.
    text = re.sub(r"[–—]", "-", text)
    text = re.sub(r"(\d)\+(?=[A-Za-z])", r"\1+ ", text)
    return re.sub(r"(\d)(?=(?:yrs?|years?)\b)", r"\1 ", text, flags=re.IGNORECASE)


@lru_cache(maxsize=1)
def _pipeline() -> tuple[Language, Matcher]:
    nlp = spacy.blank("en")
    num = {"LIKE_NUM": True}
    plus = {"ORTH": "+", "OP": "?"}
    close = {"ORTH": ")", "OP": "?"}
    year = {"LOWER": {"IN": _YEAR_WORDS}}
    matcher = Matcher(nlp.vocab)
    matcher.add(
        "YEARS",
        [
            [num, plus, close, year],  # 5 years, 5+ years, (5+) years
            [num, {"ORTH": "-"}, num, plus, close, year],  # 3-5 years
            [num, {"LOWER": {"IN": ["to", "or"]}}, num, plus, close, year],  # three to five years
        ],
        greedy="LONGEST",  # "3-5 years" is one mention, not also "5 years"
    )
    return nlp, matcher


def _number(token_text: str) -> float | None:
    text = token_text.lower().replace(",", "")
    if text in _NUMBER_WORDS:
        return float(_NUMBER_WORDS[text])
    try:
        return float(text)
    except ValueError:
        return None


def _mention(doc: Doc, span: Span) -> YearsMention | None:
    numbers = [_number(t.text) for t in span if t.like_num]
    if not numbers or any(n is None for n in numbers):
        return None
    low, high = min(numbers), max(numbers)
    after = doc[span.end].lower_ if span.end < len(doc) else ""
    if after in _NOT_A_REQUIREMENT_AFTER or high > MAX_YEARS:
        return None

    open_ended = any(t.text == "+" for t in span)
    is_range = len(numbers) == 2
    lead_in = any(t.lower_ in _REQUIREMENT_LEAD_INS for t in doc[max(0, span.start - 3) : span.start])
    window = doc[max(0, span.start - CONTEXT_WINDOW) : span.end + CONTEXT_WINDOW]
    about_experience = any(t.lower_ in _EXPERIENCE_WORDS for t in window)
    # Keep only phrases that read like a requirement, not e.g. "in business for 25 years".
    if not (open_ended or is_range or lead_in or about_experience):
        return None

    unbounded = open_ended or (lead_in and not is_range)
    return YearsMention(span.text, low, None if unbounded else high)


def _mentions(doc: Doc, matcher: Matcher) -> list[YearsMention]:
    found = []
    for _, start, end in sorted(matcher(doc), key=lambda m: m[1]):
        mention = _mention(doc, doc[start:end])
        if mention is not None:
            found.append(mention)
    return found


def extract_years(text: str | None) -> list[YearsMention]:
    """Find every years-of-experience requirement in a text.

    Args:
        text: A job description (or any text). None or blank yields no mentions.

    Returns:
        The mentions in reading order.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    nlp, matcher = _pipeline()
    return _mentions(nlp(_normalize(text)), matcher)


def summarize_years(mentions: list[YearsMention]) -> YearsSummary:
    """Reduce a posting's mentions to one requirement: the largest minimum.

    "5+ years overall, 2+ years with Spark" → 5: the overall requirement is
    usually the largest; tool-specific ones are smaller.

    Args:
        mentions: Output of extract_years.

    Returns:
        The summary; all fields empty when there are no mentions.
    """
    if not mentions:
        return YearsSummary(None, None, 0, None)
    best = max(mentions, key=lambda m: m.years_min)
    return YearsSummary(best.years_min, best.years_max, len(mentions), best.text)


def summarize_texts(texts: Iterable[str | None]) -> list[YearsSummary]:
    """Summarize many descriptions at once (batched through spaCy for speed).

    Args:
        texts: Job descriptions; None entries yield empty summaries.

    Returns:
        One YearsSummary per input, in order.
    """
    nlp, matcher = _pipeline()
    cleaned = [_normalize(t) if isinstance(t, str) else "" for t in texts]
    return [summarize_years(_mentions(doc, matcher)) for doc in nlp.pipe(cleaned, batch_size=64)]


def posting_rows(job_ids: list[str], descriptions: list[str | None], loaded_at: datetime) -> list[tuple]:
    """Build ml.posting_nlp rows: one per posting, with its years summary.

    Args:
        job_ids: Posting ids, aligned with descriptions.
        descriptions: Job descriptions (None allowed).
        loaded_at: Timezone-aware load time shared by every row in one run.

    Returns:
        (job_id, years_min, years_max, years_mentions, years_evidence, _loaded_at) tuples.
    """
    summaries = summarize_texts(descriptions)
    return [
        (job_id, s.years_min, s.years_max, s.n_mentions, s.evidence, loaded_at)
        for job_id, s in zip(job_ids, summaries, strict=True)
    ]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_BREAK.split(text) if s.strip()]


def _sentence_key(sentence: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", sentence.lower())).strip()


def strip_shared_sentences(titles: list[str], descriptions: list[str]) -> list[str]:
    """Remove sentences that appear under BOILERPLATE_MIN_TITLES or more different titles.

    Shared legal, benefits and company-intro text otherwise makes postings from
    one employer look alike. A description that would lose every sentence is
    kept whole.

    Args:
        titles: Normalized job titles, aligned with descriptions.
        descriptions: Job descriptions.

    Returns:
        The descriptions without shared sentences (sentences joined by newlines).
    """
    split = [_sentences(d or "") for d in descriptions]
    titles_per_sentence: dict[str, set[str]] = defaultdict(set)
    for title, sentences in zip(titles, split, strict=True):
        for sentence in sentences:
            titles_per_sentence[_sentence_key(sentence)].add(title)
    stripped = []
    for sentences in split:
        kept = [s for s in sentences if len(titles_per_sentence[_sentence_key(s)]) < BOILERPLATE_MIN_TITLES]
        stripped.append("\n".join(kept or sentences))
    return stripped


def embeddings_parquet(job_ids: list[str], embeddings: np.ndarray, n_chunks: list[int]) -> bytes:
    """Serialize posting embeddings as Parquet: job_id, n_chunks, embedding (float32[384]).

    Args:
        job_ids: Posting ids, one per embedding row.
        embeddings: (n, dim) float32 array.
        n_chunks: How many chunks each posting's text was split into.

    Returns:
        The Parquet file's bytes, with the model and chunking recorded in its metadata.
    """
    table = pa.table(
        {
            "job_id": pa.array(job_ids, pa.string()),
            "n_chunks": pa.array(n_chunks, pa.int32()),
            "embedding": pa.FixedSizeListArray.from_arrays(
                pa.array(embeddings.astype(np.float32).ravel()), embeddings.shape[1]
            ),
        }
    ).replace_schema_metadata(
        {
            "model": MODEL_NAME,
            "model_revision": MODEL_REVISION,
            "chunk_words": str(CHUNK_WORDS),
            "text": "title + description without sentences shared by 3+ job titles",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()


def topic_rows(result: TopicResult, loaded_at: datetime) -> list[tuple]:
    """Build ml.topics rows.

    Args:
        result: Output of topics.fit_topics.
        loaded_at: Load time shared by every row in one run.

    Returns:
        (topic_id, label, top_words, n_postings, _loaded_at) tuples; top_words is a
        comma-separated list, most distinctive first (NULL for the outlier topic).
    """
    return [
        (t.topic_id, t.label, ", ".join(t.top_words) or None, t.n_postings, loaded_at) for t in result.topics
    ]


def posting_topic_rows(job_ids: list[str], result: TopicResult, loaded_at: datetime) -> list[tuple]:
    """Build ml.posting_topics rows.

    Args:
        job_ids: Posting ids, in the order the topics were fitted.
        result: Output of topics.fit_topics.
        loaded_at: Load time shared by every row in one run.

    Returns:
        (job_id, topic_id, topic_probability, _loaded_at) tuples.
    """
    return [
        (job_id, topic, probability, loaded_at)
        for job_id, topic, probability in zip(job_ids, result.assignments, result.probabilities, strict=True)
    ]


def _replace_tables(config: PostgresConfig, rows_by_table: dict[str, list[tuple]]) -> None:
    # One transaction: readers see the previous complete tables until commit, and a
    # failure rolls back every table. Truncate (not drop) keeps dependent dbt views.
    with closing(config.connect()) as conn, conn, conn.cursor() as cur:
        cur.execute(f"create schema if not exists {ML_SCHEMA}")
        for table, rows in rows_by_table.items():
            ddl, columns = _TABLES[table]
            qualified = f"{ML_SCHEMA}.{table}"
            cur.execute(
                f"create table if not exists {qualified} "
                f"({ddl}, _loaded_at timestamp with time zone not null)"
            )
            cur.execute(f"truncate {qualified}")
            execute_values(
                cur, f"insert into {qualified} ({', '.join(columns)}, _loaded_at) values %s", rows, page_size=500
            )
            cur.execute(f"select count(*) from {qualified}")
            written = cur.fetchone()[0]
            if written != len(rows):
                raise RuntimeError(f"{qualified} has {written} rows; expected {len(rows)}")
            logger.info("%s: %d rows", qualified, written)


def run(config: PostgresConfig, curated_bucket: str) -> dict[str, int]:
    """Rebuild the ml.* tables and the posting embeddings from raw.jobs_clean.

    Reads raw.jobs_clean (not dbt views: dbt reads these outputs, so reading dbt
    here would be circular).

    Args:
        config: Database holding raw.jobs_clean; the ml.* tables are written there.
        curated_bucket: S3 bucket for the embeddings Parquet file.

    Returns:
        Rows written per ml table.

    Raises:
        RuntimeError: If there are no postings or a written row count is off.
    """
    with closing(config.connect()) as conn, conn.cursor() as cur:
        cur.execute(
            "select job_id, title, title_normalized, description, employer_normalized"
            " from raw.jobs_clean order by job_id"
        )
        postings = cur.fetchall()
    if not postings:
        raise RuntimeError("raw.jobs_clean is empty; run load_postgres first")
    job_ids = [p[0] for p in postings]
    descriptions = [p[3] for p in postings]
    loaded_at = datetime.now(timezone.utc)

    nlp_rows = posting_rows(job_ids, descriptions, loaded_at)
    with_years = sum(1 for r in nlp_rows if r[1] is not None)
    logger.info(
        "Years of experience: %d of %d postings (%.0f%%)",
        with_years, len(nlp_rows), 100 * with_years / len(nlp_rows),
    )

    stripped = strip_shared_sentences([p[2] or p[1] for p in postings], descriptions)
    texts = [f"{p[1]}\n{body}" for p, body in zip(postings, stripped, strict=True)]
    embeddings = embed_texts(texts)
    n_chunks = [len(chunk_text(t)) for t in texts]
    parquet = embeddings_parquet(job_ids, embeddings, n_chunks)
    upload_bytes(curated_bucket, EMBEDDINGS_KEY, parquet, "application/vnd.apache.parquet")
    logger.info(
        "Embedded %d postings (%d chunks) → s3://%s/%s",
        len(texts), sum(n_chunks), curated_bucket, EMBEDDINGS_KEY,
    )

    result = fit_topics(texts, embeddings, employers=[p[4] or "" for p in postings])
    unassigned = sum(t.n_postings for t in result.topics if t.topic_id < 0)
    logger.info(
        "Topics: %d; unassigned postings: %d (%.0f%%)",
        sum(t.topic_id >= 0 for t in result.topics), unassigned, 100 * unassigned / len(texts),
    )

    rows_by_table = {
        "posting_nlp": nlp_rows,
        "topics": topic_rows(result, loaded_at),
        "posting_topics": posting_topic_rows(job_ids, result, loaded_at),
    }
    _replace_tables(config, rows_by_table)
    return {table: len(rows) for table, rows in rows_by_table.items()}


def main() -> int:
    """Command-line entry point.

    Returns:
        Process exit code.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per HTTP request otherwise
    load_dotenv()
    run(PostgresConfig.from_env(), require_env("S3_CURATED_BUCKET"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
