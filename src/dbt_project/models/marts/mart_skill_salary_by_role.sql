-- One row per (role, skill): median salary of that role's salaried postings that
-- mention the skill vs those that don't. Comparing WITHIN a role removes the
-- role-mix effect in mart_skill_salary (e.g. Excel looked −$65K overall because it
-- is mostly an analyst skill). Still an association, not a causal effect:
-- seniority and city can differ between the two groups. The difference is left
-- empty when either side has fewer than var('min_salary_sample') postings.
with salaried as (
    select
        facts.job_id,
        roles.role_name,
        facts.salary_mid_annual
    from {{ ref('fact_job_postings') }} as facts
    inner join {{ ref('dim_role') }} as roles on roles.role_key = facts.role_key
    where facts.has_salary
),

-- Every skill mentioned by at least one posting of the role (salaried or not), so
-- the app can say "no salary data for this skill in this role" instead of nothing.
role_skills as (
    select distinct
        search_role as role_name,
        skill_name,
        skill_category
    from {{ ref('int_job_skills_joined') }}
),

job_skill_pairs as (
    select distinct job_id, skill_name
    from {{ ref('int_job_skills_joined') }}
),

-- Every (role, skill) × salaried posting of that role, marked by whether the
-- posting mentions the skill.
pairs as (
    select
        role_skills.role_name,
        role_skills.skill_name,
        role_skills.skill_category,
        salaried.salary_mid_annual,
        job_skill_pairs.job_id is not null as mentions_skill
    from role_skills
    inner join salaried on salaried.role_name = role_skills.role_name
    left join job_skill_pairs
        on job_skill_pairs.job_id = salaried.job_id
        and job_skill_pairs.skill_name = role_skills.skill_name
),

stats as (
    select
        role_name,
        skill_name,
        skill_category,
        count(*) as n_role_salaried,
        count(*) filter (where mentions_skill) as n_with_skill,
        count(*) filter (where not mentions_skill) as n_without_skill,
        percentile_cont(0.5) within group (order by salary_mid_annual)
            filter (where mentions_skill) as median_with_skill,
        percentile_cont(0.5) within group (order by salary_mid_annual)
            filter (where not mentions_skill) as median_without_skill
    from pairs
    group by role_name, skill_name, skill_category
),

flagged as (
    select
        *,
        n_with_skill >= {{ var('min_salary_sample') }}
            and n_without_skill >= {{ var('min_salary_sample') }} as enough_salaries
    from stats
)

select
    role_name,
    skill_name,
    skill_category,
    n_role_salaried,
    n_with_skill,
    n_without_skill,
    case when enough_salaries then 'ok' else 'too_few_to_report' end as sample_status,
    round(median_with_skill::numeric) as median_salary_with_skill,
    round(median_without_skill::numeric) as median_salary_without_skill,
    case when enough_salaries then round((median_with_skill - median_without_skill)::numeric) end
        as median_salary_difference,
    case
        when enough_salaries and median_without_skill > 0
            then round((median_with_skill / median_without_skill - 1)::numeric, 4)
    end as median_salary_difference_pct
from flagged
