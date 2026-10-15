# syntax=docker/dockerfile:1
# The TalentSignal API (FastAPI, Phase 6). Build from the repo root:
#   docker build -f infra/docker/api.Dockerfile -t talentsignal-api .
# Only the files listed in api.Dockerfile.dockerignore reach the build (never .env).

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Non-negotiable: PyTorch (resume embeddings) and XGBoost (salary) each bring an
    # OpenMP runtime, and multi-threaded OpenMP in one process segfaults (exit 139).
    # src/api/__init__.py sets it too; the image must not depend on import order.
    OMP_NUM_THREADS=1 \
    HF_HOME=/opt/hf

WORKDIR /app

# XGBoost's Linux wheel links the system OpenMP library (PyTorch bundles its own).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# CPU-only PyTorch first (the PyPI wheel pulls ~1.5 GB of NVIDIA libraries), then the
# server lock with --no-deps: the packages the CI "API tests (server lock)" job installs.
# torch's own dependencies are in the lock, so it goes in with --no-deps too.
COPY requirements-app.txt .
RUN pip install --no-deps "torch==$(grep -E '^torch==' requirements-app.txt | cut -d= -f3)" \
        --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-deps -r requirements-app.txt

# The embedding model (all-MiniLM-L6-v2 at its pinned revision) is baked in at build
# time, so the server never calls Hugging Face (anonymous rate limit) and starts offline.
COPY src/ml/artifacts.py src/ml/embeddings.py src/ml/
RUN python -c "from src.ml.embeddings import load_model; load_model()"
ENV HF_HUB_OFFLINE=1

COPY src/ src/

RUN useradd --system --uid 10001 --create-home app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --start-interval=2s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

# One worker: the 2 GB server holds one copy of PyTorch + the models. nginx (the only
# client, on the compose network) sets the forwarded headers.
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
