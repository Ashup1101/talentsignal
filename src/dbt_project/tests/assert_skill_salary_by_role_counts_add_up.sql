-- Fails if a (role, skill) row doesn't split the role's salaried postings exactly
-- into "mentions the skill" + "doesn't" (a posting double-counted or lost).
select role_name, skill_name, n_role_salaried, n_with_skill, n_without_skill
from {{ ref('mart_skill_salary_by_role') }}
where n_with_skill + n_without_skill <> n_role_salaried
