"""Tests for the dbt CI fixture generator (src/dbt_project/ci/make_fixtures.py).

The generator's building blocks are tested with a fake cursor; the end-to-end
check is loading the generated file into a fresh database and running dbt build.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.dbt_project.ci import make_fixtures


class _FakeCursor:
    """Stands in for a psycopg2 cursor: returns preset rows, quotes values with repr()."""

    def __init__(self, rows: list[tuple], names: tuple[str, ...] = ()) -> None:
        self._rows = rows
        self.description = [SimpleNamespace(name=n) for n in names]

    def execute(self, query: str, params: object = None) -> None:
        self.executed = (query, params)

    def fetchall(self) -> list[tuple]:
        return self._rows

    def mogrify(self, template: str, row: tuple) -> bytes:
        return (template % tuple(repr(v) for v in row)).encode()


def test_create_table_sql_copies_catalog_column_types() -> None:
    cur = _FakeCursor([("job_id", "text"), ("posted_at", "timestamp with time zone")])

    sql = make_fixtures._create_table_sql(cur, "jobs_clean")

    assert sql == "create table raw.jobs_clean (\n    job_id text,\n    posted_at timestamp with time zone\n);"


def test_create_table_sql_fails_loudly_when_table_missing() -> None:
    with pytest.raises(RuntimeError, match="raw.jobs_clean not found"):
        make_fixtures._create_table_sql(_FakeCursor([]), "jobs_clean")


def test_insert_sql_writes_every_row() -> None:
    cur = _FakeCursor([("a", "Python"), ("b", "SQL")], names=("job_id", "skill"))

    sql, n = make_fixtures._insert_sql(cur, "job_skills", "select ...", ())

    assert n == 2
    assert sql == "insert into raw.job_skills (job_id, skill) values\n('a', 'Python'),\n('b', 'SQL');"
