"""Salary-model serving: load the exported model, predict, what-if (Phase 6 step 3).

Moved out of src/ml/salary_model.py so the app never imports MLflow: only XGBoost
(its XGBRegressor brings scikit-learn), pandas and the shared feature builder.
Training still lives in salary_model.py.

The app process also loads PyTorch (resume embeddings). PyTorch's OpenMP runtime and
multi-threaded XGBoost crash together (CLAUDE.md 5.6), so the served model predicts
on one thread; single resumes don't need more.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace

import numpy as np
from xgboost import XGBRegressor

from src.ml.features import FeatureSpec, Profile, build_features


def load_model(model_json: dict) -> XGBRegressor:
    """Rebuild the trained salary model from its exported JSON, single-threaded.

    Args:
        model_json: The parsed model.json from the S3 curated bucket.

    Returns:
        A model that predicts log(salary).
    """
    model = XGBRegressor()
    model.load_model(bytearray(json.dumps(model_json).encode()))
    model.set_params(n_jobs=1)
    return model


def predict_salary(model: XGBRegressor, spec: FeatureSpec, profiles: Sequence[Profile]) -> np.ndarray:
    """Predict annual salaries in dollars.

    Args:
        model: Trained model (predicts log salary).
        spec: Its feature spec.
        profiles: Postings or resumes.

    Returns:
        Dollars, one per profile.
    """
    return np.exp(model.predict(build_features(profiles, spec)))


def skill_impact(
    model: XGBRegressor, spec: FeatureSpec, profile: Profile, candidates: Sequence[str]
) -> dict[str, float]:
    """Model what-if: the predicted salary change if the profile also had each skill.

    An association learned from postings, not a causal effect: the UI must say
    "associated with".

    Args:
        model: Trained model.
        spec: Its feature spec.
        profile: The resume (or posting) as it is.
        candidates: Skills to try (e.g. the card's what_if_skills[role]); ones the
            profile already has are skipped.

    Returns:
        skill → dollars (with skill − without), largest first.
    """
    missing = [s for s in candidates if s not in profile.skills]
    if not missing:
        return {}
    variants = [replace(profile, skills=profile.skills | {s}) for s in missing]
    salaries = predict_salary(model, spec, [profile, *variants])
    deltas = {s: float(v - salaries[0]) for s, v in zip(missing, salaries[1:], strict=True)}
    return dict(sorted(deltas.items(), key=lambda kv: kv[1], reverse=True))
