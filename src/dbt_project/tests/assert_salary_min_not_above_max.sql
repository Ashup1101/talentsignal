-- Fails if any posting's annual salary range is inverted.
-- (Phase 2 already nulls inverted ranges; this guards against regressions.)
select job_id, salary_min_annual, salary_max_annual
from {{ ref('fact_job_postings') }}
where salary_min_annual > salary_max_annual
