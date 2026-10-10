-- Years of experience per posting, from src/ml/nlp_pipeline.py. Renames only.
with source as (
    select * from {{ source('ml', 'posting_nlp') }}
)

select
    job_id,
    years_min as experience_years_min,
    years_max as experience_years_max,
    years_mentions as experience_mentions,
    years_evidence as experience_evidence,
    _loaded_at
from source
