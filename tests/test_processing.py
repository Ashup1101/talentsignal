"""Tests for src.processing, run on a small local SparkSession (no S3, no Delta)."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from src.processing import clean_bls, clean_jobs, extract_skills, load_postgres
from src.skills.dictionary import find_skills


@pytest.fixture(scope="session")
def spark() -> Iterator[SparkSession]:
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    session = (
        SparkSession.builder.master("local[1]")
        .appName("talentsignal-tests")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "1")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    yield session
    session.stop()


def _job(job_id: str, **fields: object) -> dict:
    base = {
        "job_id": job_id,
        "job_title": "Data Engineer",
        "employer_name": "Acme",
        "job_city": "Austin",
        "job_state": "Texas",
        "job_posted_at_datetime_utc": "2026-10-01T00:00:00.000Z",
        "job_description": "Build pipelines.",
    }
    return {**base, **fields}


def _read_raw(spark: SparkSession, tmp_path: Path, envelopes: list[dict]) -> DataFrame:
    """Write envelopes as raw files shaped like the S3 raw zone and read them back."""
    for i, envelope in enumerate(envelopes):
        (tmp_path / f"{i}.json").write_text(json.dumps(envelope))
    return spark.read.schema(clean_jobs.RAW_ENVELOPE_SCHEMA).option("multiLine", True).json(str(tmp_path))


def _envelope(jobs: list[dict], fetched_at: str = "2026-10-03T15:27:42+00:00") -> dict:
    return {"role": "data engineer", "location": "Austin, TX", "fetched_at": fetched_at, "jobs": jobs}


def _postings(spark: SparkSession, tmp_path: Path, envelopes: list[dict]) -> DataFrame:
    return clean_jobs.normalize(clean_jobs.flatten(_read_raw(spark, tmp_path, envelopes)))


# --- clean_jobs ---------------------------------------------------------------


def test_flatten_explodes_envelopes_and_parses_timestamps(spark: SparkSession, tmp_path: Path) -> None:
    flat = clean_jobs.flatten(_read_raw(spark, tmp_path, [_envelope([_job("a"), _job("b")])]))
    # Format inside Spark (session time zone = UTC); collect() would convert
    # timestamps to the machine's local time zone.
    rows = flat.select(
        "job_id",
        "search_role",
        "search_location",
        F.date_format("posted_at", "yyyy-MM-dd HH:mm:ss").alias("posted_at"),
        F.date_format("fetched_at", "yyyy-MM-dd HH:mm:ss").alias("fetched_at"),
        F.col("ingest_date").cast("string").alias("ingest_date"),
    ).collect()

    assert sorted(r.job_id for r in rows) == ["a", "b"]
    row = rows[0]
    assert (row.search_role, row.search_location) == ("data engineer", "Austin, TX")
    assert row.posted_at == "2026-10-01 00:00:00"
    assert row.fetched_at == "2026-10-03 15:27:42"
    assert row.ingest_date == "2026-10-03"


def test_normalize_annualizes_and_flags_salaries(spark: SparkSession, tmp_path: Path) -> None:
    jobs = [
        _job("hourly", job_min_salary=50, job_max_salary=60, job_salary_period="HOUR"),
        _job("monthly", job_min_salary=6000, job_max_salary=8000, job_salary_period="MONTH"),
        _job("yearly", job_min_salary=100000, job_max_salary=150000, job_salary_period="YEAR"),
        _job("min_only", job_min_salary=90000, job_salary_period="YEAR"),
        _job("tiny", job_min_salary=500, job_max_salary=600, job_salary_period="YEAR"),
        _job("odd_period", job_min_salary=100, job_max_salary=200, job_salary_period="FORTNIGHT"),
        _job("inverted", job_min_salary=150000, job_max_salary=100000, job_salary_period="YEAR"),
        _job("none"),
    ]
    rows = {r.job_id: r for r in _postings(spark, tmp_path, [_envelope(jobs)]).collect()}

    def salary(job_id: str) -> tuple:
        r = rows[job_id]
        return (r.salary_min_annual, r.salary_max_annual, r.salary_mid_annual, r.salary_flag)

    assert salary("hourly") == (104000.0, 124800.0, 114400.0, None)
    assert salary("monthly") == (72000.0, 96000.0, 84000.0, None)
    assert salary("yearly") == (100000.0, 150000.0, 125000.0, None)
    assert salary("min_only") == (90000.0, None, 90000.0, None)
    assert salary("tiny") == (None, None, None, "out_of_range")
    assert salary("odd_period") == (None, None, None, "unknown_period")
    assert salary("inverted") == (None, None, None, "inverted_range")
    assert salary("none") == (None, None, None, None)


def test_normalize_maps_states_and_builds_dedup_key(spark: SparkSession, tmp_path: Path) -> None:
    jobs = [
        _job("full_name", job_state="Texas"),
        _job("code", job_state="ny"),
        _job("missing", job_state=None, job_city=None),
        _job("foreign", job_state="Ontario"),
        _job("messy", job_title="  Senior   DATA Engineer ", employer_name="ACME Corp", job_city="Austin"),
    ]
    rows = {r.job_id: r for r in _postings(spark, tmp_path, [_envelope(jobs)]).collect()}

    assert rows["full_name"].state_code == "TX"
    assert rows["code"].state_code == "NY"
    assert rows["missing"].state_code is None
    assert rows["foreign"].state_code is None
    assert rows["messy"].dedup_key == "senior data engineer|acme corp|austin"
    assert rows["missing"].dedup_key == "data engineer|acme|"


def test_dedupe_by_id_keeps_latest_fetch(spark: SparkSession, tmp_path: Path) -> None:
    envelopes = [
        _envelope([_job("a", job_description="old")], fetched_at="2026-10-01T10:00:00+00:00"),
        _envelope([_job("a", job_description="new")], fetched_at="2026-10-02T10:00:00+00:00"),
    ]
    rows = clean_jobs.dedupe_by_id(_postings(spark, tmp_path, envelopes)).collect()

    assert [(r.job_id, r.description) for r in rows] == [("a", "new")]


def test_dedupe_by_content_prefers_salary_then_longer_description(spark: SparkSession, tmp_path: Path) -> None:
    jobs = [
        # Same title/employer/city under three ids: the one with a salary wins.
        _job("long_no_salary", job_description="x" * 500),
        _job("short_with_salary", job_description="x", job_min_salary=100000, job_salary_period="YEAR"),
        _job("short_no_salary", job_description="x"),
        # Same title/employer, different city: a different job, kept.
        _job("other_city", job_city="Chicago", job_state="Illinois"),
        # Two salary-less copies of another job: the longer description wins.
        _job("brief", job_title="Analyst", job_description="short"),
        _job("detailed", job_title="Analyst", job_description="much longer description"),
    ]
    postings = clean_jobs.dedupe_by_id(_postings(spark, tmp_path, [_envelope(jobs)]))
    kept = sorted(r.job_id for r in clean_jobs.dedupe_by_content(postings).collect())

    assert kept == ["detailed", "other_city", "short_with_salary"]


def test_sightings_keep_every_collection_that_jobs_clean_merges(spark: SparkSession, tmp_path: Path) -> None:
    # The same job collected twice: JSearch issued a new job_id, the content is identical.
    envelopes = [
        _envelope([_job("oct3-id")], fetched_at="2026-10-03T15:00:00+00:00"),
        _envelope([_job("oct7-id")], fetched_at="2026-10-07T21:00:00+00:00"),
    ]
    postings = _postings(spark, tmp_path, envelopes)

    seen = clean_jobs.sightings(postings).collect()
    kept = clean_jobs.dedupe_by_content(clean_jobs.dedupe_by_id(postings)).collect()

    assert sorted(r.job_id for r in seen) == ["oct3-id", "oct7-id"]
    assert len({r.dedup_key for r in seen}) == 1  # both sightings point to one posting
    assert [r.job_id for r in kept] == ["oct7-id"]  # jobs_clean keeps only the latest copy


# --- extract_skills -----------------------------------------------------------


# Pattern behaviour is tested Spark-free in tests/test_skills.py.


def test_extract_skills_returns_job_skill_category_rows(spark: SparkSession) -> None:
    jobs = spark.createDataFrame(
        [
            ("j1", "Data Engineer", "Spark and Kafka pipelines on AWS."),
            ("j2", "Data Analyst", "SQL, Tableau and Excel."),
            ("j3", "Recruiter", "Talk to people."),
            ("j4", None, None),
        ],
        "job_id string, title string, description string",
    )
    rows = {tuple(r) for r in extract_skills.extract_skills(jobs).collect()}

    assert rows == {
        ("j1", "Spark", "data_engineering"),
        ("j1", "Kafka", "data_engineering"),
        ("j1", "AWS", "cloud"),
        ("j2", "SQL", "language"),
        ("j2", "Tableau", "analytics_bi"),
        ("j2", "Excel", "analytics_bi"),
    }


def test_spark_udf_matches_find_skills_exactly(spark: SparkSession) -> None:
    # The UDF keeps its own one-line matching loop (so Spark workers need no repo
    # on their path); this guards that it agrees with the shared find_skills().
    texts = [
        "Experience with Python, Go, and Rust",
        "We go above and beyond. Go-to-market strategy.",
        "Statistical modeling in Python or R. Lead R&D initiatives.",
        "C++ and C# required; JavaScript and TypeScript a plus",
        "You will excel at storytelling. Star and snowflake schema design.",
        "Advanced Excel, Power BI, Snowflake, dbt and Airflow on AWS (S3, EMR)",
        "Talk to people.",
        "",
    ]
    jobs = spark.createDataFrame(
        [(f"j{i}", None, text) for i, text in enumerate(texts)],
        "job_id string, title string, description string",
    )
    from_spark: dict[str, set[str]] = {f"j{i}": set() for i in range(len(texts))}
    for row in extract_skills.extract_skills(jobs).collect():
        from_spark[row.job_id].add(row.skill)

    assert from_spark == {f"j{i}": set(find_skills(text)) for i, text in enumerate(texts)}


# --- clean_bls ----------------------------------------------------------------


def test_latest_occupations_keeps_newest_snapshot(spark: SparkSession, tmp_path: Path) -> None:
    def snapshot(fetched_at: str, wage: int) -> dict:
        record = {
            "occupation_code": "15-2051",
            "title": "Data Scientists",
            "total_employment": 262440,
            "median_wage": wage,
            "reference_year": 2025,
        }
        return {"fetched_at": fetched_at, "records": [record]}

    (tmp_path / "old.json").write_text(json.dumps(snapshot("2026-09-01T00:00:00+00:00", 1)))
    (tmp_path / "new.json").write_text(json.dumps(snapshot("2026-10-03T00:00:00+00:00", 120230)))
    raw = spark.read.schema(clean_bls.RAW_BLS_SCHEMA).option("multiLine", True).json(str(tmp_path))

    rows = clean_bls.latest_occupations(raw).collect()

    assert [(r.occupation_code, r.median_wage) for r in rows] == [("15-2051", 120230)]


# --- load_postgres ------------------------------------------------------------


def test_with_loaded_at_stamps_the_whole_batch_once(spark: SparkSession) -> None:
    df = spark.createDataFrame([("a",), ("b",)], "job_id string")
    loaded = load_postgres.with_loaded_at(df, datetime(2026, 10, 5, 12, 30, tzinfo=timezone.utc))

    stamps = loaded.select(F.date_format("_loaded_at", "yyyy-MM-dd HH:mm:ss").alias("t")).distinct().collect()

    assert [r.t for r in stamps] == ["2026-10-05 12:30:00"]


def test_postgres_config_jdbc_url_requires_tls_and_omits_password(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {"RDS_HOST": "db.example.com", "RDS_PORT": "5432", "RDS_DB": "talentsignal", "RDS_USER": "loader", "RDS_PASSWORD": "s3cret-pw"}
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    config = load_postgres.PostgresConfig.from_env()

    assert config.jdbc_url == "jdbc:postgresql://db.example.com:5432/talentsignal?sslmode=require&reWriteBatchedInserts=true"
    assert "s3cret-pw" not in config.jdbc_url


def test_postgres_config_requires_every_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RDS_HOST", raising=False)
    with pytest.raises(ValueError, match="RDS_HOST is not set"):
        load_postgres.PostgresConfig.from_env()
