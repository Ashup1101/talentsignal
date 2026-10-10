"""Smoke tests for the Phase 5 ML environment: each library works on tiny data.

Skipped where the ML libraries aren't installed (the CI pytest job); they run in
the `ml` CI job and locally after `pip-sync requirements-ml.txt`.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys

import pytest

_ML_MODULES = ("torch", "xgboost", "spacy", "sentence_transformers", "bertopic", "prophet", "mlflow", "pdfplumber")
if any(importlib.util.find_spec(m) is None for m in _ML_MODULES):
    pytest.skip("ML libraries aren't installed here (see requirements-ml.txt)", allow_module_level=True)

import numpy as np  # noqa: E402

_XGB_FIT = (
    "import numpy as np, xgboost; "
    "X = np.random.default_rng(0).normal(size=(200, 3)); y = X @ [3.0, -2.0, 1.0]; "
    "xgboost.XGBRegressor(n_estimators=5).fit(X, y)"
)


def test_xgboost_trains_on_tiny_data() -> None:
    import xgboost

    X = np.random.default_rng(0).normal(size=(200, 3))
    y = X @ [3.0, -2.0, 1.0]
    model = xgboost.XGBRegressor(n_estimators=20).fit(X, y)

    assert np.corrcoef(model.predict(X), y)[0, 1] > 0.9


def test_torch_computes_on_cpu() -> None:
    import torch

    assert torch.ones(3).sum().item() == 3.0


def test_xgboost_after_torch_in_one_process_does_not_crash() -> None:
    # Regression test for the OpenMP clash (PyTorch's bundled runtime vs XGBoost's).
    # Run in a child process so a segfault fails this test instead of the whole run.
    env = {**os.environ, "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS", "1")}
    result = subprocess.run(
        [sys.executable, "-c", f"import torch; {_XGB_FIT}; print('ok')"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, f"exit {result.returncode}: {result.stderr[-500:]}"


def test_spacy_tokenizer_treats_number_words_as_numbers() -> None:
    # The 5.1 years-of-experience matcher relies on this ("four years", "5+ years").
    import spacy

    tokens = spacy.blank("en")("four years or 5+ yrs")

    assert [t.like_num for t in tokens] == [True, False, False, True, False, False]
