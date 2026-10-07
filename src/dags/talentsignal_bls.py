"""Monthly BLS refresh: OEWS national estimates → S3 raw → Delta (bls_occupations).

fetch_bls → clean_bls

BLS publishes once a year, so monthly is plenty. There is no load step here: the
daily talentsignal_pipeline's load_postgres task copies the latest
delta/bls_occupations into RDS the same evening.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

REPO = Path(__file__).resolve().parents[2]
PYTHON = f"{REPO}/.venv/bin/python"

with DAG(
    dag_id="talentsignal_bls",
    description="Monthly: BLS OEWS national estimates → S3 raw → Delta",
    schedule="0 0 1 * *",  # 00:00 UTC on the 1st of each month
    start_date=pendulum.datetime(2026, 10, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=True,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=15)},
    tags=["talentsignal"],
    doc_md=__doc__,
) as dag:
    fetch_bls = BashOperator(
        task_id="fetch_bls",
        bash_command=f"{PYTHON} -m src.ingestion.fetch_bls",
        cwd=str(REPO),
        execution_timeout=timedelta(minutes=15),
    )
    clean_bls = BashOperator(
        task_id="clean_bls",
        bash_command=f"{PYTHON} -m src.processing.clean_bls",
        cwd=str(REPO),
        execution_timeout=timedelta(minutes=30),
    )

    fetch_bls >> clean_bls
