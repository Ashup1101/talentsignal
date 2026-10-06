-- One row per unique job posting. Renames only; cleaning happened in Spark (Phase 2).
with source as (
    select * from {{ source('raw', 'jobs_clean') }}
)

select
    job_id,
    title as job_title,
    title_normalized as job_title_normalized,
    employer as employer_name,
    employer_normalized as employer_name_normalized,
    publisher,
    employment_type,
    is_remote,
    city,
    state as state_name,
    state_code,
    country as country_code,
    latitude,
    longitude,
    posted_at,
    search_role,
    search_location,
    salary_min_raw,
    salary_max_raw,
    salary_period_raw as salary_period,
    salary_min_annual,
    salary_max_annual,
    salary_mid_annual,
    salary_flag,
    description as job_description,
    apply_link,
    dedup_key,
    fetched_at,
    ingest_date,
    _loaded_at
from source
