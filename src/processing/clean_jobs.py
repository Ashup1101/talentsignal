"""Flatten, normalize and deduplicate raw JSearch postings into a Delta table.

Reads every s3://{S3_RAW_BUCKET}/jobs/raw/{role}/{location}/{date}.json file
and rebuilds s3://{S3_PROCESSED_BUCKET}/delta/jobs_clean with one row per
unique posting. The table is recomputed from the full raw zone on each run,
so reruns are idempotent and a fix to the cleaning logic applies to all
history.

Run locally:  python -m src.processing.clean_jobs
"""

from __future__ import annotations

import argparse
import logging
import sys

from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

from src.processing.spark_utils import bucket_uri, get_spark, on_databricks

logger = logging.getLogger(__name__)

RAW_JOBS_GLOB = "jobs/raw/*/*/*.json"
JOBS_CLEAN_PATH = "delta/jobs_clean"

# Only the fields we keep; Spark ignores the rest of each JSON object. An explicit
# schema keeps column types stable even when a batch has a field that is null
# everywhere (schema inference would then guess "string").
_RAW_JOB = T.StructType(
    [
        T.StructField("job_id", T.StringType()),
        T.StructField("job_title", T.StringType()),
        T.StructField("employer_name", T.StringType()),
        T.StructField("job_publisher", T.StringType()),
        T.StructField("job_employment_type", T.StringType()),
        T.StructField("job_is_remote", T.BooleanType()),
        T.StructField("job_city", T.StringType()),
        T.StructField("job_state", T.StringType()),
        T.StructField("job_country", T.StringType()),
        T.StructField("job_latitude", T.DoubleType()),
        T.StructField("job_longitude", T.DoubleType()),
        T.StructField("job_posted_at_datetime_utc", T.StringType()),
        T.StructField("job_min_salary", T.DoubleType()),
        T.StructField("job_max_salary", T.DoubleType()),
        T.StructField("job_salary_period", T.StringType()),
        T.StructField("job_description", T.StringType()),
        T.StructField("job_apply_link", T.StringType()),
    ]
)
RAW_ENVELOPE_SCHEMA = T.StructType(
    [
        T.StructField("role", T.StringType()),
        T.StructField("location", T.StringType()),
        T.StructField("fetched_at", T.StringType()),
        T.StructField("jobs", T.ArrayType(_RAW_JOB)),
    ]
)

# Multipliers that turn a pay rate into a yearly amount (2080 = 40 h x 52 weeks).
ANNUAL_FACTOR = {"HOUR": 2080, "DAY": 260, "WEEK": 52, "MONTH": 12, "YEAR": 1}
# Annual salaries outside this range are treated as data-entry errors and dropped.
MIN_ANNUAL_SALARY = 20_000
MAX_ANNUAL_SALARY = 1_000_000

US_STATE_CODES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL",
    "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR",
    "Pennsylvania": "PA", "Puerto Rico": "PR", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}  # fmt: skip


def _literal_map(mapping: dict) -> Column:
    return F.create_map(*[F.lit(x) for pair in mapping.items() for x in pair])


def _normalize_text(col: Column) -> Column:
    return F.lower(F.trim(F.regexp_replace(col, r"\s+", " ")))


def flatten(raw: DataFrame) -> DataFrame:
    """Explode raw envelopes into one row per posting with typed, renamed columns.

    Args:
        raw: Envelopes read with RAW_ENVELOPE_SCHEMA (one row per raw file).

    Returns:
        One row per posting, carrying the search role/location and fetch time.
    """
    job = F.col("job")
    return raw.select(
        F.col("role").alias("search_role"),
        F.col("location").alias("search_location"),
        F.to_timestamp("fetched_at").alias("fetched_at"),
        F.explode("jobs").alias("job"),
    ).select(
        job["job_id"].alias("job_id"),
        job["job_title"].alias("title"),
        job["employer_name"].alias("employer"),
        job["job_publisher"].alias("publisher"),
        job["job_employment_type"].alias("employment_type"),
        job["job_is_remote"].alias("is_remote"),
        job["job_city"].alias("city"),
        job["job_state"].alias("state"),
        job["job_country"].alias("country"),
        job["job_latitude"].alias("latitude"),
        job["job_longitude"].alias("longitude"),
        F.to_timestamp(job["job_posted_at_datetime_utc"]).alias("posted_at"),
        job["job_min_salary"].alias("salary_min_raw"),
        job["job_max_salary"].alias("salary_max_raw"),
        F.upper(job["job_salary_period"]).alias("salary_period_raw"),
        job["job_description"].alias("description"),
        job["job_apply_link"].alias("apply_link"),
        "search_role",
        "search_location",
        "fetched_at",
        F.to_date("fetched_at").alias("ingest_date"),
    )


