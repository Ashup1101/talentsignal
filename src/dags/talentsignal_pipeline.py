"""Daily TalentSignal pipeline: JSearch → S3 raw → Spark (Delta) → RDS → NLP → dbt → ML.

fetch_jobs → clean_jobs → extract_skills → load_postgres → nlp_enrich
    → dbt_source_freshness → dbt_build → (train_salary_model, forecast_demand)

nlp_enrich (years of experience, embeddings, topics) runs before dbt because dbt
reads its ml.* tables. The two models both read dbt marts but not each other, so
both follow dbt_build directly: a failed salary run (e.g. Databricks down) doesn't
block the forecast. Each task is its own process, which also keeps PyTorch
(nlp_enrich) and XGBoost (train_salary_model) apart (OpenMP clash, CLAUDE.md 5.6).

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
    description="Daily: fetch → clean → skills → load RDS → NLP → dbt → salary model + demand forecast",
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
    nlp_enrich = BashOperator(
        task_id="nlp_enrich",
        bash_command=f"{PYTHON} -m src.ml.nlp_pipeline",
        cwd=str(REPO),
        execution_timeout=timedelta(minutes=45),  # ~1 min awake; embeddings are the slow part
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

    train_salary_model = BashOperator(
        task_id="train_salary_model",
        bash_command=f"{PYTHON} -m src.ml.salary_model",  # logs to MLflow (Databricks), then exports to S3
        cwd=str(REPO),
        execution_timeout=timedelta(minutes=30),
    )
    forecast_demand = BashOperator(
        task_id="forecast_demand",
        bash_command=f"{PYTHON} -m src.ml.demand_forecast",
        cwd=str(REPO),
        # Seconds today (no series passes the gate); ~20 min once all ~390 series forecast + backtest.
        execution_timeout=timedelta(minutes=45),
    )

    (
        fetch_jobs
        >> clean_jobs
        >> extract_skills
        >> load_postgres
        >> nlp_enrich
        >> dbt_source_freshness
        >> dbt_build
        >> [train_salary_model, forecast_demand]
    )
