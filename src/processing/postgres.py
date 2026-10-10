"""Connection settings for the RDS PostgreSQL database (no Spark needed).

Used by the Spark loader (load_postgres.py), the NLP step (src/ml/nlp_pipeline.py),
the dbt CI fixture generator and, later, the app.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg2

from src.ingestion.s3_utils import require_env


@dataclass(frozen=True)
class PostgresConfig:
    """Connection settings for the RDS PostgreSQL database."""

    host: str
    port: int
    database: str
    user: str
    password: str

    @classmethod
    def from_env(cls) -> PostgresConfig:
        """Build the config from RDS_* environment variables.

        Returns:
            A PostgresConfig.

        Raises:
            ValueError: If any RDS_* variable is unset.
        """
        return cls(
            host=require_env("RDS_HOST"),
            port=int(require_env("RDS_PORT")),
            database=require_env("RDS_DB"),
            user=require_env("RDS_USER"),
            password=require_env("RDS_PASSWORD"),
        )

    @property
    def jdbc_url(self) -> str:
        """JDBC URL with TLS required and batched inserts enabled (no credentials in it)."""
        return (
            f"jdbc:postgresql://{self.host}:{self.port}/{self.database}"
            "?sslmode=require&reWriteBatchedInserts=true"
        )

    def connect(self) -> psycopg2.extensions.connection:
        """Open a TLS-encrypted psycopg2 connection.

        Returns:
            An open connection; the caller closes it.
        """
        return psycopg2.connect(
            host=self.host,
            port=self.port,
            dbname=self.database,
            user=self.user,
            password=self.password,
            sslmode="require",
            connect_timeout=10,
        )
