-- One row per search role, from the role_soc_mapping seed (the official list of
-- roles), with the BLS benchmark for its occupation. Roles mapped to no SOC code
-- (data analyst, by decision) keep empty BLS columns.
with mapping as (
    select * from {{ ref('role_soc_mapping') }}
),

bls as (
    select * from {{ ref('stg_bls_occupations') }}
)

select
    md5(lower(mapping.search_role)) as role_key,
    mapping.search_role as role_name,
    mapping.soc_code,
    mapping.onet_soc_code,
    mapping.onet_title,
    bls.occupation_title as bls_occupation_title,
    bls.median_annual_wage as bls_median_annual_wage,
    bls.total_employment as bls_total_employment,
    bls.reference_year as bls_reference_year,
    mapping.evidence as soc_mapping_evidence
from mapping
left join bls on bls.soc_code = mapping.soc_code
