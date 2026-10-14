"""Tests for src/ml/salary_model.py on synthetic salaries with a known structure.

Salary = role base × 1.5 if senior × 1.3 with "Spark" × noise, so the model should
find Spark's effect and beat the medians. Skipped where XGBoost/MLflow aren't
installed (the CI pytest job); runs in the `ml` job.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("xgboost")
pytest.importorskip("mlflow")

from src.app import serving  # noqa: E402
from src.ml import salary_model  # noqa: E402
from src.ml.features import Profile  # noqa: E402
from src.ml.salary_model import MedianBaseline, TrainingRow  # noqa: E402


def _rows(n: int = 200) -> list[TrainingRow]:
    rng = np.random.default_rng(0)
    rows = []
    for i in range(n):
        role = ["data engineer", "data analyst"][i % 2]
        senior = rng.random() < 0.5
        skills = {s for s in ("Spark", "SQL", "Excel") if rng.random() < 0.5}
        salary = {"data engineer": 150_000, "data analyst": 90_000}[role]
        salary *= (1.5 if senior else 1.0) * (1.3 if "Spark" in skills else 1.0) * rng.lognormal(0, 0.05)
        profile = Profile(role, "senior" if senior else "junior", "NY", False, frozenset(skills))
        rows.append(TrainingRow(f"job{i}", f"employer{i // 4}", float(salary), profile))
    return rows


@pytest.fixture(scope="module")
def rows() -> list[TrainingRow]:
    return _rows()


def test_baseline_falls_back_from_small_groups() -> None:
    p = Profile("data engineer", "senior", None, False, frozenset())
    rows = [
        TrainingRow("a", "e", 100.0, p),
        TrainingRow("b", "e", 200.0, p),  # 2 senior DEs < MIN_GROUP_SALARIES
        TrainingRow("c", "e", 50.0, Profile("data analyst", "junior", None, False, frozenset())),
    ]

    baseline = MedianBaseline.fit(rows)

    assert baseline.predict(p, "global_median") == 100.0
    assert baseline.predict(p, "role_median") == 150.0
    assert baseline.predict(p, "role_seniority_median") == 150.0  # fell back to the role
    assert baseline.predict(Profile("chef", "senior", None, False, frozenset()), "role_median") == 100.0


def test_cross_validation_scores_every_row_and_model_beats_medians(rows: list[TrainingRow]) -> None:
    cv = salary_model.cross_validate(rows)

    assert len(cv.best_trees) == salary_model.N_FOLDS
    assert all((cv.predictions[m] > 0).all() for m in salary_model.METHODS)
    assert cv.mae("model") < cv.mae("role_seniority_median") < cv.mae("global_median")


def test_skill_impact_finds_the_planted_effect(rows: list[TrainingRow]) -> None:
    model, spec = salary_model.train_final(rows, n_trees=300)
    profile = Profile("data engineer", "senior", "NY", False, frozenset({"SQL"}))

    impact = serving.skill_impact(model, spec, profile, ["Spark", "SQL", "Excel"])

    assert list(impact) == ["Spark", "Excel"]  # SQL is already there; largest first
    assert impact["Spark"] > 30_000  # planted: +30% of a $225K senior salary
    assert abs(impact["Excel"]) < impact["Spark"] / 3


def test_what_if_skills_need_enough_postings_in_the_role(rows: list[TrainingRow]) -> None:
    extra = rows + [
        TrainingRow("x", "e", 1.0, Profile("data analyst", "junior", "NY", False, frozenset({"Rust"})))
    ] * 10
    _, spec = salary_model.train_final(extra, n_trees=10)

    eligible = salary_model.what_if_skills(extra, spec)

    assert "Rust" in eligible["data analyst"] and "Rust" not in eligible["data engineer"]


def test_mlflow_logging_records_run_metrics_and_model(
    rows: list[TrainingRow], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import mlflow

    # A throwaway local store (the real runs go to Databricks).
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", tmp_path.as_uri())
    monkeypatch.setenv("MLFLOW_EXPERIMENT_NAME", "salary-test")
    model, spec = salary_model.train_final(rows, n_trees=20)

    run_id = salary_model._log_to_mlflow(model, spec, {"mae_model": 1.5}, {"n_trees": 20}, {"use_model": True})

    run = mlflow.get_run(run_id)
    assert run.data.metrics == {"mae_model": 1.5}
    assert run.data.params == {"n_trees": "20"}
    assert run.data.tags["use_model"] == "true"
    assert json.loads((Path(run.info.artifact_uri.removeprefix("file://")) / "feature_spec.json").read_text())[
        "roles"
    ] == list(spec.roles)


def test_mlflow_requires_databricks_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "databricks")
    monkeypatch.delenv("DATABRICKS_HOST", raising=False)

    with pytest.raises(ValueError, match="DATABRICKS_HOST"):
        salary_model._log_to_mlflow(None, None, {}, {}, {"use_model": True})  # type: ignore[arg-type]


def test_export_writes_a_loadable_model_and_card(rows: list[TrainingRow], monkeypatch: pytest.MonkeyPatch) -> None:
    from xgboost import XGBRegressor

    uploads: dict[str, bytes] = {}
    monkeypatch.setattr(salary_model, "upload_bytes", lambda bucket, key, body, ctype: uploads.update({key: body}))
    model, spec = salary_model.train_final(rows, n_trees=20)

    keys = salary_model.export_to_s3("bucket", model, {"use_model": True, "feature_spec": spec.to_dict()})

    assert keys == ["models/salary/model.json", "models/salary/feature_spec.json"]
    reloaded = XGBRegressor()
    reloaded.load_model(bytearray(uploads["models/salary/model.json"]))
    profiles = [r.profile for r in rows[:5]]
    np.testing.assert_allclose(
        serving.predict_salary(reloaded, spec, profiles), serving.predict_salary(model, spec, profiles)
    )
    assert json.loads(uploads["models/salary/feature_spec.json"])["use_model"] is True


def test_salary_model_never_imports_pytorch() -> None:
    # PyTorch's OpenMP runtime + multi-threaded XGBoost in one process segfaults on macOS.
    code = "import sys, src.ml.salary_model; print('torch' in sys.modules)"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=True)

    assert result.stdout.strip() == "False"
