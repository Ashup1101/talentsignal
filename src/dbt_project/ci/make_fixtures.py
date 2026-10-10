"""Write raw_fixtures.sql: a small, real sample of the raw.* and ml.* tables for dbt CI.

The dbt CI job loads that file into a throwaway PostgreSQL container so
`dbt build` runs on every pull request without RDS credentials. Re-run this
(read-only against RDS) whenever load_postgres.py or nlp_pipeline.py changes
the source columns:

    python -m src.dbt_project.ci.make_fixtures
"""

from __future__ import annotations

import csv
import logging
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from src.processing.load_postgres import RAW_SCHEMA, TABLES
from src.processing.postgres import PostgresConfig

logger = logging.getLogger(__name__)

HERE = Path(__file__).parent
OUTPUT = HERE / "raw_fixtures.sql"
SEED = HERE.parent / "seeds" / "role_soc_mapping.csv"

# Postings per search role, by kind, so every model path gets exercised.
SAMPLE_PER_ROLE = {"with_salary": 4, "no_location": 2, "other": 4}
DESCRIPTION_CHARS = 200
# Written by src/ml/nlp_pipeline.py (not imported here: it needs spaCy, which the
# CI pytest job doesn't install). Copied as computed from the full descriptions.
ML_SCHEMA = "ml"
ML_TABLES = ("posting_nlp",)

_SAMPLE_SQL = f"""
    with labelled as (
        select
            job_id,
            search_role,
            case
                when salary_mid_annual is not null then 'with_salary'
                when city is null and state is null then 'no_location'
                else 'other'
            end as kind
        from {RAW_SCHEMA}.jobs_clean
    ),
    ranked as (
        select *, row_number() over (partition by search_role, kind order by md5(job_id)) as rank
        from labelled
    )
    select job_id, search_role, kind
    from ranked
    where (kind = 'with_salary' and rank <= %(with_salary)s)
       or (kind = 'no_location' and rank <= %(no_location)s)
       or (kind = 'other' and rank <= %(other)s)
"""


def _create_table_sql(cur, schema: str, table: str) -> str:
    cur.execute(
        """
        select column_name, data_type
        from information_schema.columns
        where table_schema = %s and table_name = %s
        order by ordinal_position
        """,
        (schema, table),
    )
    columns = cur.fetchall()
    if not columns:
        raise RuntimeError(f"{schema}.{table} not found; run the step that writes it first")
    body = ",\n".join(f"    {name} {dtype}" for name, dtype in columns)
    return f"create table {schema}.{table} (\n{body}\n);"


def _insert_sql(cur, schema: str, table: str, query: str, params: tuple) -> tuple[str, int]:
    cur.execute(query, params)
    names = [d.name for d in cur.description]
    rows = cur.fetchall()
    if not rows:
        raise RuntimeError(f"Fixture query for {schema}.{table} returned no rows")
    placeholders = "(" + ", ".join(["%s"] * len(names)) + ")"
    values = ",\n".join(cur.mogrify(placeholders, row).decode() for row in rows)
    return f"insert into {schema}.{table} ({', '.join(names)}) values\n{values};", len(rows)


def build_fixture_sql(config: PostgresConfig) -> str:
    """Query RDS (read-only) and return the full fixture SQL script.

    Args:
        config: Connection to the database holding the real raw.* tables.

    Returns:
        SQL that creates raw.* and ml.* and inserts the sample. It never drops
        anything, so running it against a database that already has them just fails.
    """
    soc_codes = sorted({row["soc_code"] for row in csv.DictReader(SEED.open()) if row["soc_code"]})
    with closing(config.connect()) as conn, conn.cursor() as cur:
        cur.execute(_SAMPLE_SQL, SAMPLE_PER_ROLE)
        sample = cur.fetchall()
        job_ids = tuple(job_id for job_id, _, _ in sample)
        kinds: dict[tuple[str, str], int] = {}
        for _, role, kind in sample:
            kinds[(role, kind)] = kinds.get((role, kind), 0) + 1
        for (role, kind), n in sorted(kinds.items()):
            logger.info("  %-26s %-12s %d", role, kind, n)

        cur.execute(f"select column_name from information_schema.columns "
                    f"where table_schema = %s and table_name = 'jobs_clean' order by ordinal_position", (RAW_SCHEMA,))
        job_cols = ", ".join(
            f"left(description, {DESCRIPTION_CHARS}) as description" if c == "description" else c
            for (c,) in cur.fetchall()
        )
        queries = {
            "jobs_clean": (f"select {job_cols} from {RAW_SCHEMA}.jobs_clean where job_id in %s order by job_id", (job_ids,)),
            "job_skills": (f"select * from {RAW_SCHEMA}.job_skills where job_id in %s order by job_id, skill", (job_ids,)),
            "bls_occupations": (
                f"select * from {RAW_SCHEMA}.bls_occupations where occupation_code in %s order by occupation_code",
                (tuple(soc_codes),),
            ),
            # Every sighting of the sampled postings, matched by content key so earlier
            # copies (different job_id, same posting) are included too.
            "job_sightings": (
                f"select * from {RAW_SCHEMA}.job_sightings where dedup_key in "
                f"(select dedup_key from {RAW_SCHEMA}.jobs_clean where job_id in %s) order by dedup_key, fetched_at",
                (job_ids,),
            ),
            "posting_nlp": (f"select * from {ML_SCHEMA}.posting_nlp where job_id in %s order by job_id", (job_ids,)),
        }

        parts = [
            "-- Generated by src/dbt_project/ci/make_fixtures.py — do not edit by hand.",
            f"-- {datetime.now(timezone.utc):%Y-%m-%d}: real sample of raw.* and ml.* ({len(job_ids)} postings,"
            f" descriptions cut to {DESCRIPTION_CHARS} chars) for the dbt CI job.",
            "-- Never drops anything: against a database that already has these tables, it",
            "-- stops at the first CREATE TABLE instead of touching real data.",
            "",
            f"create schema if not exists {RAW_SCHEMA};",
            f"create schema if not exists {ML_SCHEMA};",
        ]
        for schema, table in [(RAW_SCHEMA, t) for t in TABLES] + [(ML_SCHEMA, t) for t in ML_TABLES]:
            insert, n = _insert_sql(cur, schema, table, *queries[table])
            parts += ["", _create_table_sql(cur, schema, table), insert]
            logger.info("%s.%s: %d rows", schema, table, n)
    return "\n".join(parts) + "\n"


def main() -> int:
    """Regenerate raw_fixtures.sql from the RDS raw and ml tables.

    Returns:
        Process exit code.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sql = build_fixture_sql(PostgresConfig.from_env())
    OUTPUT.write_text(sql)
    logger.info("Wrote %s (%.0f KB)", OUTPUT, OUTPUT.stat().st_size / 1024)
    return 0


if __name__ == "__main__":
    sys.exit(main())
