"""Tests for src/api/logic.py and src/api/serving.py on stub data with known answers.

A tiny XGBoost model is trained on synthetic salaries where Spark adds 30%. Skipped
where XGBoost isn't installed (the CI pytest job); runs in the `ml` job.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("xgboost")

from xgboost import XGBRegressor  # noqa: E402

from src.api import logic, serving  # noqa: E402
from src.ml.artifacts import EMBEDDING_MODEL_REVISION  # noqa: E402
from src.ml.features import UNKNOWN, Profile, build_features, fit_spec  # noqa: E402

DE, DA = "data engineer", "data analyst"
NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)

DEMAND = pd.DataFrame(
    [
        # role, skill, category, share, rank, salaried with / without, status, median diff
        (DE, "SQL", "database", 0.80, 1, 40, 10, "ok", 5000.0),
        (DE, "Python", "language", 0.60, 2, 30, 20, "too_few_to_report", 99999.0),
        (DE, "Spark", "data_engineering", 0.40, 3, 20, 30, "ok", 30000.0),
        (DE, "Airflow", "data_engineering", 0.30, 4, 15, 35, "ok", None),
        (DE, "Excel", "analytics_bi", 0.05, 5, 2, 48, "too_few_to_report", None),
        (DA, "SQL", "database", 0.70, 1, 30, 10, "ok", 2000.0),
        (DA, "Excel", "analytics_bi", 0.50, 2, 20, 20, "ok", -4000.0),
    ],
    columns=[
        "role_name", "skill_name", "skill_category", "share_of_role_postings", "demand_rank",
        "n_salaried_with_skill", "n_salaried_without_skill", "salary_sample_status", "median_salary_difference",
    ],
)


@pytest.fixture(scope="module")
def trained() -> tuple[XGBRegressor, dict, dict]:
    rng = np.random.default_rng(0)
    profiles, salaries = [], []
    for i in range(240):
        role = (DE, DA)[i % 2]
        senior = rng.random() < 0.5
        skills = frozenset(s for s in ("SQL", "Python", "Spark", "Airflow", "Excel") if rng.random() < 0.5)
        profiles.append(Profile(role, "senior" if senior else "junior", "NY", False, skills))
        base = 150_000 if role == DE else 90_000
        salaries.append(base * (1.5 if senior else 1.0) * (1.3 if "Spark" in skills else 1.0) * rng.lognormal(0, 0.03))
    spec = fit_spec(profiles)
    model = XGBRegressor(n_estimators=300, max_depth=3, learning_rate=0.1, random_state=0)
    model.fit(build_features(profiles, spec), np.log(salaries))
    card = {
        "use_model": True,
        "feature_spec": spec.to_dict(),
        "what_if_skills": {DE: ["Airflow", "Python", "Spark"], DA: ["Excel"]},
        "baselines": {"role_median": {DE: 150_000.0, DA: 90_000.0}},
        "cv_mae": {"mae_model": 30_000.0, "mae_model__data_engineer": 25_000.0, "mae_role_median": 40_000.0},
        "mlflow_run_id": "run123",
    }
    return model, card, json.loads(model.get_booster().save_raw("json"))


# --- match % (D2) -----------------------------------------------------------------


def test_match_pct_is_demand_weighted_over_core_skills() -> None:
    # Core = share ≥ 10%: SQL .8, Python .6, Spark .4, Airflow .3 (Excel .05 doesn't count).
    assert logic.match_pct({"SQL", "Spark", "Excel"}, DE, DEMAND) == pytest.approx((0.8 + 0.4) / 2.1)
    assert logic.match_pct(set(), DE, DEMAND) == 0.0
    assert logic.match_pct({"SQL", "Python", "Spark", "Airflow"}, DE, DEMAND) == 1.0


def test_core_skills_lists_what_counted() -> None:
    core = logic.core_skills({"Spark"}, DE, DEMAND)

    assert core["skill_name"].tolist() == ["SQL", "Python", "Spark", "Airflow"]
    assert core["on_resume"].tolist() == [False, False, True, False]


def test_unknown_role_is_an_error() -> None:
    with pytest.raises(ValueError, match="No skill demand for role 'chef'"):
        logic.match_pct({"SQL"}, "chef", DEMAND)


# --- missing skills (D3) ----------------------------------------------------------


def test_top_missing_skills_are_the_most_in_demand_ones_lacking(trained: tuple) -> None:
    model, card, _ = trained
    spec = serving_spec(card)

    missing = logic.top_missing_skills({"SQL"}, DE, DEMAND, card, model, spec, seniority="senior", state="NY")

    assert [m["skill"] for m in missing] == ["Python", "Spark", "Airflow"]
    by_skill = {m["skill"]: m for m in missing}
    assert by_skill["Spark"]["model_impact"] > 40_000  # planted: +30% of a ~$225K senior salary
    assert by_skill["Spark"]["median_salary_difference"] == 30_000.0
    assert by_skill["Python"]["median_salary_difference"] is None  # too few salaries: hidden
    assert by_skill["Airflow"]["median_salary_difference"] is None  # no value in the mart
    assert by_skill["Spark"]["share_of_role_postings"] == 0.4 and by_skill["Spark"]["demand_rank"] == 3


def test_model_what_if_only_when_the_card_allows(trained: tuple) -> None:
    model, card, _ = trained
    spec = serving_spec(card)

    not_eligible = logic.top_missing_skills({"Excel"}, DA, DEMAND, card, model, spec, n=1)
    model_off = logic.top_missing_skills({"SQL"}, DE, DEMAND, {**card, "use_model": False}, model, spec)

    assert not_eligible[0]["skill"] == "SQL" and not_eligible[0]["model_impact"] is None  # not a what-if skill
    assert all(m["model_impact"] is None for m in model_off)


# --- salary ---------------------------------------------------------------------------


def test_salary_prediction_with_the_roles_error_range(trained: tuple) -> None:
    _, card, model_json = trained

    result = logic.predict_salary_for_resume({"SQL", "Spark"}, DE, "senior", "NY", False, card, model_json)

    assert result["method"] == "model"
    assert result["salary"] == pytest.approx(150_000 * 1.5 * 1.3, rel=0.1)
    assert result["typical_error"] == 25_000.0  # the role's own CV MAE
    assert (result["low"], result["high"]) == (result["salary"] - 25_000, result["salary"] + 25_000)
    assert result["role_median"] == 150_000.0 and result["mlflow_run_id"] == "run123"


def test_salary_falls_back_to_the_role_median(trained: tuple) -> None:
    _, card, model_json = trained

    no_model = {**card, "use_model": False}

    result = logic.predict_salary_for_resume({"SQL"}, DA, UNKNOWN, None, True, no_model, model_json)

    assert result["method"] == "role_median"
    assert (result["salary"], result["typical_error"]) == (90_000.0, 40_000.0)  # overall MAE: no DA key
    assert result["low"] == 50_000.0


def test_salary_for_an_unknown_role_is_an_error(trained: tuple) -> None:
    _, card, model_json = trained

    with pytest.raises(ValueError, match="Unknown role 'chef'"):
        logic.predict_salary_for_resume(set(), "chef", UNKNOWN, None, False, card, model_json)


def test_served_model_is_single_threaded_and_predicts_like_the_trained_one(trained: tuple) -> None:
    model, card, model_json = trained
    spec = serving_spec(card)
    profiles = [
        Profile(DE, "senior", "NY", False, frozenset({"Spark"})),
        Profile(DA, "junior", None, True, frozenset()),
    ]

    served = serving.load_model(model_json)

    assert served.get_params()["n_jobs"] == 1
    np.testing.assert_allclose(
        serving.predict_salary(served, spec, profiles), serving.predict_salary(model, spec, profiles), rtol=1e-6
    )


def serving_spec(card: dict) -> object:
    from src.ml.features import FeatureSpec

    return FeatureSpec.from_dict(card["feature_spec"])


# --- matching postings (D1) ------------------------------------------------------


def _embeddings(revision: str = EMBEDDING_MODEL_REVISION) -> pd.DataFrame:
    vectors = {"a": [1.0, 0.0, 0.0], "b": [0.6, 0.8, 0.0], "c": [0.0, 1.0, 0.0], "old": [1.0, 0.0, 0.0], "x": [1, 0, 0]}
    frame = pd.DataFrame(
        {"job_id": list(vectors), "embedding": [np.array(v, dtype=np.float32) for v in vectors.values()]}
    )
    frame.attrs = {"model_revision": revision}
    return frame


def _postings() -> pd.DataFrame:
    rows = [
        ("a", DE, NOW - timedelta(days=1), ("SQL", "Spark"), "manager"),
        ("b", DE, NOW - timedelta(days=2), ("Python",), "mid"),
        ("c", DE, NOW - timedelta(days=6), ("Excel",), "junior"),
        ("old", DE, NOW - timedelta(days=30), ("SQL",), "mid"),  # most similar, but not recent
        ("d", DE, NOW - timedelta(days=1), ("SQL",), "mid"),  # no embedding: skipped
        ("x", DA, NOW - timedelta(days=20), ("SQL",), "unknown"),
    ]
    return pd.DataFrame(
        [
            {
                "job_id": j, "role_name": r, "job_title": f"title {j}", "employer_name": "E",
                "location_name": "NY", "is_remote": False, "fetched_at": t, "salary_mid_annual": None,
                "apply_link": f"https://jobs/{j}", "skills": s, "seniority_effective": level,
            }
            for j, r, t, s, level in rows
        ]
    )


def test_recent_postings_ranked_by_cosine_similarity_with_shared_skills() -> None:
    result = logic.match_postings(
        np.array([2.0, 0.0, 0.0]), _embeddings(), _postings(), DE, resume_skills={"SQL", "Spark"}, now=NOW
    )

    assert result["job_id"].tolist() == ["a", "b", "c"]  # "old" isn't recent; "d" has no embedding
    np.testing.assert_allclose(result["similarity"], [1.0, 0.6, 0.0], atol=1e-6)  # resume vector normalised
    assert result["shared_skills"].tolist() == [("SQL", "Spark"), (), ()]
    assert result.attrs == {"window": "last_7_days", "since": (NOW - timedelta(days=6)).date()}
    assert len(logic.match_postings(np.array([1.0, 0, 0]), _embeddings(), _postings(), DE, top_n=2, now=NOW)) == 2


def test_role_without_recent_postings_uses_its_latest_collection() -> None:
    result = logic.match_postings(np.array([1.0, 0, 0]), _embeddings(), _postings(), DA, now=NOW)

    assert result["job_id"].tolist() == ["x"]
    assert result.attrs == {"window": "latest_collection", "since": (NOW - timedelta(days=20)).date()}


def test_embeddings_from_another_model_revision_are_refused() -> None:
    with pytest.raises(ValueError, match="rerun the NLP step"):
        logic.match_postings(np.array([1.0, 0, 0]), _embeddings("other"), _postings(), DE, now=NOW)


def test_role_with_no_postings_gives_an_empty_result() -> None:
    result = logic.match_postings(np.array([1.0, 0, 0]), _embeddings(), _postings(), "chef", now=NOW)

    assert result.empty and result.attrs["window"] == "none"


# --- the OpenMP crash -----------------------------------------------------------


def test_app_survives_pytorch_and_xgboost_in_one_process() -> None:
    # Regression: PyTorch + XGBoost in one process segfaulted (exit 139) on macOS
    # unless OMP_NUM_THREADS=1. src.api pins it; prove it with the variable unset.
    code = (
        "import os, numpy as np, src.api.serving, xgboost\n"
        "from src.ml.embeddings import embed_texts\n"
        "embed_texts(['Data engineer: Python, SQL, Spark pipelines on AWS. ' * 40])\n"
        "X = np.random.default_rng(0).normal(size=(300, 5))\n"
        "xgboost.XGBRegressor(n_estimators=20).fit(X, X @ np.arange(5.0)).predict(X)\n"
        "print(os.environ['OMP_NUM_THREADS'])\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "OMP_NUM_THREADS"}
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=300)

    assert result.returncode == 0, f"exit {result.returncode}: {result.stderr[-500:]}"
    assert result.stdout.strip().splitlines()[-1] == "1"


# --- Salary Explorer and Job Insights helpers -------------------------------------------


def _salaries() -> pd.DataFrame:
    rows = [(DE, "senior", "NY", 100_000.0 + 10_000 * i) for i in range(6)]  # 100K … 150K
    rows += [(DE, "junior", "CA", 80_000.0), (DA, "senior", "NY", 90_000.0), (DA, "senior", "NY", None)]
    return pd.DataFrame(rows, columns=["role_name", "seniority_effective", "state_code", "salary_mid_annual"])


BLS = pd.DataFrame({"role_name": [DE, DA], "bls_median_annual_wage": [120_000.0, None]})


def test_salary_bands_match_percentile_cont_and_compare_with_bls() -> None:
    bands = logic.salary_bands_for(_salaries(), BLS).set_index("role_name")

    de = bands.loc[DE]
    assert de["n_salaries"] == 7 and de["sample_status"] == "ok"
    assert (de["salary_p25"], de["salary_median"], de["salary_p75"]) == (105_000.0, 120_000.0, 135_000.0)
    assert de["median_vs_bls_pct"] == pytest.approx(0.0)
    assert bands.loc[DA, "sample_status"] == "too_few_to_report" and pd.isna(bands.loc[DA, "salary_median"])


def test_salary_band_filters_narrow_the_sample() -> None:
    senior_ny = logic.salary_bands_for(_salaries(), BLS, seniority="senior", state="NY").set_index("role_name")
    junior = logic.salary_bands_for(_salaries(), BLS, seniority="junior").set_index("role_name")

    assert senior_ny.loc[DE, "n_salaries"] == 6 and senior_ny.loc[DE, "salary_median"] == 125_000.0
    assert junior.loc[DE, "n_salaries"] == 1 and junior.loc[DE, "sample_status"] == "too_few_to_report"


def test_topic_role_mix_shares_each_topics_postings_across_roles() -> None:
    postings = pd.DataFrame(
        {
            "topic_id": [0, 0, 0, 1, -1, None],
            "topic_label": ["pipelines", "pipelines", "pipelines", "dashboards", "unassigned", None],
            "role_name": [DE, DE, DA, DA, DE, DE],
        }
    )

    mix = logic.topic_role_mix(postings)

    assert mix[["topic_id", "role_name", "n_postings"]].values.tolist() == [[0, DE, 2], [0, DA, 1], [1, DA, 1]]
    assert mix["share_of_topic"].round(3).tolist() == [0.667, 0.333, 1.0]


# --- The 2026-10-14 fixes -----------------------------------------------------------------


def test_postings_near_the_users_level_come_first() -> None:
    result = logic.match_postings(
        np.array([1.0, 0.0, 0.0]), _embeddings(), _postings(), DE, seniority="junior", now=NOW
    )

    # Junior: mid (b) and junior (c) are within one step; manager (a) is not, despite the best similarity.
    assert result["job_id"].tolist() == ["b", "c", "a"]
    assert result["near_level"].tolist() == [True, True, False]
    assert result["level"].tolist() == ["mid", "junior", "manager"]


def test_a_user_who_isnt_sure_of_their_level_gets_plain_similarity_order() -> None:
    result = logic.match_postings(np.array([1.0, 0.0, 0.0]), _embeddings(), _postings(), DE, seniority=UNKNOWN, now=NOW)

    assert result["job_id"].tolist() == ["a", "b", "c"] and result["near_level"].all()


def test_level_salary_is_the_posted_median_for_role_and_level() -> None:
    postings = pd.DataFrame(
        {
            "role_name": [DA] * 6 + [DE],
            "seniority_effective": ["junior"] * 5 + ["senior", "junior"],
            "salary_mid_annual": [70_000.0, 75_000.0, 79_000.0, 85_000.0, 90_000.0, 130_000.0, 150_000.0],
        }
    )

    assert logic.level_salary(postings, DA, "junior") == {"median": 79_000.0, "n": 5, "status": "ok"}
    assert logic.level_salary(postings, DA, "senior") == {"median": None, "n": 1, "status": "too_few_salaries"}
    assert logic.level_salary(postings, DA, UNKNOWN) == {"median": None, "n": 0, "status": "no_level"}


def test_median_difference_needs_ten_salaries_on_each_side(trained: tuple) -> None:
    model, card, _ = trained
    small = DEMAND.copy()
    small.loc[(small.role_name == DE) & (small.skill_name == "Spark"), "n_salaried_with_skill"] = 9

    by_skill = {m["skill"]: m for m in logic.top_missing_skills({"SQL"}, DE, small, card, model, serving_spec(card))}

    assert by_skill["Spark"]["median_salary_difference"] is None  # 9 vs 30: hidden
    assert by_skill["Spark"]["median_difference_status"] == "too_few_salaries"
    assert by_skill["Spark"]["model_impact_status"] == "value"


def test_impact_status_words_the_what_if() -> None:
    assert logic.impact_status(None) == "not_enough_data"
    assert logic.impact_status(0.0) == "no_measurable_effect"
    assert logic.impact_status(-499.0) == "no_measurable_effect"
    assert logic.impact_status(500.0) == "value" and logic.impact_status(-4_000.0) == "value"
