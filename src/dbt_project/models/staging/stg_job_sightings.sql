-- One row per posting per collection (before dedup). Renames only.
with source as (
    select * from {{ source('raw', 'job_sightings') }}
)

select
    job_id,
    dedup_key,
    search_role,
    search_location,
    fetched_at,
    ingest_date,
    _loaded_at
from source
