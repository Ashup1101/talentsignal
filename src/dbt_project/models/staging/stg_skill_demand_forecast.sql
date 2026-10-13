-- Per role × skill: the forecast gate's verdict and, once a series has enough
-- weeks, one row per future week (src/ml/demand_forecast.py). Renames only.
with source as (
    select * from {{ source('ml', 'skill_demand_forecast') }}
)

select
    search_role,
    skill_name,
    status as forecast_status,
    n_weeks as observed_weeks,
    last_observed_week,
    last_observed_share,
    forecast_week,
    share_forecast,
    share_lower,
    share_upper,
    backtest_mae_prophet,
    backtest_mae_naive,
    _loaded_at
from source
