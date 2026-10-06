-- One row per job posting. Measures (salaries, skill_count) plus keys to
-- dim_role and dim_location. Title, employer and apply link stay here as
-- degenerate dimensions: they're unique per posting, and the app lists them.
select
    job_id,
    role_key,
    location_key,
    posted_date,
    posted_week,
    seniority,
    seniority_from_title,
    employment_type,
    is_remote,
    publisher,
    salary_min_annual,
    salary_mid_annual,
    salary_max_annual,
    salary_flag,
    has_salary,
    skill_count,
    job_title,
    employer_name,
    apply_link,
    fetched_at
from {{ ref('int_jobs_enriched') }}
