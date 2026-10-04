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

logger = logging.getLogger(__name__)

JOB_SKILLS_PATH = "delta/job_skills"

# canonical name -> (category, aliases). Aliases match case-insensitively on word
# boundaries unless the skill is listed in CASE_SENSITIVE.
SKILLS: dict[str, tuple[str, tuple[str, ...]]] = {
    # Languages
    "Python": ("language", ("Python",)),
    "SQL": ("language", ("SQL",)),
    "Java": ("language", ("Java",)),
    "Scala": ("language", ("Scala",)),
    "R": ("language", ()),  # CUSTOM_PATTERNS
    "Go": ("language", ()),  # CUSTOM_PATTERNS
    "Rust": ("language", ("Rust",)),
    "C++": ("language", ("C++",)),
    "C#": ("language", ("C#",)),
    "JavaScript": ("language", ("JavaScript",)),
    "TypeScript": ("language", ("TypeScript",)),
    "Bash": ("language", ("Bash", "shell scripting")),
    "Kotlin": ("language", ("Kotlin",)),
    "Ruby": ("language", ("Ruby",)),
    "PHP": ("language", ("PHP",)),
    "MATLAB": ("language", ("MATLAB",)),
    "SAS": ("language", ("SAS",)),
    # Data engineering
    "Spark": ("data_engineering", ("Spark", "PySpark", "Spark SQL")),
    "Hadoop": ("data_engineering", ("Hadoop", "HDFS")),
    "Kafka": ("data_engineering", ("Kafka",)),
    "Flink": ("data_engineering", ("Flink",)),
    "Airflow": ("data_engineering", ("Airflow",)),
    "dbt": ("data_engineering", ("dbt",)),
    "Databricks": ("data_engineering", ("Databricks",)),
    "Snowflake": ("data_engineering", ("Snowflake",)),
    "BigQuery": ("data_engineering", ("BigQuery",)),
    "Redshift": ("data_engineering", ("Redshift",)),
    "Hive": ("data_engineering", ("Hive",)),
    "Presto/Trino": ("data_engineering", ("Presto", "Trino")),
    "Delta Lake": ("data_engineering", ("Delta Lake",)),
    "Iceberg": ("data_engineering", ("Apache Iceberg", "Iceberg")),
    "Apache Beam": ("data_engineering", ("Apache Beam",)),
    "NiFi": ("data_engineering", ("NiFi",)),
    "Informatica": ("data_engineering", ("Informatica",)),
    "Fivetran": ("data_engineering", ("Fivetran",)),
    "SSIS": ("data_engineering", ("SSIS",)),
    "Talend": ("data_engineering", ("Talend",)),
    "AWS Glue": ("data_engineering", ("AWS Glue", "Glue jobs", "Glue ETL")),
    "EMR": ("data_engineering", ("EMR",)),
    "Kinesis": ("data_engineering", ("Kinesis",)),
    "Azure Data Factory": ("data_engineering", ("Azure Data Factory", "ADF")),
    "Azure Synapse": ("data_engineering", ("Synapse",)),
    "ETL": ("data_engineering", ("ETL", "ELT")),
    "Data Modeling": ("data_engineering", ("data modeling", "data modelling", "dimensional modeling")),
    "Data Warehousing": ("data_engineering", ("data warehouse", "data warehousing", "data lakehouse")),
    # Databases
    "PostgreSQL": ("database", ("PostgreSQL", "Postgres")),
    "MySQL": ("database", ("MySQL",)),
    "SQL Server": ("database", ("SQL Server", "MSSQL", "T-SQL")),
    "Oracle": ("database", ("Oracle",)),
    "MongoDB": ("database", ("MongoDB", "Mongo")),
    "Cassandra": ("database", ("Cassandra",)),
    "DynamoDB": ("database", ("DynamoDB",)),
    "Redis": ("database", ("Redis",)),
    "Elasticsearch": ("database", ("Elasticsearch", "Elastic Search", "OpenSearch")),
    "Neo4j": ("database", ("Neo4j",)),
    "NoSQL": ("database", ("NoSQL",)),
    # Cloud
    "AWS": ("cloud", ("AWS", "Amazon Web Services")),
    "Azure": ("cloud", ("Azure",)),
    "GCP": ("cloud", ("GCP", "Google Cloud")),
    "S3": ("cloud", ("S3",)),
    "AWS Lambda": ("cloud", ("AWS Lambda", "Lambda functions")),
    "EC2": ("cloud", ("EC2",)),
    # DevOps
    "Docker": ("devops", ("Docker",)),
    "Kubernetes": ("devops", ("Kubernetes", "K8s", "EKS", "AKS", "GKE")),
    "Terraform": ("devops", ("Terraform",)),
    "Git": ("devops", ("Git",)),
    "GitHub Actions": ("devops", ("GitHub Actions",)),
    "Jenkins": ("devops", ("Jenkins",)),
    "CI/CD": ("devops", ("CI/CD", "CICD", "continuous integration")),
    "Linux": ("devops", ("Linux", "Unix")),
    # ML / AI
    "Machine Learning": ("ml_ai", ("machine learning", "ML")),
    "Deep Learning": ("ml_ai", ("deep learning", "neural network", "neural networks")),
    "PyTorch": ("ml_ai", ("PyTorch",)),
    "TensorFlow": ("ml_ai", ("TensorFlow",)),
    "Keras": ("ml_ai", ("Keras",)),
    "scikit-learn": ("ml_ai", ("scikit-learn", "sklearn", "scikit learn")),
    "XGBoost": ("ml_ai", ("XGBoost", "LightGBM", "gradient boosting")),
    "Pandas": ("ml_ai", ("Pandas",)),
    "NumPy": ("ml_ai", ("NumPy",)),
    "NLP": ("ml_ai", ("NLP", "natural language processing")),
    "Computer Vision": ("ml_ai", ("computer vision",)),
    "LLMs": ("ml_ai", ("LLM", "LLMs", "large language model", "large language models")),
    "Generative AI": ("ml_ai", ("generative AI", "GenAI", "Gen AI")),
    "RAG": ("ml_ai", ("RAG", "retrieval-augmented generation", "retrieval augmented generation")),
    "Hugging Face": ("ml_ai", ("Hugging Face", "HuggingFace")),
    "LangChain": ("ml_ai", ("LangChain",)),
    "MLflow": ("ml_ai", ("MLflow",)),
    "SageMaker": ("ml_ai", ("SageMaker",)),
    "Vertex AI": ("ml_ai", ("Vertex AI",)),
    "MLOps": ("ml_ai", ("MLOps",)),
    "Statistics": ("ml_ai", ("statistics", "statistical")),
    "A/B Testing": ("ml_ai", ("A/B test", "A/B tests", "A/B testing", "AB testing")),
    # Not plain "forecasting": in analyst postings that usually means business planning.
    "Time Series": ("ml_ai", ("time series", "time-series", "ARIMA", "forecasting models")),
    "Reinforcement Learning": ("ml_ai", ("reinforcement learning",)),
    # Analytics / BI
    "Tableau": ("analytics_bi", ("Tableau",)),
    "Power BI": ("analytics_bi", ("Power BI", "PowerBI")),
    "Looker": ("analytics_bi", ("Looker",)),
    "Excel": ("analytics_bi", ("Excel",)),
    "Qlik": ("analytics_bi", ("Qlik",)),
    "Superset": ("analytics_bi", ("Superset",)),
    "Alteryx": ("analytics_bi", ("Alteryx",)),
    # Web / backend
    "React": ("web", ("React", "React.js", "ReactJS")),
    "Node.js": ("web", ("Node.js", "NodeJS")),
    "Django": ("web", ("Django",)),
    "Flask": ("web", ("Flask",)),
    "FastAPI": ("web", ("FastAPI",)),
    "Spring": ("web", ("Spring Boot", "Spring Framework")),
    "GraphQL": ("web", ("GraphQL",)),
    "REST APIs": ("web", ("REST API", "REST APIs", "RESTful")),
    "Microservices": ("web", ("microservices", "microservice")),
}

