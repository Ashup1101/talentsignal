-- Fails if any share/percentage column falls outside [0, 1].
select 'mart_skill_demand.share_of_role_postings' as column_checked, share_of_role_postings as value
from {{ ref('mart_skill_demand') }}
where share_of_role_postings not between 0 and 1

union all

select 'mart_job_trends.share_remote', share_remote
from {{ ref('mart_job_trends') }}
where share_remote not between 0 and 1

union all

select 'mart_job_trends.share_with_salary', share_with_salary
from {{ ref('mart_job_trends') }}
where share_with_salary not between 0 and 1
