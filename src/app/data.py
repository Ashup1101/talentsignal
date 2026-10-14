"""Read-only data access for the Streamlit app (Phase 6 step 2).

Everything the pages show comes from here:
- PostgreSQL as app_reader (SELECT-only on the dbt schemas and ml.*), through a
  small thread-safe connection pool (Streamlit serves each session on a thread);
- the Phase 5 exports in the S3 curated bucket (salary model, its card, the
  posting embeddings), via boto3's default credentials: .env keys on the laptop,
  the EC2 instance role on the server.

Results are cached for CACHE_SECONDS (the pipeline refreshes once a night). No
Streamlit imports: functions return plain dicts or pandas DataFrames, which keeps
them testable without a browser. A page can't change the cached data: results are
deep copies, and values nested in cells are immutable (skills are tuples,
embedding vectors are read-only arrays).
"""

from __future__ import annotations

import copy
import io
import json
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from decimal import Decimal
from functools import lru_cache, wraps
from typing import Any, TypeVar

import boto3
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from botocore.exceptions import BotoCoreError, ClientError
from psycopg2.pool import ThreadedConnectionPool

from src.ingestion.s3_utils import require_env
from src.ml.artifacts import POSTING_EMBEDDINGS_KEY, SALARY_CARD_KEY, SALARY_MODEL_KEY
from src.processing.postgres import PostgresConfig

CACHE_SECONDS = 3600
POOL_MAX_CONNECTIONS = 4

T = TypeVar("T")

_POSTINGS_SQL = """
    select
        f.job_id, r.role_name, f.job_title, f.employer_name,
        l.city, l.state_code, l.location_name, f.is_remote,
        f.posted_date, f.fetched_at,
        f.seniority_effective, f.seniority_source, f.experience_years_min, f.experience_years_max,
        f.salary_min_annual, f.salary_mid_annual, f.salary_max_annual, f.has_salary,
        f.skill_count, coalesce(s.skills, '{}'::text[]) as skills,
        p.topic_id, t.topic_label,
        f.apply_link
    from analytics_marts.fact_job_postings as f
    join analytics_marts.dim_role as r on r.role_key = f.role_key
    join analytics_marts.dim_location as l on l.location_key = f.location_key
    left join (
        select job_id, array_agg(skill_name order by skill_name) as skills
        from analytics_staging.stg_skills
        group by job_id
    ) as s on s.job_id = f.job_id
    left join analytics_staging.stg_posting_topics as p on p.job_id = f.job_id
    left join analytics_staging.stg_topics as t on t.topic_id = p.topic_id
    order by f.fetched_at desc, f.job_id
"""


def ttl_cache(seconds: float) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Cache a function's results per arguments for `seconds`, thread-safely.

    Hits return a deep copy, so callers can't change what's cached. The wrapped
    function gains cache_clear().

    Args:
        seconds: How long a result stays valid.

    Returns:
        The decorator.
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        entries: dict[tuple, tuple[float, T]] = {}
        lock = threading.Lock()

        @wraps(func)
        def wrapper(*args: Any) -> T:
            now = time.monotonic()
            with lock:
                hit = entries.get(args)
            if hit is None or now - hit[0] >= seconds:
                hit = (now, func(*args))
                with lock:
                    entries[args] = hit
            return copy.deepcopy(hit[1])

        wrapper.cache_clear = entries.clear  # type: ignore[attr-defined]
        return wrapper

    return decorator


@lru_cache(maxsize=1)
def _pool() -> ThreadedConnectionPool:
    config = PostgresConfig.from_env(user_var="APP_DB_USER", password_var="APP_DB_PASSWORD")
    return ThreadedConnectionPool(1, POOL_MAX_CONNECTIONS, **config.connect_kwargs())


@contextmanager
def _connection() -> Iterator[Any]:
    pool = _pool()
    conn = pool.getconn()
    try:
        conn.autocommit = True  # plain SELECTs: no transaction left open between queries
        yield conn
    except Exception:
        pool.putconn(conn, close=True)  # it may be broken (e.g. RDS restarted): don't reuse it
        raise
    pool.putconn(conn)


def _query(sql: str) -> pd.DataFrame:
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(sql)
        frame = pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])
    # psycopg2 returns NUMERIC as Decimal; pages and models want floats.
    for column in frame.columns:
        if frame[column].map(lambda v: isinstance(v, Decimal)).any():
            frame[column] = frame[column].map(lambda v: float(v) if isinstance(v, Decimal) else v)
    return frame


@ttl_cache(CACHE_SECONDS)
def postings() -> pd.DataFrame:
    """Every posting with its role, location, skills, salary, seniority and topic.

    Returns:
        One row per posting, newest fetch first. `skills` is a tuple per row;
        `topic_id` is -1 for postings in no topic and NaN for postings the NLP
        step hasn't processed yet.
    """
    frame = _query(_POSTINGS_SQL)
    frame["skills"] = frame["skills"].map(tuple)
    return frame


