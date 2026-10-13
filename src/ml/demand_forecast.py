"""Skill-demand forecasting with Prophet (Phase 5.3).

Series: per search role × skill, the share of that role's collected postings in
each collection week that mention the skill (analytics_marts.mart_skill_demand;
weeks the role wasn't sampled are gaps, not zeros).

- Gate: forecast only series with at least MIN_WEEKS_TO_FORECAST weekly points;
  the rest get status 'insufficient_history' plus their latest observed share.
- Prophet: linear trend, no seasonality (weeks of data can't reveal a yearly
  cycle), wide 95% intervals, FORECAST_WEEKS weekly steps (≥ the 90-day horizon).
  Shares are clipped to [0, 1].
- Backtest once a series has MIN_WEEKS_TO_BACKTEST points: one-step-ahead over
  its last BACKTEST_STEPS weeks, Prophet vs "next week = this week".

Output: ml.skill_demand_forecast in RDS (a dbt source), rebuilt each run.

Run locally:  python -m src.ml.demand_forecast
"""

from __future__ import annotations

import logging
import sys
from collections import defaultdict
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from prophet import Prophet

from src.processing.postgres import PostgresConfig, replace_tables

logger = logging.getLogger(__name__)

MIN_WEEKS_TO_FORECAST = 12
MIN_WEEKS_TO_BACKTEST = 16
BACKTEST_STEPS = 4  # each backtest fit still has ≥ MIN_WEEKS_TO_FORECAST points
HORIZON_DAYS = 90
FORECAST_WEEKS = -(-HORIZON_DAYS // 7)  # 13 weekly steps = 91 days, covering the horizon
INTERVAL_WIDTH = 0.95
RANDOM_SEED = 42  # Prophet samples its intervals; a fixed seed makes reruns identical
STATUS_FORECAST = "forecast"
STATUS_INSUFFICIENT = "insufficient_history"

ML_SCHEMA = "ml"
TABLE = "skill_demand_forecast"
_DDL = """search_role text not null,
        skill_name text not null,
        status text not null,
        n_weeks integer not null,
        last_observed_week date not null,
        last_observed_share double precision not null,
        forecast_week date,
        share_forecast double precision,
        share_lower double precision,
        share_upper double precision,
        backtest_mae_prophet double precision,
        backtest_mae_naive double precision"""
_COLUMNS = (
    "search_role", "skill_name", "status", "n_weeks", "last_observed_week", "last_observed_share",
    "forecast_week", "share_forecast", "share_lower", "share_upper", "backtest_mae_prophet", "backtest_mae_naive",
)


@dataclass(frozen=True)
class Series:
    """One role × skill demand series, oldest week first."""

    role: str
    skill: str
    weeks: tuple[date, ...]
    shares: tuple[float, ...]


def load_series(config: PostgresConfig) -> list[Series]:
    """Read every role × skill series from mart_skill_demand.

    Args:
        config: Database with the dbt marts.

    Returns:
        One Series per role × skill, sorted by role then skill.

    Raises:
        RuntimeError: If the mart is empty.
    """
    with closing(config.connect()) as conn, conn.cursor() as cur:
        cur.execute(
            "select search_role, skill_name, collection_week, share_of_role_postings"
            " from analytics_marts.mart_skill_demand order by 1, 2, 3"
        )
        rows = cur.fetchall()
    if not rows:
        raise RuntimeError("analytics_marts.mart_skill_demand is empty; run dbt build")
    points: dict[tuple[str, str], list[tuple[date, float]]] = defaultdict(list)
    for role, skill, week, share in rows:
        points[(role, skill)].append((week, float(share)))
    return [
        Series(role, skill, tuple(w for w, _ in pts), tuple(s for _, s in pts))
        for (role, skill), pts in sorted(points.items())
    ]


def _prophet_forecast(weeks: Sequence[date], shares: Sequence[float], targets: Sequence[date]) -> pd.DataFrame:
    history = pd.DataFrame({"ds": pd.to_datetime(list(weeks)), "y": list(shares)})
    model = Prophet(
        growth="linear",
        yearly_seasonality=False,
        weekly_seasonality=False,
        daily_seasonality=False,
        interval_width=INTERVAL_WIDTH,
    )
    model.fit(history)
    np.random.seed(RANDOM_SEED)  # Prophet draws its uncertainty samples from numpy's global generator
    forecast = model.predict(pd.DataFrame({"ds": pd.to_datetime(list(targets))}))
    return forecast[["yhat", "yhat_lower", "yhat_upper"]].clip(0.0, 1.0)


def backtest(series: Series) -> tuple[float, float] | None:
    """One-step-ahead backtest over the last BACKTEST_STEPS weeks.

    For each of those weeks, fit on everything before it and predict it; compare
    with the naive forecast "the share stays at last week's value".

    Args:
        series: A series.

    Returns:
        (Prophet MAE, naive MAE) in share points, or None below MIN_WEEKS_TO_BACKTEST.
    """
    n = len(series.shares)
    if n < MIN_WEEKS_TO_BACKTEST:
        return None
    prophet_errors, naive_errors = [], []
    for t in range(n - BACKTEST_STEPS, n):
        predicted = _prophet_forecast(series.weeks[:t], series.shares[:t], [series.weeks[t]])["yhat"].iloc[0]
        prophet_errors.append(abs(predicted - series.shares[t]))
        naive_errors.append(abs(series.shares[t - 1] - series.shares[t]))
    return float(np.mean(prophet_errors)), float(np.mean(naive_errors))


def forecast_rows(series: Series, loaded_at: datetime) -> list[tuple]:
    """Rows for ml.skill_demand_forecast: the gate's verdict, then forecasts if any.

    Args:
        series: A series.
        loaded_at: Load time shared by every row in one run.

    Returns:
        One 'insufficient_history' row (no forecast columns), or FORECAST_WEEKS
        'forecast' rows, one per future week.
    """
    n, last_week, last_share = len(series.shares), series.weeks[-1], series.shares[-1]
    if n < MIN_WEEKS_TO_FORECAST:
        return [
            (series.role, series.skill, STATUS_INSUFFICIENT, n, last_week, last_share,
             None, None, None, None, None, None, loaded_at)
        ]
    targets = [last_week + timedelta(weeks=k) for k in range(1, FORECAST_WEEKS + 1)]
    forecast = _prophet_forecast(series.weeks, series.shares, targets)
    scores = backtest(series) or (None, None)
    return [
        (series.role, series.skill, STATUS_FORECAST, n, last_week, last_share,
         week, float(f.yhat), float(f.yhat_lower), float(f.yhat_upper), *scores, loaded_at)
        for week, f in zip(targets, forecast.itertuples(), strict=True)
    ]


def run(config: PostgresConfig) -> dict[str, int]:
    """Forecast every series that passes the gate and rebuild ml.skill_demand_forecast.

    Args:
        config: Database with the dbt marts; the forecast table is written there.

    Returns:
        Series counts per status.
    """
    series = load_series(config)
    loaded_at = datetime.now(timezone.utc)
    rows = [row for s in series for row in forecast_rows(s, loaded_at)]
    counts = {
        STATUS_FORECAST: sum(len(s.shares) >= MIN_WEEKS_TO_FORECAST for s in series),
        STATUS_INSUFFICIENT: sum(len(s.shares) < MIN_WEEKS_TO_FORECAST for s in series),
    }
    longest = max(len(s.shares) for s in series)
    logger.info(
        "%d series: %d forecast, %d insufficient_history (longest series: %d weeks; forecasting needs %d)",
        len(series), counts[STATUS_FORECAST], counts[STATUS_INSUFFICIENT], longest, MIN_WEEKS_TO_FORECAST,
    )
    replace_tables(config, ML_SCHEMA, {TABLE: (_DDL, _COLUMNS, rows)})
    return counts


def main() -> int:
    """Command-line entry point.

    Returns:
        Process exit code.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("cmdstanpy").setLevel(logging.WARNING)  # one INFO line per Stan call otherwise
    load_dotenv()
    run(PostgresConfig.from_env())
    return 0


if __name__ == "__main__":
    sys.exit(main())
