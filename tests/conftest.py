"""Shared pytest setup, loaded before any test module."""

import os

# PyTorch bundles its own OpenMP runtime, while XGBoost on macOS uses Homebrew's
# libomp. With both loaded in one process, multi-threaded XGBoost crashes
# (segfault). The pipeline keeps them in separate processes; tests run everything
# in one, on tiny data, so single-threaded OpenMP costs nothing and avoids it.
os.environ.setdefault("OMP_NUM_THREADS", "1")
