"""Stub data for the Streamlit page tests, shaped like src/app/data.py's results.

install() swaps every data loader (and the resume embedder) for these stubs, so the
pages run with no database, S3 or embedding model. The salary model is a tiny real
XGBoost model trained on the stub postings.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import numpy as np
import pandas as pd
import pytest
from xgboost import XGBRegressor

from src.ml.artifacts import EMBEDDING_MODEL_REVISION
from src.ml.features import Profile, build_features, fit_spec

ROLES = ["data analyst", "data engineer", "data scientist", "machine learning engineer", "software engineer"]
BASE_SALARY = {"data analyst": 90_000, "data engineer": 150_000, "data scientist": 140_000,
               "machine learning engineer": 170_000, "software engineer": 160_000}
SKILLS = ["SQL", "Python", "Spark", "Airflow", "AWS", "Excel", "Tableau", "Docker"]
LEVELS = ["junior", "mid", "senior", "staff_plus"]
NOW = datetime.now(timezone.utc)


@lru_cache(maxsize=1)
def _postings() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows = []
    for r, role in enumerate(ROLES):
        for i in range(12):
            skills = tuple(sorted(s for s in SKILLS if rng.random() < 0.45))
            level = LEVELS[i % len(LEVELS)]
            salary = BASE_SALARY[role] * (1 + 0.15 * LEVELS.index(level)) if i % 6 else None
            rows.append(
                {
                    "job_id": f"{r}-{i}", "role_name": role, "job_title": f"{role.title()} {i}",
                    "employer_name": f"Employer {i % 5}", "city": "New York", "state_code": ("NY", "CA", None)[i % 3],
                    "location_name": "New York, NY", "is_remote": i % 4 == 0,
                    "posted_date": (NOW - timedelta(days=3)).date(),
                    # Data engineers were collected this week; the other roles 10 days ago.
                    "fetched_at": NOW - timedelta(days=1 if role == "data engineer" else 10),
                    "seniority_effective": level, "seniority_source": "title",
                    "experience_years_min": 3.0, "experience_years_max": None,
                    "salary_min_annual": None, "salary_mid_annual": salary, "salary_max_annual": None,
                    "has_salary": salary is not None, "skill_count": len(skills), "skills": skills,
                    "topic_id": (0, 1, -1)[i % 3],
                    "topic_label": ("data pipelines, spark", "dashboards, reporting", "unassigned")[i % 3],
                    "apply_link": f"https://jobs.example/{r}-{i}",
                }
            )
    return pd.DataFrame(rows)


def _skill_demand() -> pd.DataFrame:
    postings = _postings()
    rows = []
    for role in ROLES:
        role_rows = postings[postings["role_name"] == role]
        counts = {s: int(role_rows["skills"].map(lambda sk, s=s: s in sk).sum()) for s in SKILLS}
        for rank, (skill, n) in enumerate(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])), start=1):
            rows.append(
                {
                    "role_name": role, "skill_name": skill, "skill_category": "language",
                    "n_role_postings": len(role_rows), "n_postings_with_skill": n,
                    "share_of_role_postings": n / len(role_rows), "demand_rank": rank,
                    "n_salaried_with_skill": 6, "n_salaried_without_skill": 6,
                    "salary_sample_status": "ok" if rank % 2 else "too_few_to_report",
                    "median_salary_difference": 12_000.0 if rank % 2 else None,
                }
            )
    return pd.DataFrame(rows)


def _salary_bands() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "role_name": ROLES,
            "bls_median_annual_wage": [None, 135_000.0, 112_000.0, 112_000.0, 133_000.0],
        }
    )


def _job_insights() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "topic_id": [-1, 0, 1],
            "topic_label": ["unassigned", "data pipelines, spark", "dashboards, reporting"],
            "n_postings": [20, 20, 20],
            "share_of_postings": [1 / 3, 1 / 3, 1 / 3],
            "top_words": [[], ["data", "pipelines", "spark"], ["dashboards", "reporting"]],
        }
    )


def _forecast(forecasting: bool) -> pd.DataFrame:
    rows = [
        {"search_role": role, "skill_name": skill, "forecast_status": "insufficient_history", "observed_weeks": 2,
         "last_observed_week": (NOW - timedelta(days=7)).date(), "last_observed_share": 0.4, "forecast_week": None,
         "share_forecast": None, "share_lower": None, "share_upper": None}
        for role in ROLES for skill in SKILLS
    ]
    if forecasting:  # data engineer / SQL has a full year: 13 weekly forecasts
        rows = [r for r in rows if not (r["search_role"] == "data engineer" and r["skill_name"] == "SQL")]
        last = NOW.date()
        rows += [
            {"search_role": "data engineer", "skill_name": "SQL", "forecast_status": "forecast", "observed_weeks": 14,
             "last_observed_week": last, "last_observed_share": 0.7, "forecast_week": last + timedelta(weeks=k),
             "share_forecast": 0.7 + 0.01 * k, "share_lower": 0.6, "share_upper": 0.9}
            for k in range(1, 14)
        ]
    return pd.DataFrame(rows)


def _history() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"collection_week": NOW.date() - timedelta(weeks=k), "search_role": "data engineer", "skill_name": "SQL",
             "share_of_role_postings": 0.7 - 0.005 * k}
            for k in range(14)
        ]
    )


@lru_cache(maxsize=1)
def _model() -> tuple[dict, dict]:
    postings = _postings()
    salaried = postings[postings["salary_mid_annual"].notna()]
    profiles = [
        # pandas turns a missing state into NaN; training data (psycopg2) has None.
        Profile(r.role_name, r.seniority_effective, r.state_code if isinstance(r.state_code, str) else None,
                bool(r.is_remote), frozenset(r.skills))
        for r in salaried.itertuples()
    ]
    spec = fit_spec(profiles)
    model = XGBRegressor(n_estimators=30, max_depth=2, random_state=0)
    model.fit(build_features(profiles, spec), np.log(salaried["salary_mid_annual"].astype(float)))
    card = {
        "use_model": True,
        "feature_spec": spec.to_dict(),
        "what_if_skills": {role: list(spec.skills) for role in ROLES},
        "baselines": {"role_median": {role: float(BASE_SALARY[role]) for role in ROLES}},
        "cv_mae": {"mae_model": 30_000.0, "mae_role_median": 40_000.0},
        "mlflow_run_id": "stub-run",
        "trained_at": NOW.isoformat(),
    }
    return card, json.loads(model.get_booster().save_raw("json"))


def _embeddings() -> pd.DataFrame:
    postings = _postings()
    rng = np.random.default_rng(1)
    vectors = rng.normal(size=(len(postings), 3)).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    frame = pd.DataFrame({"job_id": postings["job_id"], "n_chunks": 1, "embedding": list(vectors)})
    frame.attrs = {"model_revision": EMBEDDING_MODEL_REVISION}
    return frame


def install(monkeypatch: pytest.MonkeyPatch, *, forecasting: bool = False) -> None:
    """Point every page's data at the stubs (copies, so a page can't change them)."""
    from src.app import data, ui
    from src.ml import embeddings

    card, model_json = _model()
    stubs = {
        "postings": _postings, "skill_demand": _skill_demand, "salary_bands": _salary_bands,
        "job_insights": _job_insights, "skill_demand_history": _history,
        "skill_demand_forecast": lambda: _forecast(forecasting), "posting_embeddings": _embeddings,
        "salary_model_card": lambda: card, "salary_model_json": lambda: model_json,
    }
    for name, func in stubs.items():
        monkeypatch.setattr(data, name, lambda func=func: _copy(func()))
    monkeypatch.setattr(embeddings, "embed_texts", lambda texts: np.array([[1.0, 0.0, 0.0]], dtype=np.float32))
    ui.salary_model.clear()


def _copy(value: object) -> object:
    if isinstance(value, pd.DataFrame):
        copied = value.copy()
        copied.attrs = dict(value.attrs)
        return copied
    return json.loads(json.dumps(value)) if isinstance(value, dict) else value
