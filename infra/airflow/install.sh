#!/usr/bin/env bash
# Create .venv-airflow (git-ignored) and install Airflow 3 with its official
# constraints file. Airflow lives in its own virtualenv because its pinned
# libraries conflict with the pipeline's (.venv). Safe to re-run.
#
#   infra/airflow/install.sh
set -euo pipefail

AIRFLOW_VERSION="3.3.1"
PYTHON_VERSION="3.11"
CONSTRAINTS="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${REPO_ROOT}/.venv-airflow"
PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/opt/python@${PYTHON_VERSION}/bin/python${PYTHON_VERSION}}"

echo "Creating ${VENV} with ${PYTHON_BIN}"
"${PYTHON_BIN}" -m venv "${VENV}"
"${VENV}/bin/pip" install --quiet --upgrade pip

echo "Installing apache-airflow ${AIRFLOW_VERSION} (constraints: ${CONSTRAINTS})"
# pytest: tests/test_dags.py needs Airflow, so it runs with this environment's Python.
"${VENV}/bin/pip" install --quiet \
  "apache-airflow==${AIRFLOW_VERSION}" \
  apache-airflow-providers-standard \
  apache-airflow-providers-databricks \
  pytest \
  --constraint "${CONSTRAINTS}"

# Point AIRFLOW_HOME at the repo so this first airflow command doesn't create ~/airflow.
export AIRFLOW_HOME="${REPO_ROOT}/.airflow"
echo "Airflow $("${VENV}/bin/airflow" version)"
"${VENV}/bin/pip" list 2>/dev/null | grep -E "^apache-airflow-providers-(standard|databricks) "
