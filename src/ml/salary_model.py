"""XGBoost salary model with MLflow tracking (Phase 5.2).

Predicts a posting's annual salary (midpoint of its posted range) from what a
resume can provide (src/ml/features.py). Trained on log(salary): salaries are
skewed ($69K–$450K) and errors are proportional; every error is reported in
dollars.

Honest evaluation with ~270 salaried postings:
- 5-fold cross-validation grouped by employer, so one employer's near-identical
  postings never sit on both sides of a split;
- three median baselines computed inside the same folds: global, per role, and
  per role × seniority;
- the app uses the model only if it beats the per-role median; otherwise it
  falls back to the baseline and says so (use_model in the exported spec).

Run locally:  python -m src.ml.salary_model
Never import PyTorch / sentence-transformers here (OpenMP clash, CLAUDE.md 5.6).
"""

from __future__ import annotations

import json
import logging
import sys
from collections import defaultdict
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from statistics import median

import mlflow
import numpy as np
from dotenv import load_dotenv
from sklearn.model_selection import GroupKFold, GroupShuffleSplit
from xgboost import XGBRegressor

from src.ingestion.s3_utils import require_env, upload_bytes
from src.ml.features import FeatureSpec, Profile, build_features, fit_spec
from src.processing.postgres import PostgresConfig

logger = logging.getLogger(__name__)

RANDOM_STATE = 42
N_FOLDS = 5
EARLY_STOPPING_SHARE = 0.2  # of each training fold, held out to pick the number of trees
EARLY_STOPPING_ROUNDS = 50
# Shallow, slow-learning trees: ~270 rows can't support deep interactions.
XGB_PARAMS = {
    "max_depth": 3,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 3,
    "reg_lambda": 1.0,
    "objective": "reg:squarederror",
    "random_state": RANDOM_STATE,
}
MAX_TREES = 2000
# A role × seniority median needs this many training salaries; otherwise the role median.
MIN_GROUP_SALARIES = 3
# What-if impact is offered only for skills this many salaried postings of the role
# mention (the same floor as mart_skill_salary_by_role).
MIN_WHAT_IF_POSTINGS = 5
METHODS = ("model", "global_median", "role_median", "role_seniority_median")
MODEL_PREFIX = "models/salary"


@dataclass(frozen=True)
class TrainingRow:
    """One salaried posting: its features, its salary and its employer (the CV group)."""

    job_id: str
    employer: str
    salary: float
    profile: Profile


@dataclass(frozen=True)
class MedianBaseline:
    """Median salaries by group, fitted on training rows; falls back to coarser groups."""

    global_median: float
    by_role: dict[str, float]
    by_role_seniority: dict[str, float]  # key "role|seniority"

    @classmethod
    def fit(cls, rows: Sequence[TrainingRow]) -> MedianBaseline:
        """Compute the medians from training rows.

        Args:
            rows: Training rows.

        Returns:
            The fitted baseline.
        """
        by_role: dict[str, list[float]] = defaultdict(list)
        by_group: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            by_role[r.profile.role].append(r.salary)
            by_group[f"{r.profile.role}|{r.profile.seniority}"].append(r.salary)
        return cls(
            global_median=median(r.salary for r in rows),
            by_role={k: median(v) for k, v in by_role.items()},
            by_role_seniority={k: median(v) for k, v in by_group.items() if len(v) >= MIN_GROUP_SALARIES},
        )

    def predict(self, profile: Profile, level: str) -> float:
        """Predict one salary at a given level, falling back when a group is missing.

        Args:
            profile: The posting or resume.
            level: 'global_median', 'role_median' or 'role_seniority_median'.

        Returns:
            Salary in dollars.
        """
        role = self.by_role.get(profile.role, self.global_median)
        if level == "global_median":
            return self.global_median
        if level == "role_median":
            return role
        return self.by_role_seniority.get(f"{profile.role}|{profile.seniority}", role)


@dataclass(frozen=True)
class CVResult:
    """Out-of-fold predictions for the model and each baseline, plus per-fold tree counts."""

    salaries: np.ndarray
    roles: list[str]
    predictions: dict[str, np.ndarray]  # method → dollars, aligned with salaries
    best_trees: list[int]

    def mae(self, method: str, role: str | None = None) -> float:
        """Mean absolute error in dollars, overall or for one role.

        Args:
            method: One of METHODS.
            role: Restrict to this role (None = all rows).

        Returns:
            MAE in dollars.
        """
        mask = np.ones(len(self.salaries), bool) if role is None else np.array([r == role for r in self.roles])
        return float(np.mean(np.abs(self.predictions[method][mask] - self.salaries[mask])))


