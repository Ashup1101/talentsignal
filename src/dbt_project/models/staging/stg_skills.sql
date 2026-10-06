-- One row per (job posting, skill) found by the dictionary-based extractor.
with source as (
    select * from {{ source('raw', 'job_skills') }}
)

select
    job_id,
    skill as skill_name,
    category as skill_category,
    _loaded_at
from source
