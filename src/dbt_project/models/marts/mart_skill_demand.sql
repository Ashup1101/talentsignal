-- One row per (collection week, role, skill) for every week the role was sampled:
-- of the distinct postings collected for the role that week, how many mention the
-- skill and what share that is (0–1).
-- Built from job_sightings (every collection), not jobs_clean (latest copy only),
-- so a week's numbers never change once the week is over. Weeks a role wasn't
-- sampled have no rows (a gap, not a zero); in sampled weeks, skills nobody
-- mentioned get 0.
with sightings as (
    select
        date_trunc('week', fetched_at at time zone 'UTC')::date as collection_week,
        search_role,
        dedup_key
    from {{ ref('stg_job_sightings') }}
),

role_weeks as (
    -- Distinct postings (by content) collected per role per week.
    select collection_week, search_role, count(distinct dedup_key) as role_postings
    from sightings
    group by collection_week, search_role
),

-- Skills come from a posting's text, so look them up via the content key on the
-- copy jobs_clean kept (one per dedup_key).
posting_skills as (
    select jobs.dedup_key, skills.skill_name, skills.skill_category
    from {{ ref('stg_skills') }} as skills
    inner join {{ ref('stg_jobs') }} as jobs on jobs.job_id = skills.job_id
),

skill_weeks as (
    select
        sightings.collection_week,
        sightings.search_role,
        posting_skills.skill_name,
        count(distinct sightings.dedup_key) as postings_with_skill
    from sightings
    inner join posting_skills on posting_skills.dedup_key = sightings.dedup_key
    group by sightings.collection_week, sightings.search_role, posting_skills.skill_name
),

-- Zero-fill catalog: every skill ever seen for the role.
role_skills as (
    select distinct sightings.search_role, posting_skills.skill_name, posting_skills.skill_category
    from sightings
    inner join posting_skills on posting_skills.dedup_key = sightings.dedup_key
)

select
    role_weeks.collection_week,
    role_weeks.search_role,
    role_skills.skill_name,
    role_skills.skill_category,
    coalesce(skill_weeks.postings_with_skill, 0) as postings_with_skill,
    role_weeks.role_postings,
    round(coalesce(skill_weeks.postings_with_skill, 0)::numeric / role_weeks.role_postings, 4)
        as share_of_role_postings
from role_weeks
inner join role_skills on role_skills.search_role = role_weeks.search_role
left join skill_weeks
    on skill_weeks.collection_week = role_weeks.collection_week
    and skill_weeks.search_role = role_weeks.search_role
    and skill_weeks.skill_name = role_skills.skill_name
