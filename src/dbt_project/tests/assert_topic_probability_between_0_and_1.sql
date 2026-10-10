-- HDBSCAN membership strength is a probability; unassigned postings get 0.
select job_id, topic_id, topic_probability
from {{ ref('stg_posting_topics') }}
where topic_probability < 0
   or topic_probability > 1
   or (topic_id = -1 and topic_probability <> 0)
