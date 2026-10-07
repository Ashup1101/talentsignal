#!/usr/bin/env bash
# Start Airflow locally with `airflow standalone`: one command that runs the
# api-server (UI on http://localhost:8080), scheduler, dag-processor and
# triggerer. Ctrl+C stops everything. Run infra/airflow/install.sh first.
#
#   infra/airflow/run_local.sh
#
# Settings are passed as AIRFLOW__<SECTION>__<KEY> environment variables so they
# live in git rather than in the git-ignored .airflow/airflow.cfg.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# `airflow standalone` launches each component as a new `airflow …` process found
# via PATH, so Airflow's virtualenv must come first on it.
export PATH="${REPO_ROOT}/.venv-airflow/bin:${PATH}"

export AIRFLOW_HOME="${REPO_ROOT}/.airflow"            # config, logs, SQLite metadata DB
export AIRFLOW__CORE__DAGS_FOLDER="${REPO_ROOT}/src/dags"
export AIRFLOW__CORE__LOAD_EXAMPLES=False
export AIRFLOW__CORE__EXECUTOR=LocalExecutor
# Serve the UI/API on this Mac only (default 0.0.0.0 = reachable from the whole network).
export AIRFLOW__API__HOST=127.0.0.1

# Spark tasks need Java 17 even if this shell didn't load ~/.zshrc.
export JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}"

# macOS: task processes are forked, and forked processes can crash in the
# Objective-C runtime or hang on system proxy lookups without these.
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export no_proxy="*"

exec airflow standalone
