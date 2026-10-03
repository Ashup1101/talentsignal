# TalentSignal — Project Specification for Claude Code

## What this is
An end-to-end job market intelligence platform. Raw job postings are ingested
from public APIs, processed at scale with PySpark on Databricks, modeled with
dbt, orchestrated by Airflow, enriched with NLP + ML, and served through a
hosted Streamlit app on AWS EC2.

Goal: a publicly accessible, interview-demonstrable portfolio project covering
the full data engineering + ML stack.

## Rebuild targets (from the original project's resume description)
This repo rebuilds an earlier version of TalentSignal whose code was lost; only
the resume description survives. Each phase must deliver what it claims:
- Scale: structured analytics across 50K+ job postings (after dedup).
- Databricks PySpark: large-scale deduplication + skill extraction via UDFs.
- dbt: star-schema mart layer over RDS PostgreSQL — dim_role, dim_location,
  fact_job_postings — alongside the trend / salary / skill-demand marts.
- NLP: spaCy + BERTopic skill extraction and latent topic clustering of
  job descriptions, run in Databricks.
- ML: XGBoost salary predictor with MLflow tracking (target MAE < $9K);
  Prophet skill-demand forecaster with a 90-day horizon.
- Airflow: daily DAG using DatabricksRunNowOperator to chain ingestion →
  PySpark → dbt run → ML retraining.
- App: four-page Streamlit app on EC2 behind nginx, CI/CD via GitHub Actions,
  showing live salary predictions, skill demand forecasts, market trends.

Numbers above are targets, not facts. Measure them on real data and report
the actual result (e.g. real held-out MAE), even if it misses the target.

---

## Tech stack (use exactly these, no substitutions without asking)
- Ingestion:        Python 3.11, boto3, requests, JSearch API (RapidAPI)
- Storage:          AWS S3 (raw / processed / curated zones), AWS RDS PostgreSQL
- Processing:       PySpark, Databricks (Delta Lake format)
- Transformation:   dbt Core (dbt-postgres adapter)
- Orchestration:    Apache Airflow 2.x (Docker Compose locally)
- NLP:              spaCy, sentence-transformers, BERTopic, VADER
- ML:               XGBoost, Prophet, scikit-learn, MLflow (Databricks-hosted)
- App:              Streamlit
- Hosting:          AWS EC2 t3.small, nginx, systemd, GitHub Actions CI/CD
- Python deps:      managed via pyproject.toml + pip-tools

---

## Repo structure (create this exactly)
```
talentsignal/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .gitignore
│
├── infra/
│   ├── terraform/                # S3 buckets, RDS, EC2 (scaffold only for now)
│   └── docker-compose.yml        # Airflow local dev
│
├── src/
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── fetch_jobs.py         # JSearch API → S3 raw zone
│   │   ├── fetch_bls.py          # BLS Occupational Outlook → S3 raw zone
│   │   └── s3_utils.py           # boto3 helpers (upload, check exists, list)
│   │
│   ├── processing/               # PySpark notebooks + scripts
│   │   ├── clean_jobs.py         # flatten JSON, deduplicate, normalize
│   │   └── extract_skills.py     # PySpark UDF for skill extraction
│   │
│   ├── dbt_project/              # full dbt project lives here
│   │   ├── dbt_project.yml
│   │   ├── profiles.yml.example
│   │   ├── models/
│   │   │   ├── staging/
│   │   │   │   ├── stg_jobs.sql
│   │   │   │   └── stg_skills.sql
│   │   │   ├── intermediate/
│   │   │   │   └── int_job_skills_joined.sql
│   │   │   └── marts/
│   │   │       ├── mart_job_trends.sql
│   │   │       ├── mart_salary_bands.sql
│   │   │       └── mart_skill_demand.sql
│   │   └── tests/
│   │
│   ├── dags/                     # Airflow DAGs
│   │   └── talentsignal_pipeline.py
│   │
│   ├── ml/
│   │   ├── nlp_pipeline.py       # spaCy + BERTopic skill extraction + clustering
│   │   ├── salary_model.py       # XGBoost regressor + MLflow logging
│   │   └── demand_forecast.py    # Prophet time-series per skill
│   │
│   └── app/
│       ├── streamlit_app.py      # entry point
│       └── pages/
│           ├── 01_market_overview.py
│           ├── 02_salary_explorer.py
│           ├── 03_skill_demand.py
│           └── 04_job_insights.py
│
├── tests/
│   ├── test_ingestion.py
│   └── test_ml.py
│
└── .github/
    └── workflows/
        └── ci.yml                # dbt test on PR, redeploy app on merge to main
```

