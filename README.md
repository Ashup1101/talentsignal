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
| 4     | Airflow orchestration          | Done        |
| 5     | NLP + ML models                | Not started |
| 6     | Streamlit app + EC2 hosting    | Not started |

## Local setup

Requires Python 3.11 and Java 17 (for local Spark; `brew install openjdk@17`,
then set `JAVA_HOME`). On macOS, XGBoost also needs OpenMP: `brew install libomp`.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-ml.txt   # everything: pipeline + dev + ML (~2.6 GB)
# create .env with the variables under "Secrets needed" in CLAUDE.md
pytest
```

`requirements-dev.txt` (pipeline + dev tools, no ML) is what the CI `pytest` job
installs; ML tests skip themselves there and run in the separate `ml` job.

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

## Phase 4: orchestrate with Airflow

Airflow 3 runs locally in its own virtualenv (its pinned libraries conflict with
the pipeline's), with no Docker:

```bash
infra/airflow/install.sh     # once: .venv-airflow with Airflow 3.3.1 + constraints
infra/airflow/run_local.sh   # UI on http://localhost:8080 (Ctrl+C stops it)
```

Login: user `admin`, password in `.airflow/simple_auth_manager_passwords.json.generated`.

- `talentsignal_pipeline` (daily, 22:00 UTC): fetch_jobs → clean_jobs →
  extract_skills → load_postgres → dbt_source_freshness → dbt_build
- `talentsignal_bls` (monthly): fetch_bls → clean_bls

Both DAGs start paused, so nothing runs or spends JSearch quota until switched
on. Switching a DAG on immediately runs its most recent missed slot.

First end-to-end runs (2026-10-07): about 2 minutes with a JSearch fetch (118.5 s),
91 s without. `load_postgres` took ~22 s in both runs, compared with ~4 min on the
first manual load, which hasn't recurred.

Dependencies are declared in `pyproject.toml` and pinned with pip-tools:

```bash
pip-compile -o requirements.txt pyproject.toml
pip-compile --extra dev -o requirements-dev.txt pyproject.toml
pip-compile --extra dev --extra ml -o requirements-ml.txt pyproject.toml
```
