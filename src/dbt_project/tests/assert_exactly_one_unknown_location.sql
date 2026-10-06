-- Fails unless dim_location has exactly one 'Unknown' member.
select count(*) as unknown_members
from {{ ref('dim_location') }}
where is_unknown
having count(*) <> 1
