#!/usr/bin/env bash
# Run the TalentSignal API on this laptop: http://localhost:8000/api/docs
#
# Reads .env (RDS as the read-only app_reader, S3 with your AWS keys). Allows the
# Next.js dev server (http://localhost:3000 or 127.0.0.1:3000) to call it. Stop with Ctrl+C.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

export PYTHONPATH="${REPO_ROOT}"
export OMP_NUM_THREADS=1   # PyTorch + XGBoost in one process (also pinned in src/api/__init__.py)
export APP_CORS_ORIGINS="${APP_CORS_ORIGINS:-http://localhost:3000,http://127.0.0.1:3000}"

exec .venv/bin/uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --env-file .env