# Also ordinary English words or short acronyms, so only exact capitalization counts
# ("React" vs "react quickly", "Excel" vs "excel at", "Snowflake" vs "snowflake schema").
CASE_SENSITIVE = {
    "AWS", "EMR", "Azure Data Factory", "Excel", "Hive", "Iceberg", "Oracle", "RAG", "React",
    "SAS", "S3", "Snowflake", "Spring", "Superset",
}

# Names too ambiguous for plain alias matching.
CUSTOM_PATTERNS = {
    # "Go": only as golang or inside a list ("Python, Go, Rust" / "Go/Java"), never "Go above and beyond".
    "Go": r"(?i:\bgolang\b)|(?<=[,/(] )Go\b|(?<=[,/(])Go\b|\bGo(?=\s*[,/)])",
    # "R": standalone capital R, not "R&D", "R-squared" or "R2".
    "R": r"(?<![A-Za-z0-9&/-])R(?![A-Za-z0-9&+#'-])",
}

# Alias boundaries: not glued to other letters/digits, and "+"/"#" so "C" never matches "C++"/"C#".
_LEFT = r"(?<![A-Za-z0-9+#])"
_RIGHT = r"(?![A-Za-z0-9+#])"


def skill_patterns() -> dict[str, re.Pattern[str]]:
    """Compile one regex per canonical skill from SKILLS, CASE_SENSITIVE and CUSTOM_PATTERNS.

    Returns:
        Mapping of canonical skill name to its compiled pattern.
    """
    patterns: dict[str, re.Pattern[str]] = {}
    for name, (_, aliases) in SKILLS.items():
        if name in CUSTOM_PATTERNS:
            patterns[name] = re.compile(CUSTOM_PATTERNS[name])
            continue
        alternation = "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True))
        flags = 0 if name in CASE_SENSITIVE else re.IGNORECASE
        patterns[name] = re.compile(f"{_LEFT}(?:{alternation}){_RIGHT}", flags)
    return patterns


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
