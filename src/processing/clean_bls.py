"""Flatten raw BLS OEWS snapshots into a Delta table of occupations.

Reads every s3://{S3_RAW_BUCKET}/bls/raw/{date}.json snapshot and rebuilds
delta/bls_occupations with the most recently fetched record per occupation.

Run locally:  python -m src.processing.clean_bls
"""

from __future__ import annotations

import argparse
import logging
import sys

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

from src.processing.spark_utils import bucket_uri, get_spark, on_databricks

logger = logging.getLogger(__name__)

RAW_BLS_GLOB = "bls/raw/*.json"
BLS_OCCUPATIONS_PATH = "delta/bls_occupations"

RAW_BLS_SCHEMA = T.StructType(
    [
        T.StructField("fetched_at", T.StringType()),
        T.StructField(
            "records",
            T.ArrayType(
                T.StructType(
                    [
                        T.StructField("occupation_code", T.StringType()),
                        T.StructField("title", T.StringType()),
                        T.StructField("total_employment", T.LongType()),
                        T.StructField("median_wage", T.LongType()),
                        T.StructField("reference_year", T.IntegerType()),
                    ]
                )
            ),
        ),
    ]
)


def latest_occupations(raw: DataFrame) -> DataFrame:
    """Explode BLS snapshots and keep the most recently fetched row per occupation.

    Args:
        raw: Snapshots read with RAW_BLS_SCHEMA (one row per raw file).

    Returns:
        One row per occupation_code with title, total_employment, median_wage,
        reference_year and fetched_at.
    """
    rows = raw.select(F.to_timestamp("fetched_at").alias("fetched_at"), F.explode("records").alias("r")).select(
        "r.occupation_code", "r.title", "r.total_employment", "r.median_wage", "r.reference_year", "fetched_at"
    )
    latest_first = Window.partitionBy("occupation_code").orderBy(F.col("fetched_at").desc())
    return rows.withColumn("_rank", F.row_number().over(latest_first)).filter("_rank = 1").drop("_rank")


def run(spark: SparkSession, raw_root: str, processed_root: str) -> int:
    """Rebuild the bls_occupations Delta table.

    Args:
        spark: Active SparkSession.
        raw_root: Raw bucket URI.
        processed_root: Processed bucket URI.

    Returns:
        Number of occupations written.
    """
    raw = spark.read.schema(RAW_BLS_SCHEMA).option("multiLine", True).json(f"{raw_root}/{RAW_BLS_GLOB}")
    occupations = latest_occupations(raw).cache()
    n = occupations.count()
    if n == 0:
        raise RuntimeError(f"No BLS records found under {raw_root}/{RAW_BLS_GLOB}")

    out = f"{processed_root}/{BLS_OCCUPATIONS_PATH}"
    occupations.write.format("delta").mode("overwrite").option("overwriteSchema", "true").save(out)
    logger.info("Wrote %d occupations to %s", n, out)
    occupations.unpersist()
    return n


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments (defaults to sys.argv). --raw-root / --processed-root
            override the bucket URIs built from the environment.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-root")
    parser.add_argument("--processed-root")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    spark = get_spark("clean_bls")
    try:
        run(
            spark,
            args.raw_root or bucket_uri("S3_RAW_BUCKET"),
            args.processed_root or bucket_uri("S3_PROCESSED_BUCKET"),
        )
    finally:
        if not on_databricks():
            spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
