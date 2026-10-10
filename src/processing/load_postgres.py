"""Copy the processed Delta tables into RDS PostgreSQL (schema raw) for dbt.

Reads delta/jobs_clean, delta/job_skills and delta/bls_occupations from
s3://{S3_PROCESSED_BUCKET} and replaces raw.jobs_clean, raw.job_skills and
raw.bls_occupations, adding a _loaded_at timestamp that dbt's source
freshness check reads.

Run locally:  python -m src.processing.load_postgres
"""

from __future__ import annotations

import argparse
import logging
import sys
from contextlib import closing
from datetime import datetime, timezone

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from src.ingestion.s3_utils import require_env
from src.processing.clean_bls import BLS_OCCUPATIONS_PATH
from src.processing.clean_jobs import JOB_SIGHTINGS_PATH, JOBS_CLEAN_PATH
from src.processing.extract_skills import JOB_SKILLS_PATH
from src.processing.postgres import PostgresConfig
from src.processing.spark_utils import bucket_uri, get_spark, on_databricks

logger = logging.getLogger(__name__)

RAW_SCHEMA = "raw"
# raw table name -> Delta path under the processed bucket
TABLES = {
    "jobs_clean": JOBS_CLEAN_PATH,
    "job_skills": JOB_SKILLS_PATH,
    "bls_occupations": BLS_OCCUPATIONS_PATH,
    "job_sightings": JOB_SIGHTINGS_PATH,
}
POSTGRES_JDBC_PACKAGE = "org.postgresql:postgresql:42.7.13"


def with_loaded_at(df: DataFrame, loaded_at: datetime) -> DataFrame:
    """Add a _loaded_at column so dbt can tell how fresh the raw tables are.

    Args:
        df: Table to load.
        loaded_at: Timezone-aware load time, shared by every table in one run.

    Returns:
        df with a _loaded_at timestamp column.
    """
    return df.withColumn("_loaded_at", F.lit(loaded_at).cast("timestamp"))


def _write_table(df: DataFrame, config: PostgresConfig, table: str) -> None:
    # truncate=true empties and refills an existing table instead of dropping it,
    # so dbt views built on top of raw.* survive reloads. If the columns change,
    # the insert fails loudly; drop the raw table once and rerun to recreate it.
    (
        df.write.format("jdbc")
        .option("url", config.jdbc_url)
        .option("dbtable", f"{RAW_SCHEMA}.{table}")
        .option("user", config.user)
        .option("password", config.password)
        .option("driver", "org.postgresql.Driver")
        .option("truncate", "true")
        .mode("overwrite")
        .save()
    )


def run(spark: SparkSession, processed_root: str, config: PostgresConfig) -> dict[str, int]:
    """Replace every raw.* table with the current Delta table and verify row counts.

    Args:
        spark: Active SparkSession with the PostgreSQL JDBC driver available.
        processed_root: Processed bucket URI, e.g. "s3a://talentsignal-processed-ash".
        config: Target database.

    Returns:
        Mapping of raw table name to rows loaded.

    Raises:
        RuntimeError: If a table's row count in PostgreSQL differs from Spark's.
    """
    # `with conn` commits (or rolls back) but does not close; closing() does.
    with closing(config.connect()) as conn, conn, conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {RAW_SCHEMA}")

    loaded_at = datetime.now(timezone.utc)
    expected: dict[str, int] = {}
    for table, path in TABLES.items():
        df = with_loaded_at(spark.read.format("delta").load(f"{processed_root}/{path}"), loaded_at).cache()
        expected[table] = df.count()
        _write_table(df, config, table)
        df.unpersist()
        logger.info("Loaded %d rows into %s.%s", expected[table], RAW_SCHEMA, table)

    with closing(config.connect()) as conn, conn.cursor() as cur:
        for table, n in expected.items():
            cur.execute(f"SELECT count(*) FROM {RAW_SCHEMA}.{table}")
            actual = cur.fetchone()[0]
            if actual != n:
                raise RuntimeError(f"{RAW_SCHEMA}.{table} has {actual} rows after load; expected {n}")
    logger.info("Verified row counts in PostgreSQL: %s", expected)
    return expected


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments (defaults to sys.argv). --processed-root overrides the
            URI built from S3_PROCESSED_BUCKET.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--processed-root")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config = PostgresConfig.from_env()
    spark = get_spark("load_postgres", extra_packages=[POSTGRES_JDBC_PACKAGE])
    try:
        run(spark, args.processed_root or bucket_uri("S3_PROCESSED_BUCKET"), config)
    finally:
        if not on_databricks():
            spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
