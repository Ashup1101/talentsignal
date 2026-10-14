"""Tests for src/app/data.py with a stub database and stubbed S3 (no network, no AWS).

The database is a fake psycopg2 pool; S3 is botocore's Stubber, which fails any
call that wasn't explicitly stubbed.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import numpy as np
import psycopg2
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber

from src.app import data
from src.ml import artifacts

CACHED = (
    data.postings, data.skill_demand, data.salary_bands, data.job_insights,
    data.salary_model_json, data.salary_model_card, data.posting_embeddings,
)
BUCKET = "test-curated"


class _FakeCursor:
    def __init__(self, tables: dict[str, tuple[list[str], list[tuple]]], log: list[str]) -> None:
        self._tables, self._log = tables, log
        self.description: list[SimpleNamespace] = []
        self._rows: list[tuple] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        self._log.append(sql)
        for relation, (columns, rows) in self._tables.items():
            if relation in sql:
                if rows is None:
                    raise psycopg2.OperationalError("server closed the connection unexpectedly")
                self.description = [SimpleNamespace(name=c) for c in columns]
                self._rows = rows
                return
        raise AssertionError(f"unexpected query: {sql}")

    def fetchall(self) -> list[tuple]:
        return self._rows


class _FakePool:
    """Stands in for psycopg2's ThreadedConnectionPool; records what comes back."""

    def __init__(self, tables: dict[str, tuple[list[str], list[tuple] | None]]) -> None:
        self.tables, self.queries, self.returned = tables, [], []

    def getconn(self) -> SimpleNamespace:
        return SimpleNamespace(autocommit=False, cursor=lambda: _FakeCursor(self.tables, self.queries))

    def putconn(self, conn: object, close: bool = False) -> None:
        self.returned.append(close)


@pytest.fixture(autouse=True)
def _fresh_caches() -> Iterator[None]:
    for func in CACHED:
        func.cache_clear()
    yield
    for func in CACHED:
        func.cache_clear()


def _install_pool(monkeypatch: pytest.MonkeyPatch, tables: dict) -> _FakePool:
    pool = _FakePool(tables)
    monkeypatch.setattr(data, "_pool", lambda: pool)
    return pool


POSTING_COLUMNS = [
    "job_id", "role_name", "salary_mid_annual", "skills", "topic_id", "topic_label", "fetched_at",
]
POSTING_ROWS = [
    ("a", "data engineer", Decimal("150000.5"), ["SQL", "Spark"], 0, "data engineer, pipelines",
     datetime(2026, 10, 13, tzinfo=timezone.utc)),
    ("b", "data analyst", None, [], -1, "unassigned", datetime(2026, 10, 3, tzinfo=timezone.utc)),
]


