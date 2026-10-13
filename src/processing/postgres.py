"""RDS PostgreSQL connection settings and a transactional table writer (no Spark needed).

Used by the Spark loader (load_postgres.py), the ML steps (src/ml/*.py), the dbt
CI fixture generator and, later, the app.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass

import psycopg2
from psycopg2.extras import execute_values

from src.ingestion.s3_utils import require_env

logger = logging.getLogger(__name__)


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


def replace_tables(
    config: PostgresConfig, schema: str, tables: dict[str, tuple[str, Sequence[str], list[tuple]]]
) -> None:
    """Replace every row of several tables in ONE transaction, adding _loaded_at.

    Readers see the previous complete tables until commit, and a failure rolls
    back every table. Tables are created if missing and truncated (not dropped),
    which keeps dependent dbt views.

    Args:
        config: Target database.
        schema: Schema to write into (created if missing).
        tables: name → (column DDL, column names in insert order, rows); each row
            ends with its _loaded_at value.

    Raises:
        RuntimeError: If a table's row count after the insert is off.
    """
    with closing(config.connect()) as conn, conn, conn.cursor() as cur:
        cur.execute(f"create schema if not exists {schema}")
        for table, (ddl, columns, rows) in tables.items():
            qualified = f"{schema}.{table}"
            cur.execute(
                f"create table if not exists {qualified} "
                f"({ddl}, _loaded_at timestamp with time zone not null)"
            )
            cur.execute(f"truncate {qualified}")
            execute_values(
                cur, f"insert into {qualified} ({', '.join(columns)}, _loaded_at) values %s", rows, page_size=500
            )
            cur.execute(f"select count(*) from {qualified}")
            written = cur.fetchone()[0]
            if written != len(rows):
                raise RuntimeError(f"{qualified} has {written} rows; expected {len(rows)}")
            logger.info("%s: %d rows", qualified, written)
