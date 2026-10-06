-- One row per (week, role, skill) that occurs: how many of the role's postings
-- that week mention the skill, and what share that is (0–1). Weeks where a
-- skill wasn't mentioned have no row; Phase 5 fills those with zeros.
with role_weeks as (
    select
        posted_week,
        search_role,
        count(*) as role_postings
    from {{ ref('int_jobs_enriched') }}
    group by posted_week, search_role
),

skill_weeks as (
    select
        posted_week,
        search_role,
        skill_name,
        skill_category,
        count(distinct job_id) as postings_with_skill
    from {{ ref('int_job_skills_joined') }}
    group by posted_week, search_role, skill_name, skill_category
)

select
    skill_weeks.posted_week,
    skill_weeks.search_role,
    skill_weeks.skill_name,
    skill_weeks.skill_category,
    skill_weeks.postings_with_skill,
    role_weeks.role_postings,
    round(skill_weeks.postings_with_skill::numeric / role_weeks.role_postings, 4) as share_of_role_postings
from skill_weeks
inner join role_weeks
    on role_weeks.posted_week = skill_weeks.posted_week
    and role_weeks.search_role = skill_weeks.search_role