def normalize(df: DataFrame) -> DataFrame:
    """Add normalized text, state codes, annualized salaries and a dedup key.

    Salaries are converted to yearly amounts. Values that can't be trusted are
    nulled and explained in salary_flag: "unknown_period", "out_of_range"
    (outside MIN/MAX_ANNUAL_SALARY) or "inverted_range" (min > max).

    Args:
        df: Output of flatten().

    Returns:
        df plus title_normalized, employer_normalized, state_code,
        salary_{min,max,mid}_annual, salary_flag and dedup_key.
    """
    factor = _literal_map(ANNUAL_FACTOR)[F.col("salary_period_raw")]
    min_annual = F.col("salary_min_raw") * factor
    max_annual = F.col("salary_max_raw") * factor

    def plausible(c: Column) -> Column:
        return c.isNull() | c.between(MIN_ANNUAL_SALARY, MAX_ANNUAL_SALARY)

    has_salary = F.col("salary_min_raw").isNotNull() | F.col("salary_max_raw").isNotNull()
    salary_flag = (
        F.when(has_salary & factor.isNull(), "unknown_period")
        .when(has_salary & ~(plausible(min_annual) & plausible(max_annual)), "out_of_range")
        .when(min_annual > max_annual, "inverted_range")
    )

    state_code = F.coalesce(
        _literal_map(US_STATE_CODES)[F.col("state")],
        F.when(F.length("state") == 2, F.upper("state")),
    )

    out = (
        df.withColumn("title_normalized", _normalize_text(F.col("title")))
        .withColumn("employer_normalized", _normalize_text(F.col("employer")))
        .withColumn("state_code", state_code)
        .withColumn("salary_flag", salary_flag)
        .withColumn("salary_min_annual", F.when(F.col("salary_flag").isNull(), F.round(min_annual)))
        .withColumn("salary_max_annual", F.when(F.col("salary_flag").isNull(), F.round(max_annual)))
    )
    return out.withColumn(
        "salary_mid_annual",
        F.coalesce(
            (F.col("salary_min_annual") + F.col("salary_max_annual")) / 2,
            F.col("salary_min_annual"),
            F.col("salary_max_annual"),
        ),
    ).withColumn(
        # Same job reposted (or listed on several boards) under different job_ids.
        "dedup_key",
        F.concat_ws(
            "|",
            "title_normalized",
            "employer_normalized",
            F.coalesce(_normalize_text(F.col("city")), F.lit("")),
        ),
    )


def dedupe_by_id(df: DataFrame) -> DataFrame:
    """Keep the most recently fetched copy of each job_id.

    Args:
        df: Postings that may repeat across daily raw files.

    Returns:
        One row per job_id.
    """
    latest_first = Window.partitionBy("job_id").orderBy(F.col("fetched_at").desc())
    return df.withColumn("_rank", F.row_number().over(latest_first)).filter("_rank = 1").drop("_rank")


def dedupe_by_content(df: DataFrame) -> DataFrame:
    """Keep the most complete posting among rows sharing a dedup_key.

    Preference order: has a salary, longer description, fetched more recently,
    then job_id so the choice is deterministic.

    Args:
        df: Output of normalize(), already unique per job_id.

    Returns:
        One row per dedup_key.
    """
    richest_first = Window.partitionBy("dedup_key").orderBy(
        F.col("salary_mid_annual").isNull().asc(),
        F.length("description").desc_nulls_last(),
        F.col("fetched_at").desc(),
        F.col("job_id").asc(),
    )
    return df.withColumn("_rank", F.row_number().over(richest_first)).filter("_rank = 1").drop("_rank")


def run(spark: SparkSession, raw_root: str, processed_root: str) -> int:
    """Rebuild the jobs_clean Delta table from every raw JSearch file.

    Args:
        spark: Active SparkSession.
        raw_root: Raw bucket URI, e.g. "s3a://talentsignal-raw-ash".
        processed_root: Processed bucket URI.

    Returns:
        Number of rows written.
    """
    raw = spark.read.schema(RAW_ENVELOPE_SCHEMA).option("multiLine", True).json(f"{raw_root}/{RAW_JOBS_GLOB}")
    postings = normalize(flatten(raw)).cache()
    unique_ids = dedupe_by_id(postings)
    clean = dedupe_by_content(unique_ids)

    n_raw, n_ids, n_clean = postings.count(), unique_ids.count(), clean.count()
    logger.info(
        "Postings: %d raw → %d after job_id dedup (-%d) → %d after content dedup (-%d)",
        n_raw, n_ids, n_raw - n_ids, n_clean, n_ids - n_clean,
    )  # fmt: skip
    if n_clean == 0:
        raise RuntimeError(f"No postings found under {raw_root}/{RAW_JOBS_GLOB}")

    out = f"{processed_root}/{JOBS_CLEAN_PATH}"
    clean.write.format("delta").mode("overwrite").option("overwriteSchema", "true").save(out)
    logger.info("Wrote %d rows to %s", n_clean, out)
    postings.unpersist()
    return n_clean


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments (defaults to sys.argv). --raw-root / --processed-root
            override the bucket URIs built from S3_RAW_BUCKET / S3_PROCESSED_BUCKET.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-root")
    parser.add_argument("--processed-root")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    spark = get_spark("clean_jobs")
    try:
        run(
            spark,
            args.raw_root or bucket_uri("S3_RAW_BUCKET"),
            args.processed_root or bucket_uri("S3_PROCESSED_BUCKET"),
        )
    finally:
        if not on_databricks():  # Databricks owns its session; stopping it breaks the job.
            spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
