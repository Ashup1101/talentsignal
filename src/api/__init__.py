"""The app's Python API (Phase 6): FastAPI over the dbt marts, ml.* and the Phase 5 models.

PyTorch (resume embeddings) and XGBoost (salary) each bring an OpenMP runtime; in
one process, multi-threaded OpenMP crashes (segfault, exit 139 — measured on macOS
2026-10-14 even with XGBoost single-threaded: the crash is in PyTorch's threads).
OpenMP reads OMP_NUM_THREADS once, when it starts, so it is pinned here, before
any app module imports either library. One resume at a time needs no more: a
2-page resume embeds in ~0.25 s on one thread. The Docker image sets it too.
"""

import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