def load_training_rows(config: PostgresConfig) -> list[TrainingRow]:
    """Read every salaried posting with its features from the dbt star schema.

    Args:
        config: Database with the dbt marts.

    Returns:
        One row per salaried posting, ordered by job_id.

    Raises:
        RuntimeError: If there are no salaried postings, or a posting's skills
            don't add up to its skill_count.
    """
    with closing(config.connect()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            select f.job_id, f.employer_name, f.salary_mid_annual, r.role_name,
                   f.seniority_effective, l.state_code, f.is_remote, f.skill_count
            from analytics_marts.fact_job_postings f
            join analytics_marts.dim_role r using (role_key)
            join analytics_marts.dim_location l using (location_key)
            where f.has_salary
            order by f.job_id
            """
        )
        postings = cur.fetchall()
        if not postings:
            raise RuntimeError("No salaried postings in analytics_marts.fact_job_postings; run dbt build")
        cur.execute(
            "select job_id, skill_name from analytics_staging.stg_skills where job_id = any(%s)",
            ([p[0] for p in postings],),
        )
        skills: dict[str, set[str]] = defaultdict(set)
        for job_id, skill in cur.fetchall():
            skills[job_id].add(skill)

    rows = []
    for job_id, employer, salary, role, seniority, state, remote, skill_count in postings:
        if len(skills[job_id]) != skill_count:
            raise RuntimeError(f"{job_id}: {len(skills[job_id])} skills but skill_count {skill_count}")
        profile = Profile(role, seniority, state, bool(remote), frozenset(skills[job_id]))
        rows.append(TrainingRow(job_id, employer or "", float(salary), profile))
    return rows


def _fit_model(features: object, log_salaries: np.ndarray, n_trees: int) -> XGBRegressor:
    return XGBRegressor(n_estimators=n_trees, **XGB_PARAMS).fit(features, log_salaries, verbose=False)


def _best_tree_count(rows: Sequence[TrainingRow], spec: FeatureSpec) -> int:
    # Hold out some employers of the training fold; stop adding trees when they stop helping.
    groups = [r.employer for r in rows]
    fit_idx, stop_idx = next(
        GroupShuffleSplit(n_splits=1, test_size=EARLY_STOPPING_SHARE, random_state=RANDOM_STATE).split(
            rows, groups=groups
        )
    )
    X = build_features([r.profile for r in rows], spec)
    y = np.log([r.salary for r in rows])
    model = XGBRegressor(n_estimators=MAX_TREES, early_stopping_rounds=EARLY_STOPPING_ROUNDS, **XGB_PARAMS)
    model.fit(X.iloc[fit_idx], y[fit_idx], eval_set=[(X.iloc[stop_idx], y[stop_idx])], verbose=False)
    return model.best_iteration + 1


def cross_validate(rows: Sequence[TrainingRow]) -> CVResult:
    """Grouped 5-fold CV: out-of-fold dollar predictions for the model and baselines.

    Each fold picks its features, tree count and medians from its training part
    only, then predicts postings of employers it has never seen.

    Args:
        rows: All salaried postings.

    Returns:
        Out-of-fold predictions and the tree count chosen in each fold.
    """
    salaries = np.array([r.salary for r in rows])
    predictions = {m: np.zeros(len(rows)) for m in METHODS}
    best_trees = []
    folds = GroupKFold(n_splits=N_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    for train_idx, test_idx in folds.split(rows, groups=[r.employer for r in rows]):
        train = [rows[i] for i in train_idx]
        test = [rows[i] for i in test_idx]
        spec = fit_spec([r.profile for r in train])
        n_trees = _best_tree_count(train, spec)
        best_trees.append(n_trees)
        model = _fit_model(build_features([r.profile for r in train], spec), np.log(salaries[train_idx]), n_trees)
        predictions["model"][test_idx] = np.exp(model.predict(build_features([r.profile for r in test], spec)))
        baseline = MedianBaseline.fit(train)
        for method in METHODS[1:]:
            predictions[method][test_idx] = [baseline.predict(r.profile, method) for r in test]
    return CVResult(salaries, [r.profile.role for r in rows], predictions, best_trees)


def train_final(rows: Sequence[TrainingRow], n_trees: int) -> tuple[XGBRegressor, FeatureSpec]:
    """Fit the production model on every salaried posting.

    Args:
        rows: All salaried postings.
        n_trees: Tree count (median of the CV folds' early-stopping choices).

    Returns:
        The model and its feature spec.
    """
    spec = fit_spec([r.profile for r in rows])
    X = build_features([r.profile for r in rows], spec)
    return _fit_model(X, np.log([r.salary for r in rows]), n_trees), spec


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


def what_if_skills(rows: Sequence[TrainingRow], spec: FeatureSpec) -> dict[str, list[str]]:
    """Skills whose what-if impact may be shown, per role.

    Args:
        rows: Salaried postings.
        spec: The model's feature spec (only feature skills can change a prediction).

    Returns:
        role → skills that are model features and appear in at least
        MIN_WHAT_IF_POSTINGS salaried postings of that role.
    """
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        for skill in r.profile.skills:
            counts[r.profile.role][skill] += 1
    return {
        role: sorted(s for s in spec.skills if counts[role][s] >= MIN_WHAT_IF_POSTINGS) for role in spec.roles
    }


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
        candidates: Skills to try (e.g. what_if_skills()[role]); ones the profile
            already has are skipped.

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


def evaluation_metrics(cv: CVResult) -> dict[str, float]:
    """Flatten CV results into MLflow-style metrics.

    Args:
        cv: Output of cross_validate.

    Returns:
        mae_<method> overall and mae_<method>__<role> per role, in dollars.
    """
    metrics = {f"mae_{m}": cv.mae(m) for m in METHODS}
    for role in sorted(set(cv.roles)):
        key = role.replace(" ", "_")
        metrics.update({f"mae_{m}__{key}": cv.mae(m, role) for m in METHODS})
    return metrics


def _log_to_mlflow(
    model: XGBRegressor, spec: FeatureSpec, metrics: dict[str, float], params: dict[str, object], card: dict
) -> str:
    tracking_uri = require_env("MLFLOW_TRACKING_URI")
    if tracking_uri == "databricks":
        require_env("DATABRICKS_HOST")
        require_env("DATABRICKS_TOKEN")
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(require_env("MLFLOW_EXPERIMENT_NAME"))
    with mlflow.start_run(run_name=f"salary-{datetime.now(timezone.utc):%Y-%m-%d}") as run:
        mlflow.log_params(params)
        mlflow.log_metrics(metrics)
        mlflow.set_tag("use_model", str(card["use_model"]).lower())
        mlflow.log_dict(spec.to_dict(), "feature_spec.json")
        mlflow.log_dict(card, "model_card.json")
        mlflow.xgboost.log_model(model, name="model")
    return run.info.run_id


def export_to_s3(bucket: str, model: XGBRegressor, card: dict) -> list[str]:
    """Write the model and its card (feature spec, baselines, metrics) for the app.

    Args:
        bucket: The S3 curated bucket.
        model: Trained model.
        card: Feature spec, baselines, what-if skills, metrics and use_model.

    Returns:
        The S3 keys written.
    """
    model_key, card_key = f"{MODEL_PREFIX}/model.json", f"{MODEL_PREFIX}/feature_spec.json"
    upload_bytes(bucket, model_key, bytes(model.get_booster().save_raw("json")), "application/json")
    upload_bytes(bucket, card_key, json.dumps(card, indent=2).encode(), "application/json")
    return [model_key, card_key]


def run(config: PostgresConfig, curated_bucket: str) -> dict:
    """Evaluate, train, log to MLflow and export the salary model.

    The S3 export happens only after MLflow logging succeeds, so every exported
    model has a tracked run.

    Args:
        config: Database with the dbt marts.
        curated_bucket: S3 bucket for the exported model.

    Returns:
        The model card that was exported.
    """
    rows = load_training_rows(config)
    cv = cross_validate(rows)
    metrics = evaluation_metrics(cv)
    for method in METHODS:
        logger.info("CV MAE %-22s $%s", method, f"{metrics[f'mae_{method}']:,.0f}")
    use_model = metrics["mae_model"] < metrics["mae_role_median"]
    logger.info("Model %s the per-role median → use_model=%s", "beats" if use_model else "does NOT beat", use_model)

    n_trees = int(median(cv.best_trees))
    model, spec = train_final(rows, n_trees)
    baseline = MedianBaseline.fit(rows)
    card = {
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_salaried_postings": len(rows),
        "n_employers": len({r.employer for r in rows}),
        "target": "log(salary_mid_annual); predictions in dollars",
        "use_model": use_model,
        "fallback": "role_median",
        "feature_spec": spec.to_dict(),
        "what_if_skills": what_if_skills(rows, spec),
        "baselines": {
            "global_median": baseline.global_median,
            "role_median": baseline.by_role,
            "role_seniority_median": baseline.by_role_seniority,
        },
        "cv_mae": {k: round(v, 2) for k, v in metrics.items()},
        "n_trees": n_trees,
    }
    params = {
        **XGB_PARAMS,
        "n_trees": n_trees,
        "cv_folds": N_FOLDS,
        "cv_grouped_by": "employer",
        "n_rows": len(rows),
        "n_features": len(spec.names),
    }
    card["mlflow_run_id"] = _log_to_mlflow(model, spec, metrics, params, card)
    keys = export_to_s3(curated_bucket, model, card)
    logger.info("MLflow run %s; exported s3://%s/{%s}", card["mlflow_run_id"], curated_bucket, ",".join(keys))
    return card


def main() -> int:
    """Command-line entry point.

    Returns:
        Process exit code.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv()
    run(PostgresConfig.from_env(), require_env("S3_CURATED_BUCKET"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
