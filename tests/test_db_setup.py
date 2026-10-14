"""Tests for src/app/db_setup.py (the app's read-only database user), with a fake connection."""

from __future__ import annotations

from types import SimpleNamespace

from src.app import db_setup


class _RecordingCursor:
    def __init__(self, executed: list[tuple[object, object]]) -> None:
        self._executed = executed

    def __enter__(self) -> _RecordingCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, statement: object, params: object = None) -> None:
        self._executed.append((statement, params))


class _FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[object, object]] = []

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def cursor(self) -> _RecordingCursor:
        return _RecordingCursor(self.executed)

    def close(self) -> None:
        return None


def test_statements_grant_select_on_each_schema_and_future_tables() -> None:
    statements = [repr(s) for s, _ in db_setup.setup_statements("talentsignal", "admin")]
    text = "\n".join(statements)

    assert len(statements) == 5 + 3 * len(db_setup.APP_SCHEMAS)
    for schema in db_setup.APP_SCHEMAS:
        assert f"Identifier('{schema}')" in text
    assert text.count("ALTER DEFAULT PRIVILEGES FOR ROLE ") == len(db_setup.APP_SCHEMAS)
    assert "Identifier('admin')" in text  # future tables created by the owner become readable
    assert "default_transaction_read_only = on" in text
    assert "INSERT" not in text and "UPDATE" not in text and "raw" not in text


def test_password_is_a_parameter_never_part_of_the_sql() -> None:
    connection = _FakeConnection()
    admin = SimpleNamespace(database="talentsignal", user="admin", connect=lambda: connection)

    db_setup.run(admin, "s3cret-Pa55")  # type: ignore[arg-type]

    with_params = [(s, p) for s, p in connection.executed if p]
    assert len(with_params) == 1
    statement, params = with_params[0]
    assert params == ("s3cret-Pa55",)
    assert "s3cret" not in repr(statement) and "PASSWORD %s" in repr(statement)
    assert all("s3cret" not in repr(s) for s, _ in connection.executed)
