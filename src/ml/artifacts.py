"""S3 keys (curated bucket) of what the pipeline exports and the app reads.

One place for the paths, so the app can't silently read a stale location. Import-free
on purpose: the app server has no MLflow, spaCy or Spark.
"""

# The embedding model, pinned: postings (nlp_pipeline) and resumes (the app) must be
# embedded by the same weights, or their similarities are meaningless.
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_MODEL_REVISION = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"

SALARY_MODEL_KEY = "models/salary/model.json"  # XGBoost JSON (salary_model.py)
SALARY_CARD_KEY = "models/salary/feature_spec.json"  # spec, baselines, CV MAE, use_model
# Named after the embedding model, so a different model writes elsewhere; test_nlp.py
# checks this equals the key nlp_pipeline derives from embeddings.MODEL_NAME.
POSTING_EMBEDDINGS_KEY = "embeddings/all-MiniLM-L6-v2/postings.parquet"