---

## Phase plan — work one phase at a time, do not jump ahead

### Phase 1 — Ingestion (start here)
Files to build:
- src/ingestion/s3_utils.py
  - upload_json(bucket, key, data: dict) → None
  - key_exists(bucket, key) → bool
  - list_keys(bucket, prefix) → list[str]
  - All errors raised with descriptive messages; no silent failures

- src/ingestion/fetch_jobs.py
  - fetch_jobs(role: str, location: str, num_pages: int = 3) → list[dict]
    Calls JSearch API (/search-v2 endpoint; /search was retired), follows the
    response cursor (~10 jobs per page, 1 API request each), returns raw results
  - save_to_s3(jobs: list[dict], role: str, location: str) → str
    Lands as s3://{RAW_BUCKET}/jobs/raw/{role}/{location}/{date}.json
    Key is idempotent — same role+location+date never overwrites
  - __main__ block: runs a sample pull for 5 roles × 5 cities

- src/ingestion/fetch_bls.py
  - fetch_bls_outlook() → list[dict]
    Reads BLS OEWS national data (oesm{YY}nat.zip → xlsx, no API key needed;
    BLS rejects requests without a contact email in the User-Agent)
    Returns list of {occupation_code, title, total_employment, median_wage}
  - save_to_s3(data) → str (same pattern as above, prefix bls/raw/)

- pyproject.toml — define all deps for Phase 1 only

Deliverable: running `python -m src.ingestion.fetch_jobs` populates S3 with
real data. Must work end-to-end before Phase 2 starts.

### Phase 2 — PySpark processing (Databricks)
Build after Phase 1 is confirmed working.
Files: src/processing/clean_jobs.py, src/processing/extract_skills.py
Details: TBD — ask for spec when Phase 1 is done.

### Phase 3 — dbt modeling
Build after Phase 2 is confirmed working.
Details: TBD — ask for spec when Phase 2 is done.

### Phase 4 — Airflow orchestration
Build after Phase 3 is confirmed working.
Details: TBD — ask for spec when Phase 3 is done.

### Phase 5 — NLP + ML models
Build after Phase 4 is confirmed working.
Details: TBD — ask for spec when Phase 4 is done.

### Phase 6 — Streamlit app + EC2 hosting
Build after Phase 5 is confirmed working.
Details: TBD — ask for spec when Phase 5 is done.

---

## Coding standards
- Type hints on every function signature
- Docstrings on every public function (one-line summary + Args/Returns)
- Environment variables via python-dotenv; keep "Secrets needed" below updated (it is the .env template)
- No hardcoded credentials anywhere — raise ValueError if env var missing
- Logging via Python's logging module (not print statements)
- Tests in tests/ using pytest; at minimum one happy-path test per module

## Secrets needed (set in .env, never committed)
```
RAPIDAPI_KEY=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=us-east-1
S3_RAW_BUCKET=talentsignal-raw
S3_PROCESSED_BUCKET=talentsignal-processed
S3_CURATED_BUCKET=talentsignal-curated
RDS_HOST=
RDS_PORT=5432
RDS_DB=talentsignal
RDS_USER=
RDS_PASSWORD=
BLS_CONTACT_EMAIL=          # sent in the User-Agent; BLS blocks anonymous scripts
```

## What to do if you're blocked
- Missing credential / env var → stop, tell me exactly what's needed
- Unclear schema from API → show me a sample response and ask
- Two valid implementation approaches → list both briefly and ask
- Never invent data, never mock an external call in production code
