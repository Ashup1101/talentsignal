# TalentSignal

Job market intelligence and predictive analytics platform. Job postings are
ingested from public APIs into S3, processed with PySpark on Databricks,
modeled with dbt, orchestrated by Airflow, enriched with NLP + ML, and served
through a Streamlit app on AWS EC2.

See [CLAUDE.md](CLAUDE.md) for the full specification and phase plan.

## Status

| Phase | Scope                          | Status      |
|-------|--------------------------------|-------------|
| 1     | Ingestion (JSearch, BLS → S3)  | Done        |
| 2     | PySpark processing             | Done (local; Databricks pending) |
| 3     | dbt modeling                   | Done        |
| 4     | Airflow orchestration          | Not started |
| 5     | NLP + ML models                | Not started |
| 6     | Streamlit app + EC2 hosting    | Not started |

## Local setup

Requires Python 3.11 and Java 17 (for local Spark; `brew install openjdk@17`,
then set `JAVA_HOME`).

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

Both are idempotent per day: an existing object is never overwritten.

`fetch_jobs` stays inside a monthly JSearch budget (`JSEARCH_MONTHLY_BUDGET`,
default 180 of the free plan's 200): each run fetches only today's share, rotating
through the 25 role × city pairs least-recently-fetched first, and stops early if
RapidAPI reports ≤ `JSEARCH_RESERVE_REQUESTS` (default 20) left. Same-day reruns
spend nothing extra. See what tonight's run would do, without spending quota:

```bash
python -m src.ingestion.fetch_jobs --dry-run
```

## Phase 2: clean and enrich with PySpark

```bash
python -m src.processing.clean_jobs      # → s3://$S3_PROCESSED_BUCKET/delta/jobs_clean
python -m src.processing.extract_skills  # → delta/job_skills (needs jobs_clean)
python -m src.processing.clean_bls       # → delta/bls_occupations
```

Each job rebuilds its Delta table from scratch, so reruns are safe. While one
runs locally, the Spark UI is at http://localhost:4040. The first run
downloads the Delta and S3 connector jars (a few hundred MB, cached in ~/.ivy2).

Dependencies are declared in `pyproject.toml` and pinned with pip-tools:

```bash
pip-compile -o requirements.txt pyproject.toml
pip-compile --extra dev -o requirements-dev.txt pyproject.toml
```
