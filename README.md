# TalentSignal

Job market intelligence and predictive analytics platform. Job postings are
ingested from public APIs into S3, processed with PySpark on Databricks,
modeled with dbt, orchestrated by Airflow, enriched with NLP + ML, and served
through a Streamlit app on AWS EC2.

See [CLAUDE.md](CLAUDE.md) for the full specification and phase plan.

## Status

| Phase | Scope                          | Status      |
|-------|--------------------------------|-------------|
| 1     | Ingestion (JSearch, BLS → S3)  | In progress |
| 2     | PySpark processing             | Not started |
| 3     | dbt modeling                   | Not started |
| 4     | Airflow orchestration          | Not started |
| 5     | NLP + ML models                | Not started |
| 6     | Streamlit app + EC2 hosting    | Not started |

## Local setup

Requires Python 3.11.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
# create .env with the variables under "Secrets needed" in CLAUDE.md
pytest
```

## Phase 1: land raw data in S3

```bash
python -m src.ingestion.fetch_bls    # s3://$S3_RAW_BUCKET/bls/raw/{date}.json
python -m src.ingestion.fetch_jobs   # s3://$S3_RAW_BUCKET/jobs/raw/{role}/{location}/{date}.json
```

Both are idempotent per day: an existing object is never overwritten, and
`fetch_jobs` skips role/location pairs already landed today without calling
the API, so reruns don't spend JSearch quota.

Dependencies are declared in `pyproject.toml` and pinned with pip-tools:

```bash
pip-compile -o requirements.txt pyproject.toml
pip-compile --extra dev -o requirements-dev.txt pyproject.toml
```
