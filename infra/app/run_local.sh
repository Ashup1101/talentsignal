#!/usr/bin/env bash
# Run the TalentSignal Streamlit app on this laptop: http://localhost:8501
#
# Reads .env: RDS as the read-only app_reader, S3 with your AWS keys. Uploaded
# resumes stay in memory. Stop with Ctrl+C.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"                     # .streamlit/config.toml is read from here

export PYTHONPATH="${REPO_ROOT}"      # the pages import src.*
export OMP_NUM_THREADS=1              # PyTorch + XGBoost in one process (also pinned in src/app)

exec .venv/bin/streamlit run src/app/streamlit_app.py --server.address 127.0.0.1 --server.port 8501
