-- One row per place (city + state + country), plus exactly one 'Unknown' member
-- for postings with no city and no state, so every fact row has a location.
with postings as (
    select location_key, city, state_code, country_code
    from {{ ref('int_jobs_enriched') }}
),

known as (
    select
        location_key,
        -- Keys are built from lowercased text, so case variants share one row.
        min(city) as city,
        min(state_code) as state_code,
        min(country_code) as country_code
    from postings
    where location_key <> md5('unknown')
    group by location_key
)

select
    location_key,
    city,
    state_code,
    country_code,
    concat_ws(', ', city, state_code) as location_name,
    false as is_unknown
from known

union all

select
    md5('unknown') as location_key,
    null as city,
    null as state_code,
    null as country_code,
    'Unknown' as location_name,
    true as is_unknown
