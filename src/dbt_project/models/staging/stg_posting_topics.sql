-- Each posting's topic (-1 = unassigned) and how firmly it belongs there. Renames only.
with source as (
    select * from {{ source('ml', 'posting_topics') }}
)

select
    job_id,
    topic_id,
    topic_probability,
    _loaded_at
from source