@ttl_cache(CACHE_SECONDS)
def skill_demand() -> pd.DataFrame:
    """Per role × skill: share of the role's postings mentioning it, rank, salary comparison.

    Returns:
        analytics_marts.mart_role_skill_profile, ordered by role and demand rank.
    """
    return _query("select * from analytics_marts.mart_role_skill_profile order by role_name, demand_rank")


@ttl_cache(CACHE_SECONDS)
def salary_bands() -> pd.DataFrame:
    """Per role: posted salary percentiles next to the BLS median.

    Returns:
        analytics_marts.mart_salary_bands, ordered by role.
    """
    return _query("select * from analytics_marts.mart_salary_bands order by role_name")


@ttl_cache(CACHE_SECONDS)
def skill_demand_history() -> pd.DataFrame:
    """Per collection week × role × skill: share of the role's collected postings mentioning it.

    Returns:
        analytics_marts.mart_skill_demand (weeks the role wasn't sampled are absent).
    """
    return _query(
        "select * from analytics_marts.mart_skill_demand order by search_role, skill_name, collection_week"
    )


@ttl_cache(CACHE_SECONDS)
def skill_demand_forecast() -> pd.DataFrame:
    """Per role × skill: the forecast gate's verdict and, once enough weeks, Prophet forecasts.

    Returns:
        analytics_staging.stg_skill_demand_forecast (forecast_status, observed_weeks,
        last observed share, forecast_week / share_forecast / share_lower / share_upper).
    """
    return _query(
        "select * from analytics_staging.stg_skill_demand_forecast"
        " order by search_role, skill_name, forecast_week"
    )


@ttl_cache(CACHE_SECONDS)
def job_insights() -> pd.DataFrame:
    """BERTopic topics with their sizes and keywords.

    Returns:
        One row per topic (topic_id -1 = postings in no topic) with
        share_of_postings and top_words as a list, most distinctive first.
    """
    topics = _query(
        "select topic_id, topic_label, topic_top_words, n_postings"
        " from analytics_staging.stg_topics order by topic_id"
    )
    topics["share_of_postings"] = topics["n_postings"] / topics["n_postings"].sum()
    # NULL keywords (the "unassigned" topic) arrive as NaN, which is truthy: check for text.
    topics["top_words"] = topics.pop("topic_top_words").map(lambda w: w.split(", ") if isinstance(w, str) else [])
    return topics


@lru_cache(maxsize=1)
def _s3() -> Any:
    # boto3's default credential chain: AWS_* env vars (laptop) or the instance role (EC2).
    return boto3.client("s3", region_name=require_env("AWS_REGION"))


def _download(key: str) -> bytes:
    bucket = require_env("S3_CURATED_BUCKET")
    try:
        return _s3().get_object(Bucket=bucket, Key=key)["Body"].read()
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
            raise FileNotFoundError(
                f"s3://{bucket}/{key} not found; the nightly pipeline exports it (see CLAUDE.md Phase 5)"
            ) from exc
        raise RuntimeError(f"Could not read s3://{bucket}/{key}: {exc}") from exc
    except BotoCoreError as exc:
        raise RuntimeError(f"Could not read s3://{bucket}/{key}: {exc}") from exc


@ttl_cache(CACHE_SECONDS)
def salary_model_json() -> dict:
    """The exported XGBoost salary model, as its parsed JSON.

    Returns:
        The model JSON (XGBRegressor.load_model accepts it re-encoded as bytes).
    """
    return json.loads(_download(SALARY_MODEL_KEY))


@ttl_cache(CACHE_SECONDS)
def salary_model_card() -> dict:
    """The salary model's card: feature spec, baselines, what-if skills, CV MAE, use_model.

    Returns:
        The parsed feature_spec.json.
    """
    return json.loads(_download(SALARY_CARD_KEY))


@ttl_cache(CACHE_SECONDS)
def posting_embeddings() -> pd.DataFrame:
    """Posting embeddings from the NLP step.

    Returns:
        Columns job_id, n_chunks and embedding (float32 array of 384 values per
        row); frame.attrs holds the file metadata (model, model_revision,
        chunk_words, created_at) so the app can check it embeds resumes the same way.
    """
    table = pq.read_table(io.BytesIO(_download(POSTING_EMBEDDINGS_KEY)))
    matrix = np.asarray(table.column("embedding").to_pylist(), dtype=np.float32)
    matrix.flags.writeable = False  # rows are views of it, so they're read-only too
    frame = pd.DataFrame(
        {
            "job_id": table.column("job_id").to_pylist(),
            "n_chunks": table.column("n_chunks").to_pylist(),
            "embedding": list(matrix),
        }
    )
    frame.attrs = {k.decode(): v.decode() for k, v in (table.schema.metadata or {}).items()}
    return frame
