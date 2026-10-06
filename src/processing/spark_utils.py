"""SparkSession and storage-path helpers shared by the processing jobs.

The same job code runs in two places:
- locally (laptop), where we build a SparkSession with Delta Lake and the
  S3A connector, reading AWS credentials from .env via environment variables;
- on Databricks, where the runtime already provides a configured session.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pyspark.sql import SparkSession

from src.ingestion.s3_utils import require_env

load_dotenv()

logger = logging.getLogger(__name__)


def on_databricks() -> bool:
    """Report whether this process is running on a Databricks cluster or job.

    Returns:
        True when the Databricks runtime environment variable is present.
    """
    return "DATABRICKS_RUNTIME_VERSION" in os.environ


def _hadoop_version() -> str:
    # hadoop-aws must match the Hadoop version bundled inside pyspark exactly.
    import pyspark

    jars = Path(pyspark.__file__).parent / "jars"
    for jar in jars.glob("hadoop-client-api-*.jar"):
        return jar.stem.removeprefix("hadoop-client-api-")
    raise RuntimeError(f"No hadoop-client-api jar found in {jars}; is pyspark installed correctly?")


def get_spark(app_name: str, extra_packages: list[str] | None = None) -> SparkSession:
    """Return a SparkSession with Delta Lake and S3 access configured.

    Args:
        app_name: Name shown in the Spark UI (http://localhost:4040 while a local job runs).
        extra_packages: Additional Maven coordinates to fetch locally (e.g. a JDBC
            driver). Ignored on Databricks, whose runtime bundles common drivers.

    Returns:
        The Databricks-provided session on Databricks, otherwise a local session.

    Raises:
        ValueError: Locally, if AWS_REGION is unset.
    """
    if on_databricks():
        return SparkSession.builder.getOrCreate()

    from delta import configure_spark_with_delta_pip

    # Python UDFs run in worker processes; make them use this interpreter (and its packages).
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    builder = (
        SparkSession.builder.master("local[*]")
        .appName(app_name)
        .config("spark.driver.memory", "2g")
        .config("spark.sql.session.timeZone", "UTC")
        # The default of 200 shuffle partitions is tuned for clusters; a laptop wants a handful.
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        # Credentials come from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in the environment.
        .config("spark.hadoop.fs.s3a.endpoint.region", require_env("AWS_REGION"))
    )
    packages = [f"org.apache.hadoop:hadoop-aws:{_hadoop_version()}", *(extra_packages or [])]
    spark = configure_spark_with_delta_pip(builder, extra_packages=packages).getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark


def bucket_uri(env_var: str) -> str:
    """Build a Spark-readable URI for a bucket named in an environment variable.

    Args:
        env_var: Variable holding the bucket name, e.g. "S3_RAW_BUCKET".

    Returns:
        "s3://bucket" on Databricks, "s3a://bucket" locally (Hadoop's S3 connector).

    Raises:
        ValueError: If env_var is unset.
    """
    scheme = "s3" if on_databricks() else "s3a"
    return f"{scheme}://{require_env(env_var)}"
