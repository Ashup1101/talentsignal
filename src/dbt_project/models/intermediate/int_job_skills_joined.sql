-- One row per (posting, skill), carrying the posting attributes the skill
-- marts group by, so those marts need no joins.
select
    skills.job_id,
    skills.skill_name,
    skills.skill_category,
    jobs.search_role,
    jobs.city,
    jobs.state_code,
    jobs.posted_date,
    jobs.posted_week,
    jobs.seniority,
    jobs.has_salary,
    jobs.salary_mid_annual
from {{ ref('stg_skills') }} as skills
inner join {{ ref('int_jobs_enriched') }} as jobs on jobs.job_id = skills.job_id
