"""S3 keys (curated bucket) of what the pipeline exports and the app reads.

One place for the paths, so the app can't silently read a stale location. Import-free
on purpose: the app server has no MLflow, spaCy or Spark.
"""

SALARY_MODEL_KEY = "models/salary/model.json"  # XGBoost JSON (salary_model.py)
SALARY_CARD_KEY = "models/salary/feature_spec.json"  # spec, baselines, CV MAE, use_model
# Named after the embedding model, so a different model writes elsewhere; test_nlp.py
# checks this equals the key nlp_pipeline derives from embeddings.MODEL_NAME.
POSTING_EMBEDDINGS_KEY = "embeddings/all-MiniLM-L6-v2/postings.parquet"
