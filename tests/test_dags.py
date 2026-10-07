"""Tests for the Airflow DAGs in src/dags.

These need Airflow, which lives in its own environment (.venv-airflow locally, the
`dags` CI job); where Airflow isn't installed (the pipeline's .venv) this file is
skipped. DAGs are only parsed (DagBag.dags), never looked up in Airflow's database,
and AIRFLOW_HOME points at a throwaway folder, so these tests can't touch a running
local Airflow or create ~/airflow.
"""

from __future__ import annotations

import atexit
import importlib.util
import os
import shutil
import tempfile
from pathlib import Path

import pytest

if importlib.util.find_spec("airflow") is None:
    pytest.skip(
        "Airflow isn't installed here; run with .venv-airflow/bin/pytest (or the `dags` CI job)",
        allow_module_level=True,
    )

# Airflow reads its configuration when it is imported, so set these first.
_AIRFLOW_HOME = tempfile.mkdtemp(prefix="airflow-test-")
atexit.register(shutil.rmtree, _AIRFLOW_HOME, ignore_errors=True)
os.environ["AIRFLOW_HOME"] = _AIRFLOW_HOME
os.environ["AIRFLOW__CORE__LOAD_EXAMPLES"] = "False"

from airflow.dag_processing.dagbag import DagBag  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DAGS_DIR = REPO / "src" / "dags"

PIPELINE_ORDER = [
    "fetch_jobs",
    "clean_jobs",
    "extract_skills",
    "load_postgres",
    "dbt_source_freshness",
    "dbt_build",
]
BLS_ORDER = ["fetch_bls", "clean_bls"]


@pytest.fixture(scope="module")
def dagbag() -> DagBag:
    return DagBag(dag_folder=str(DAGS_DIR))


def test_dag_files_import_without_errors(dagbag: DagBag) -> None:
    assert dagbag.import_errors == {}


def test_exactly_the_expected_dags_exist(dagbag: DagBag) -> None:
    assert sorted(dagbag.dags) == ["talentsignal_bls", "talentsignal_pipeline"]


@pytest.mark.parametrize(
    ("dag_id", "order"),
    [("talentsignal_pipeline", PIPELINE_ORDER), ("talentsignal_bls", BLS_ORDER)],
)
def test_tasks_form_one_chain_in_the_specified_order(dagbag: DagBag, dag_id: str, order: list[str]) -> None:
    dag = dagbag.dags[dag_id]

    assert sorted(dag.task_ids) == sorted(order)
    assert dag.get_task(order[0]).upstream_task_ids == set()
    for upstream, downstream in zip(order, order[1:]):
        assert dag.get_task(downstream).upstream_task_ids == {upstream}, downstream


@pytest.mark.parametrize(
    ("dag_id", "cron"),
    [("talentsignal_pipeline", "0 22 * * *"), ("talentsignal_bls", "0 0 1 * *")],
)
def test_schedule_and_safety_settings(dagbag: DagBag, dag_id: str, cron: str) -> None:
    dag = dagbag.dags[dag_id]

    assert dag.timetable.expression == cron
    assert getattr(dag.timetable.timezone, "name", str(dag.timetable.timezone)) == "UTC"
    assert dag.catchup is False
    assert dag.max_active_runs == 1
    # Nothing runs (or spends JSearch quota) until someone switches the DAG on.
    assert dag.is_paused_upon_creation is True


def test_every_task_has_a_timeout_and_runs_in_the_repo_venv(dagbag: DagBag) -> None:
    for dag in dagbag.dags.values():
        for task in dag.tasks:
            where = f"{dag.dag_id}.{task.task_id}"
            assert task.execution_timeout is not None, where
            assert task.cwd == str(REPO), where
            assert f"{REPO}/.venv/bin/" in task.bash_command, where


def test_fetch_jobs_gets_the_run_date_and_extra_retries(dagbag: DagBag) -> None:
    task = dagbag.dags["talentsignal_pipeline"].get_task("fetch_jobs")

    assert "--run-date {{ (logical_date or dag_run.run_after).strftime('%Y-%m-%d') }}" in task.bash_command
    assert task.retries == 2
