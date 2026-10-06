-- One row per BLS detailed occupation (OEWS national estimates).
with source as (
    select * from {{ source('raw', 'bls_occupations') }}
)

select
    occupation_code as soc_code,
    title as occupation_title,
    total_employment,
    median_wage as median_annual_wage,
    reference_year,
    fetched_at,
    _loaded_at
from source
