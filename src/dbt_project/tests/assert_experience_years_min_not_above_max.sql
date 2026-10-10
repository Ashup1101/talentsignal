-- A years-of-experience range never runs backwards ("5-3 years").
select job_id, experience_years_min, experience_years_max
from {{ ref('stg_posting_nlp') }}
where experience_years_max < experience_years_min
