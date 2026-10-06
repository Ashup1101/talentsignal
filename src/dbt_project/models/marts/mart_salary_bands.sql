-- One row per role: salary percentiles from postings (range midpoints) next to
-- the BLS median. Roles with fewer than var('min_salary_sample') salaries get
-- empty percentiles and sample_status = 'too_few_to_report'.
with postings as (
    select
        roles.role_name,
        roles.bls_median_annual_wage,
        facts.has_salary,
        facts.salary_mid_annual
    from {{ ref('fact_job_postings') }} as facts
    inner join {{ ref('dim_role') }} as roles on roles.role_key = facts.role_key
),

stats as (
    select
        role_name,
        max(bls_median_annual_wage) as bls_median_annual_wage,
        count(*) as n_postings,
        count(*) filter (where has_salary) as n_with_salary,
        percentile_cont(0.25) within group (order by salary_mid_annual) as p25,
        percentile_cont(0.50) within group (order by salary_mid_annual) as p50,
        percentile_cont(0.75) within group (order by salary_mid_annual) as p75
    from postings
    group by role_name
),

flagged as (
    select
        *,
        n_with_salary >= {{ var('min_salary_sample') }} as enough_salaries
    from stats
)

select
    role_name,
    n_postings,
    n_with_salary,
    case when enough_salaries then 'ok' else 'too_few_to_report' end as sample_status,
    case when enough_salaries then round(p25::numeric) end as salary_p25,
    case when enough_salaries then round(p50::numeric) end as salary_median,
    case when enough_salaries then round(p75::numeric) end as salary_p75,
    bls_median_annual_wage,
    case
        when enough_salaries and bls_median_annual_wage > 0
            then round((p50 / bls_median_annual_wage - 1)::numeric, 4)
    end as median_vs_bls_pct
from flagged
