-- One row per skill: median salary of postings that mention it vs. postings that
-- don't (both among postings with a salary). An association, not a causal effect:
-- skills cluster with seniority and role. The difference is left empty when
-- either side has fewer than var('min_salary_sample') postings.
with salaried as (
    select job_id, salary_mid_annual
    from {{ ref('fact_job_postings') }}
    where has_salary
),

skills as (
    select distinct skill_name, skill_category
    from {{ ref('int_job_skills_joined') }}
),

job_skill_pairs as (
    select distinct job_id, skill_name
    from {{ ref('int_job_skills_joined') }}
),

-- Every (skill, salaried posting) pair, marked by whether the posting mentions the skill.
pairs as (
    select
        skills.skill_name,
        skills.skill_category,
        salaried.salary_mid_annual,
        job_skill_pairs.job_id is not null as mentions_skill
    from skills
    cross join salaried
    left join job_skill_pairs
        on job_skill_pairs.job_id = salaried.job_id
        and job_skill_pairs.skill_name = skills.skill_name
),

stats as (
    select
        skill_name,
        skill_category,
        count(*) filter (where mentions_skill) as n_with_skill,
        count(*) filter (where not mentions_skill) as n_without_skill,
        percentile_cont(0.5) within group (order by salary_mid_annual)
            filter (where mentions_skill) as median_with_skill,
        percentile_cont(0.5) within group (order by salary_mid_annual)
            filter (where not mentions_skill) as median_without_skill
    from pairs
    group by skill_name, skill_category
),

flagged as (
    select
        *,
        n_with_skill >= {{ var('min_salary_sample') }}
            and n_without_skill >= {{ var('min_salary_sample') }} as enough_salaries
    from stats
)

select
    skill_name,
    skill_category,
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
