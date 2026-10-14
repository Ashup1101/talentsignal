"""Create or update app_reader, the app API's read-only PostgreSQL user (Phase 6).

app_reader can SELECT from the dbt schemas and ml.* — nothing else: no raw.*
tables, no writes (every session is read-only by default), 30 s statement limit.
Default privileges make tables that dbt and the ML steps re-create on every run
readable too, without re-running this.

Run once (and again after changing APP_SCHEMAS), connected as the RDS user that
owns those schemas (RDS_USER); app_reader's password comes from APP_DB_PASSWORD:

    python -m src.api.db_setup
"""

from __future__ import annotations

import logging
import sys
from contextlib import closing

from dotenv import load_dotenv
from psycopg2 import sql

from src.ingestion.s3_utils import require_env
from src.processing.postgres import PostgresConfig

logger = logging.getLogger(__name__)

APP_ROLE = "app_reader"
APP_SCHEMAS = ("analytics_staging", "analytics_intermediate", "analytics_marts", "ml")
STATEMENT_TIMEOUT = "30s"


def setup_statements(database: str, owner: str) -> list[tuple[sql.Composable, tuple]]:
    """The statements that create app_reader and grant it read-only access.

    Args:
        database: Database name (CONNECT is granted on it).
        owner: Role that creates the tables (dbt, the ML steps); default
            privileges apply to objects it creates later.

    Returns:
        (statement, parameters) pairs, in order. The password is the parameter of
        the ALTER ROLE statement, never part of the SQL text.
    """
    role = sql.Identifier(APP_ROLE)
    statements: list[tuple[sql.Composable, tuple]] = [
        (
            sql.SQL(
                "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = {name}) "
                "THEN CREATE ROLE {role}; END IF; END $$"
            ).format(name=sql.Literal(APP_ROLE), role=role),
            (),
        ),
        (
            # No NOSUPERUSER: on RDS only a superuser may name that attribute (roles are
            # created without it, and a non-superuser can't grant it anyway).
            sql.SQL("ALTER ROLE {} WITH LOGIN NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %s").format(role),
            ("<APP_DB_PASSWORD>",),
        ),
        (sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(role), ()),
        (sql.SQL("ALTER ROLE {} SET statement_timeout = {}").format(role, sql.Literal(STATEMENT_TIMEOUT)), ()),
        (sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), role), ()),
    ]
    for schema in APP_SCHEMAS:
        s = sql.Identifier(schema)
        statements += [
            (sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(s, role), ()),
            (sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(s, role), ()),
            (
                sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} GRANT SELECT ON TABLES TO {}").format(
                    sql.Identifier(owner), s, role
                ),
                (),
            ),
        ]
    return statements


def run(admin: PostgresConfig, password: str) -> None:
    """Apply setup_statements in one transaction.

    Args:
        admin: Connection as the schemas' owner (needs CREATEROLE).
        password: app_reader's password.
    """
    with closing(admin.connect()) as conn, conn, conn.cursor() as cur:
        for statement, params in setup_statements(admin.database, admin.user):
            cur.execute(statement, (password,) if params else None)
    logger.info("%s: read-only access to %s", APP_ROLE, ", ".join(APP_SCHEMAS))


def main() -> int:
    """Command-line entry point.

    Returns:
        Process exit code.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv()
    if require_env("APP_DB_USER") != APP_ROLE:
        raise ValueError(f"APP_DB_USER must be {APP_ROLE!r}")
    run(PostgresConfig.from_env(), require_env("APP_DB_PASSWORD"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