def test_postings_converts_numbers_and_freezes_skills(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _install_pool(monkeypatch, {"fact_job_postings": (POSTING_COLUMNS, POSTING_ROWS)})

    frame = data.postings()

    assert list(frame.columns) == POSTING_COLUMNS
    assert frame.loc[0, "salary_mid_annual"] == 150000.5 and isinstance(frame.loc[0, "salary_mid_annual"], float)
    assert frame.loc[0, "skills"] == ("SQL", "Spark") and frame.loc[1, "skills"] == ()
    assert "analytics_marts.dim_role" in pool.queries[0] and "stg_posting_topics" in pool.queries[0]
    assert pool.returned == [False]  # the connection went back to the pool, not closed


def test_results_are_cached_for_an_hour_and_returned_as_copies(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _install_pool(monkeypatch, {"fact_job_postings": (POSTING_COLUMNS, POSTING_ROWS)})
    clock = [1000.0]
    monkeypatch.setattr(data.time, "monotonic", lambda: clock[0])

    first = data.postings()
    first.loc[0, "role_name"] = "changed by a page"
    clock[0] += data.CACHE_SECONDS - 1
    second = data.postings()
    clock[0] += 2
    data.postings()

    assert second.loc[0, "role_name"] == "data engineer"  # the cache wasn't touched
    assert len(pool.queries) == 2  # one query, one cache hit, one refresh after the hour


def test_a_failed_query_discards_the_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _install_pool(monkeypatch, {"mart_salary_bands": (["role_name"], None)})

    with pytest.raises(psycopg2.OperationalError):
        data.salary_bands()

    assert pool.returned == [True]  # closed, so a broken connection is never reused


def test_skill_demand_and_salary_bands_read_their_marts(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _install_pool(
        monkeypatch,
        {
            "mart_role_skill_profile": (
                ["role_name", "skill_name", "share_of_role_postings", "demand_rank"],
                [("data engineer", "SQL", Decimal("0.79"), 1)],
            ),
            "mart_salary_bands": (["role_name", "salary_median"], [("data engineer", Decimal("165000"))]),
        },
    )

    demand, bands = data.skill_demand(), data.salary_bands()

    assert demand.loc[0, "share_of_role_postings"] == pytest.approx(0.79)
    assert bands.loc[0, "salary_median"] == 165000.0
    assert "order by role_name, demand_rank" in pool.queries[0]


def test_job_insights_splits_keywords_and_adds_shares(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_pool(
        monkeypatch,
        {
            "stg_topics": (
                ["topic_id", "topic_label", "topic_top_words", "n_postings"],
                [(-1, "unassigned", None, 30), (0, "clinical, health", "clinical, health, data analyst", 10)],
            )
        },
    )

    topics = data.job_insights()

    assert topics["top_words"].tolist() == [[], ["clinical", "health", "data analyst"]]
    assert topics["share_of_postings"].tolist() == [0.75, 0.25]


@pytest.fixture
def s3(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stubber]:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("S3_CURATED_BUCKET", BUCKET)
    data._s3.cache_clear()
    with Stubber(data._s3()) as stubber:
        yield stubber
        stubber.assert_no_pending_responses()
    data._s3.cache_clear()


def _object(stubber: Stubber, key: str, body: bytes) -> None:
    stubber.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(body), len(body))},
        expected_params={"Bucket": BUCKET, "Key": key},
    )


def test_salary_model_card_and_model_come_from_s3(s3: Stubber) -> None:
    _object(s3, artifacts.SALARY_CARD_KEY, json.dumps({"use_model": True, "n_trees": 59}).encode())
    _object(s3, artifacts.SALARY_MODEL_KEY, json.dumps({"learner": {}, "version": [3, 2, 0]}).encode())

    assert data.salary_model_card() == {"use_model": True, "n_trees": 59}
    assert data.salary_model_json() == {"learner": {}, "version": [3, 2, 0]}


def test_posting_embeddings_are_read_only_vectors_with_metadata(s3: Stubber) -> None:
    vectors = np.array([[0.6, 0.8], [1.0, 0.0]], dtype=np.float32)
    table = pa.table(
        {
            "job_id": ["a", "b"],
            "n_chunks": pa.array([3, 1], pa.int32()),
            "embedding": pa.FixedSizeListArray.from_arrays(pa.array(vectors.ravel()), 2),
        }
    ).replace_schema_metadata({"model": "sentence-transformers/all-MiniLM-L6-v2", "chunk_words": "150"})
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    _object(s3, artifacts.POSTING_EMBEDDINGS_KEY, buffer.getvalue())

    frame = data.posting_embeddings()

    assert frame["job_id"].tolist() == ["a", "b"] and frame["n_chunks"].tolist() == [3, 1]
    np.testing.assert_allclose(np.vstack(frame["embedding"]), vectors)
    assert frame.attrs == {"model": "sentence-transformers/all-MiniLM-L6-v2", "chunk_words": "150"}
    with pytest.raises(ValueError, match="read-only"):
        frame.loc[0, "embedding"][0] = 0.0


def test_a_missing_s3_object_says_what_to_run(s3: Stubber) -> None:
    s3.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)

    with pytest.raises(FileNotFoundError, match=f"s3://{BUCKET}/{artifacts.SALARY_CARD_KEY} not found"):
        data.salary_model_card()


def test_data_module_stays_light() -> None:
    # The pages import it on every rerun; it must not drag in Streamlit, PyTorch or XGBoost.
    code = "import sys, src.app.data; print(sorted(m for m in ('streamlit', 'torch', 'xgboost') if m in sys.modules))"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=True)

    assert result.stdout.strip() == "[]"
