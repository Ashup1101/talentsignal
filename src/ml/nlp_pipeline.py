"""NLP enrichment of job postings (Phase 5.1).

5.1a: years of experience. A spaCy rule-based Matcher finds phrases like "5+ years",
"3-5 yrs" or "three to five years of experience" in job descriptions. Only spaCy's
tokenizer is used (spacy.blank("en")), no statistical model: LIKE_NUM already
treats "five" and "5" alike. Results go to ml.posting_nlp in RDS (a dbt source).

Known limitation: "largest minimum" overstates postings that list education-tiered
alternatives ("diploma + 5 yrs or bachelor's + 3"): ~7% of postings with years
(39 of 521 on 2026-10-09).

Run locally:  python -m src.ml.nlp_pipeline
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

import spacy
from dotenv import load_dotenv
from psycopg2.extras import execute_values
from spacy.language import Language
from spacy.matcher import Matcher
from spacy.tokens import Doc, Span

from src.processing.postgres import PostgresConfig

logger = logging.getLogger(__name__)

ML_SCHEMA = "ml"
POSTING_NLP_TABLE = f"{ML_SCHEMA}.posting_nlp"
_POSTING_NLP_DDL = f"""
    create table if not exists {POSTING_NLP_TABLE} (
        job_id text primary key,
        years_min double precision,
        years_max double precision,
        years_mentions integer not null,
        years_evidence text,
        _loaded_at timestamp with time zone not null
    )
"""

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


def run(config: PostgresConfig) -> int:
    """Rebuild ml.posting_nlp from raw.jobs_clean in a single transaction.

    Reads raw.jobs_clean (not dbt views: dbt reads this table, so reading dbt here
    would be circular). Readers keep seeing the previous complete table until commit;
    a failure rolls everything back.

    Args:
        config: Target database.

    Returns:
        Number of rows written.

    Raises:
        RuntimeError: If there are no postings or the written row count is off.
    """
    with closing(config.connect()) as conn, conn, conn.cursor() as cur:
        cur.execute("select job_id, description from raw.jobs_clean order by job_id")
        postings = cur.fetchall()
        if not postings:
            raise RuntimeError("raw.jobs_clean is empty; run load_postgres first")
        rows = posting_rows([p[0] for p in postings], [p[1] for p in postings], datetime.now(timezone.utc))

        cur.execute(f"create schema if not exists {ML_SCHEMA}")
        cur.execute(_POSTING_NLP_DDL)
        cur.execute(f"truncate {POSTING_NLP_TABLE}")  # keeps dependent dbt views
        execute_values(
            cur,
            f"insert into {POSTING_NLP_TABLE} "
            "(job_id, years_min, years_max, years_mentions, years_evidence, _loaded_at) values %s",
            rows,
            page_size=500,
        )
        cur.execute(f"select count(*) from {POSTING_NLP_TABLE}")
        written = cur.fetchone()[0]
        if written != len(rows):
            raise RuntimeError(f"{POSTING_NLP_TABLE} has {written} rows; expected {len(rows)}")

    with_years = sum(1 for r in rows if r[1] is not None)
    logger.info(
        "Wrote %d rows to %s; %d (%.0f%%) state years of experience",
        written, POSTING_NLP_TABLE, with_years, 100 * with_years / written,
    )
    return written


def main() -> int:
    """Command-line entry point.

    Returns:
        Process exit code.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv()
    run(PostgresConfig.from_env())
    return 0


if __name__ == "__main__":
    sys.exit(main())
