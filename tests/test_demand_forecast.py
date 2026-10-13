"""Tests for src/ml/demand_forecast.py (gate, Prophet forecasts, backtest).

Synthetic weekly series with a known shape. Skipped where Prophet isn't installed
(the CI pytest job); runs in the `ml` job.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

pytest.importorskip("prophet")

from src.ml import demand_forecast as df  # noqa: E402
from src.ml.demand_forecast import Series  # noqa: E402

LOADED_AT = datetime(2026, 10, 13, tzinfo=timezone.utc)
FIRST_MONDAY = date(2026, 6, 1)


def _series(shares: list[float]) -> Series:
    weeks = tuple(FIRST_MONDAY + timedelta(weeks=i) for i in range(len(shares)))
    return Series("data engineer", "Spark", weeks, tuple(shares))


def _rising(n: int) -> list[float]:
    return [0.10 + 0.01 * i for i in range(n)]


def test_horizon_covers_90_days() -> None:
    assert df.FORECAST_WEEKS * 7 >= df.HORIZON_DAYS > (df.FORECAST_WEEKS - 1) * 7


def test_short_series_gets_insufficient_history_and_its_observed_share() -> None:
    series = _series(_rising(df.MIN_WEEKS_TO_FORECAST - 1))

    rows = df.forecast_rows(series, LOADED_AT)

    assert rows == [
        ("data engineer", "Spark", "insufficient_history", 11, series.weeks[-1], series.shares[-1],
         None, None, None, None, None, None, LOADED_AT)
    ]


def test_long_enough_series_gets_13_weekly_forecasts_continuing_the_trend() -> None:
    series = _series(_rising(df.MIN_WEEKS_TO_FORECAST))

    rows = df.forecast_rows(series, LOADED_AT)

    assert len(rows) == df.FORECAST_WEEKS
    assert [r[6] for r in rows] == [series.weeks[-1] + timedelta(weeks=k) for k in range(1, 14)]
    assert all(r[2] == "forecast" and 0 <= r[8] <= r[7] <= r[9] <= 1 for r in rows)
    assert rows[-1][7] > series.shares[-1]  # a rising trend keeps rising
    assert rows[0][10:12] == (None, None)  # < 16 weeks: no backtest yet


def test_forecasts_are_clipped_to_valid_shares() -> None:
    falling = [0.60 - 0.05 * i for i in range(df.MIN_WEEKS_TO_FORECAST)]  # → negative if extrapolated

    rows = df.forecast_rows(_series(falling), LOADED_AT)

    assert min(r[8] for r in rows) == 0.0
    assert all(0 <= r[8] <= r[7] <= r[9] <= 1 for r in rows)


def test_backtest_from_16_weeks_and_prophet_beats_naive_on_a_clean_trend() -> None:
    assert df.backtest(_series(_rising(df.MIN_WEEKS_TO_BACKTEST - 1))) is None

    prophet_mae, naive_mae = df.backtest(_series(_rising(df.MIN_WEEKS_TO_BACKTEST)))

    assert naive_mae == pytest.approx(0.01)  # "next week = this week" misses each 1-point step
    assert prophet_mae < naive_mae


def test_reruns_give_identical_forecasts() -> None:
    noisy = [0.2 + 0.01 * i + (0.03 if i % 3 else -0.03) for i in range(df.MIN_WEEKS_TO_FORECAST)]

    assert df.forecast_rows(_series(noisy), LOADED_AT) == df.forecast_rows(_series(noisy), LOADED_AT)


class _FakeCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, query: str) -> None:
        assert "mart_skill_demand" in query

    def fetchall(self) -> list[tuple]:
        return self._rows


class _FakeConfig:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def connect(self) -> object:
        rows = self._rows

        class _Conn:
            def cursor(self) -> _FakeCursor:
                return _FakeCursor(rows)

            def close(self) -> None:
                return None

        return _Conn()


def test_load_series_groups_points_per_role_and_skill() -> None:
    w1, w2 = date(2026, 9, 28), date(2026, 10, 5)
    rows = [
        ("data engineer", "SQL", w1, Decimal("0.5")),
        ("data engineer", "SQL", w2, Decimal("0.6")),
        ("data analyst", "Excel", w1, Decimal("0.4")),
    ]

    series = df.load_series(_FakeConfig(rows))  # type: ignore[arg-type]

    assert series == [
        Series("data analyst", "Excel", (w1,), (0.4,)),
        Series("data engineer", "SQL", (w1, w2), (0.5, 0.6)),
    ]
