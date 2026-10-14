-- One row per (role, skill): how much of the role's postings mention the skill —
-- the app's match % (D2) and missing-skill picks (D3) — next to the within-role
-- salary comparison from mart_skill_salary_by_role (an association, not a causal
-- effect; empty when either side has too few salaries).
with role_postings as (
    select
        roles.role_name,
        count(*) as n_role_postings
    from {{ ref('fact_job_postings') }} as facts
    inner join {{ ref('dim_role') }} as roles on roles.role_key = facts.role_key
    group by roles.role_name
),

skill_postings as (
    select
        search_role as role_name,
        skill_name,
        skill_category,
        count(distinct job_id) as n_postings_with_skill
    from {{ ref('int_job_skills_joined') }}
    group by search_role, skill_name, skill_category
)

select
    skill_postings.role_name,
    skill_postings.skill_name,
    skill_postings.skill_category,
    role_postings.n_role_postings,
    skill_postings.n_postings_with_skill,
    round(skill_postings.n_postings_with_skill::numeric / role_postings.n_role_postings, 4)
        as share_of_role_postings,
    -- 1 = the role's most-mentioned skill; ties broken alphabetically so ranks are unique.
    row_number() over (
        partition by skill_postings.role_name
        order by skill_postings.n_postings_with_skill desc, skill_postings.skill_name
    ) as demand_rank,
    coalesce(salaries.n_with_skill, 0) as n_salaried_with_skill,
    coalesce(salaries.n_without_skill, 0) as n_salaried_without_skill,
    coalesce(salaries.sample_status, 'too_few_to_report') as salary_sample_status,
    salaries.median_salary_with_skill,
    salaries.median_salary_without_skill,
    salaries.median_salary_difference,
    salaries.median_salary_difference_pct
from skill_postings
inner join role_postings on role_postings.role_name = skill_postings.role_name
left join {{ ref('mart_skill_salary_by_role') }} as salaries
    on salaries.role_name = skill_postings.role_name
    and salaries.skill_name = skill_postings.skill_name
