-- One row per (week, role, state): posting volume plus the share of postings that
-- are remote and that list a salary (0–1). Postings with no state count under
-- 'Unknown' instead of being dropped.
select
    facts.posted_week,
    roles.role_name,
    coalesce(locations.state_code, 'Unknown') as state_code,
    count(*) as postings,
    -- avg() over booleans-as-integers ignores NULLs (postings that don't say).
    round(avg(facts.is_remote::int), 4) as share_remote,
    round(avg(facts.has_salary::int), 4) as share_with_salary
from {{ ref('fact_job_postings') }} as facts
inner join {{ ref('dim_role') }} as roles on roles.role_key = facts.role_key
inner join {{ ref('dim_location') }} as locations on locations.location_key = facts.location_key
group by facts.posted_week, roles.role_name, coalesce(locations.state_code, 'Unknown')
