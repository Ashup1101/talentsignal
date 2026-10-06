-- One row per posting, plus derived fields: seniority (rule-based, from the
-- title), skill_count, posting date/week in UTC and has_salary.
with jobs as (
    select * from {{ ref('stg_jobs') }}
),

skill_counts as (
    select job_id, count(*) as skill_count
    from {{ ref('stg_skills') }}
    group by job_id
),

classified as (
    select
        jobs.*,
        -- First matching rule wins (e.g. "Senior Manager" → manager).
        -- \m and \M are PostgreSQL word boundaries, so "sr" won't match "srs".
        case
            when job_title ~* '\m(intern|interns|internship|co-op|coop)\M' then 'intern'
            when job_title ~* '\m(manager|director|head|vp|vice president|chief)\M' then 'manager'
            when job_title ~* '\m(staff|principal|distinguished|fellow|lead|architect)\M' then 'staff_plus'
            when job_title ~* '\m(senior|sr|iii|iv)\M' then 'senior'
            when job_title ~* '\mii\M' then 'mid'
            when job_title ~* '\m(junior|jr|entry|associate|graduate|grad|early career|i)\M' then 'junior'
        end as seniority_rule
    from jobs
)

select
    classified.job_id,
    -- Star-schema keys, defined once here so dims and fact can't disagree.
    -- Hashes of natural keys are stable across rebuilds (unlike row numbers).
    md5(lower(classified.search_role)) as role_key,
    case
        when classified.city is null and classified.state_code is null then md5('unknown')
        else md5(lower(concat_ws('|',
            coalesce(classified.city, ''),
            coalesce(classified.state_code, ''),
            coalesce(classified.country_code, ''))))
    end as location_key,
    classified.job_title,
    classified.employer_name,
    classified.publisher,
    classified.employment_type,
    classified.is_remote,
    classified.city,
    classified.state_code,
    classified.country_code,
    classified.search_role,
    classified.posted_at,
    (classified.posted_at at time zone 'UTC')::date as posted_date,
    date_trunc('week', classified.posted_at at time zone 'UTC')::date as posted_week,
    -- Titles with no level word default to 'mid'; seniority_from_title says
    -- whether the level was actually stated.
    coalesce(classified.seniority_rule, 'mid') as seniority,
    classified.seniority_rule is not null as seniority_from_title,
    classified.salary_min_annual,
    classified.salary_max_annual,
    classified.salary_mid_annual,
    classified.salary_flag,
    classified.salary_mid_annual is not null as has_salary,
    coalesce(skill_counts.skill_count, 0) as skill_count,
    classified.apply_link,
    classified.fetched_at
from classified
left join skill_counts on skill_counts.job_id = classified.job_id
