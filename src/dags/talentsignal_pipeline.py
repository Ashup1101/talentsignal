"""Daily TalentSignal pipeline: JSearch → S3 raw → Spark (Delta) → RDS → dbt.

fetch_jobs → clean_jobs → extract_skills → load_postgres → dbt_source_freshness → dbt_build

Every task is a BashOperator running the same command you would run by hand, in
the project's own virtualenv (.venv). Airflow's environment (.venv-airflow) never
imports pipeline code, so the two sets of pinned libraries can't clash, and this
file stays cheap to parse (the dag-processor re-reads it every ~30 s).

If a task fails, everything after it is marked upstream_failed and does not run,
so RDS keeps the last good build instead of being rebuilt from partial input.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

REPO = Path(__file__).resolve().parents[2]
PYTHON = f"{REPO}/.venv/bin/python"
# dbt doesn't read .env itself, so run it through python-dotenv.
DBT = f"{REPO}/.venv/bin/dotenv -f {REPO}/.env run -- {REPO}/.venv/bin/dbt"
DBT_DIRS = "--project-dir src/dbt_project --profiles-dir src/dbt_project"
# Airflow 3 manual runs may have no logical date; fall back to when the run was due.
RUN_DATE = "{{ (logical_date or dag_run.run_after).strftime('%Y-%m-%d') }}"

with DAG(
    dag_id="talentsignal_pipeline",
    description="Daily: fetch postings → clean → extract skills → load RDS → dbt build",
    schedule="0 22 * * *",  # 22:00 UTC every day (6 pm US Eastern)
    start_date=pendulum.datetime(2026, 10, 1, tz="UTC"),
    catchup=False,  # when switched on, don't replay every missed day
    max_active_runs=1,  # runs write the same tables; never overlap two days
    is_paused_upon_creation=True,  # nothing runs (or spends JSearch quota) until unpaused
    default_args={"retries": 1, "retry_delay": timedelta(minutes=5)},
    tags=["talentsignal"],
    doc_md=__doc__,
) as dag:
    fetch_jobs = BashOperator(
        task_id="fetch_jobs",
        bash_command=f"{PYTHON} -m src.ingestion.fetch_jobs --run-date " + RUN_DATE,
        cwd=str(REPO),
        retries=2,
        retry_delay=timedelta(minutes=10),  # JSearch timeouts are usually transient
        execution_timeout=timedelta(minutes=20),
    )
    clean_jobs = BashOperator(
        task_id="clean_jobs",
        bash_command=f"{PYTHON} -m src.processing.clean_jobs",
        cwd=str(REPO),
        execution_timeout=timedelta(minutes=30),
    )
    extract_skills = BashOperator(
        task_id="extract_skills",
        bash_command=f"{PYTHON} -m src.processing.extract_skills",
        cwd=str(REPO),
        execution_timeout=timedelta(minutes=30),
    )
    load_postgres = BashOperator(
        task_id="load_postgres",
        bash_command=f"{PYTHON} -m src.processing.load_postgres",
        cwd=str(REPO),
        execution_timeout=timedelta(minutes=20),
    )
    dbt_source_freshness = BashOperator(
        task_id="dbt_source_freshness",
        bash_command=f"{DBT} source freshness {DBT_DIRS}",  # warns only (sources.yml)
        cwd=str(REPO),
        execution_timeout=timedelta(minutes=15),
    )
    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=f"{DBT} build {DBT_DIRS}",
        cwd=str(REPO),
        execution_timeout=timedelta(minutes=15),
    )

    fetch_jobs >> clean_jobs >> extract_skills >> load_postgres >> dbt_source_freshness >> dbt_build
