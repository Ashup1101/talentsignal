"""Extract skills from job postings with a dictionary-based pandas UDF.

Reads delta/jobs_clean and rebuilds delta/job_skills: one row per
(job_id, skill) with the skill's category. This is the deterministic
baseline; Phase 5 adds spaCy/BERTopic extraction to compare against it.

Run locally:  python -m src.processing.extract_skills
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from collections.abc import Callable

import pandas as pd
from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T

from src.processing.clean_jobs import JOBS_CLEAN_PATH
from src.processing.spark_utils import bucket_uri, get_spark, on_databricks
# The dictionary is shared with resumes (no Spark), so it lives in src/skills.
from src.skills.dictionary import SKILLS, skill_patterns

logger = logging.getLogger(__name__)

JOB_SKILLS_PATH = "delta/job_skills"


def make_skill_matcher(patterns: dict[str, re.Pattern[str]]) -> Callable[[Column], Column]:
    """Build a vectorized (pandas) UDF that returns the skills found in a text column.

    The UDF is created inside this function on purpose: Spark then ships it to
    worker processes by value, so workers don't need this repo on their Python path.

    Args:
        patterns: Output of skill_patterns().

    Returns:
        A function mapping a string Column to an array<string> Column of skill names.
    """
    items = list(patterns.items())

    @F.pandas_udf(T.ArrayType(T.StringType()))
    def match_skills(texts: pd.Series) -> pd.Series:
        return pd.Series(
            [[name for name, rx in items if rx.search(t)] if isinstance(t, str) else [] for t in texts]
        )

    return match_skills


def extract_skills(jobs: DataFrame) -> DataFrame:
    """Find dictionary skills in each posting's title and description.

    Args:
        jobs: Rows with job_id, title and description (e.g. delta/jobs_clean).

    Returns:
        One row per (job_id, skill) with columns job_id, skill, category.
    """
    spark = jobs.sparkSession
    catalog = spark.createDataFrame(
        [(name, category) for name, (category, _) in SKILLS.items()], "skill string, category string"
    )
    match_skills = make_skill_matcher(skill_patterns())
    text = F.concat_ws("\n", "title", "description")
    found = jobs.select("job_id", F.explode(match_skills(text)).alias("skill"))
    # The catalog is tiny, so broadcast it to every worker instead of shuffling the big side.
    return found.join(F.broadcast(catalog), "skill").select("job_id", "skill", "category")


def run(spark: SparkSession, processed_root: str) -> int:
    """Rebuild the job_skills Delta table from jobs_clean.

    Args:
        spark: Active SparkSession.
        processed_root: Processed bucket URI, e.g. "s3a://talentsignal-processed-ash".

    Returns:
        Number of (job_id, skill) rows written.
    """
    jobs = spark.read.format("delta").load(f"{processed_root}/{JOBS_CLEAN_PATH}")
    skills = extract_skills(jobs).cache()

    n_rows = skills.count()
    n_jobs, n_with_skills = jobs.count(), skills.select("job_id").distinct().count()
    logger.info("Extracted %d skill mentions; %d of %d postings have at least one", n_rows, n_with_skills, n_jobs)
    top = skills.groupBy("skill").count().orderBy(F.desc("count"), "skill").limit(15).collect()
    logger.info("Top skills: %s", ", ".join(f"{r['skill']} ({r['count']})" for r in top))

    out = f"{processed_root}/{JOB_SKILLS_PATH}"
    skills.write.format("delta").mode("overwrite").option("overwriteSchema", "true").save(out)
    logger.info("Wrote %d rows to %s", n_rows, out)
    skills.unpersist()
    return n_rows


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

    spark = get_spark("extract_skills")
    try:
        run(spark, args.processed_root or bucket_uri("S3_PROCESSED_BUCKET"))
    finally:
        if not on_databricks():
            spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
