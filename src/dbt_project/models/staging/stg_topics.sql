-- One row per BERTopic topic (src/ml/topics.py); topic_id -1 holds the postings
-- that fit no topic ("unassigned"). Renames only.
with source as (
    select * from {{ source('ml', 'topics') }}
)

select
    topic_id,
    label as topic_label,
    top_words as topic_top_words,
    n_postings,
    _loaded_at
from source
