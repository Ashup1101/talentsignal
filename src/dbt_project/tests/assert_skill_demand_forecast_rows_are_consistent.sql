-- 'forecast' rows carry a future week and 0 ≤ lower ≤ forecast ≤ upper ≤ 1;
-- 'insufficient_history' rows carry no forecast at all.
select *
from {{ ref('stg_skill_demand_forecast') }}
where (
        forecast_status = 'forecast'
        and not (
            forecast_week > last_observed_week
            and share_lower >= 0
            and share_lower <= share_forecast
            and share_forecast <= share_upper
            and share_upper <= 1
        )
    )
    or (
        forecast_status = 'insufficient_history'
        and coalesce(forecast_week::text, share_forecast::text, share_lower::text, share_upper::text) is not null
    )
    or last_observed_share not between 0 and 1
