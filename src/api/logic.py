"""The Resume Analyzer's calculations, as plain functions (Phase 6 step 3).

The pages only display what these return, so every number on screen is unit-tested.
Inputs are the frames and dicts from src/api/data.py plus what the resume yields
(skills from the shared dictionary, an embedding from src/ml/embeddings.py).
Decisions: CLAUDE.md Phase 6 D1–D3. Salary differences are associations from
postings, never causal effects: the UI says "associated with".
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from src.api import serving
from src.ml.artifacts import EMBEDDING_MODEL_REVISION
from src.ml.features import UNKNOWN, FeatureSpec, Profile

CORE_SKILL_MIN_SHARE = 0.10  # D2: a role's skills = those in ≥ 10% of its postings
RECENT_DAYS = 7  # "this week's postings"
# Fix 3 (2026-10-14): a with/without salary difference is shown only with this many
# salaries on EACH side (the mart's floor is 5; 7-vs-66 comparisons read -$33K).
MIN_SALARIES_PER_SIDE = 10
MIN_LEVEL_SALARIES = 5  # posted median for role × level (dbt's min_salary_sample)
# A what-if under $500 would show as "$0" at the UI's $1,000 rounding.
NO_EFFECT_BELOW = 500
# Rough order of levels for "at or near your level" (manager ~ staff+).
LEVEL_RANK = {"intern": 0, "junior": 1, "mid": 2, "senior": 3, "staff_plus": 4, "manager": 4}


def core_skills(resume_skills: Iterable[str], role: str, skill_demand_df: pd.DataFrame) -> pd.DataFrame:
    """The role's core skills (in ≥ 10% of its postings), marked found / not found.

    Args:
        resume_skills: Skills found on the resume.
        role: Target role.
        skill_demand_df: data.skill_demand() (mart_role_skill_profile).

    Returns:
        skill_name, share_of_role_postings, demand_rank, on_resume — most in-demand first.

    Raises:
        ValueError: If the role has no skill-demand rows.
    """
    rows = skill_demand_df[skill_demand_df["role_name"] == role]
    if rows.empty:
        raise ValueError(f"No skill demand for role {role!r}")
    core = rows[rows["share_of_role_postings"] >= CORE_SKILL_MIN_SHARE].sort_values("demand_rank")
    found = set(resume_skills)
    core = core[["skill_name", "share_of_role_postings", "demand_rank"]].reset_index(drop=True)
    core["on_resume"] = core["skill_name"].isin(found)
    return core


def match_pct(resume_skills: Iterable[str], role: str, skill_demand_df: pd.DataFrame) -> float:
    """D2: demand-weighted share of the role's core skills that the resume has.

    E.g. core skills SQL 80%, Python 60%, Spark 40% and a resume with SQL + Spark:
    (0.8 + 0.4) / (0.8 + 0.6 + 0.4) = 0.67.

    Args:
        resume_skills: Skills found on the resume.
        role: Target role.
        skill_demand_df: data.skill_demand().

    Returns:
        A value in [0, 1].
    """
    core = core_skills(resume_skills, role, skill_demand_df)
    total = core["share_of_role_postings"].sum()
    return float(core.loc[core["on_resume"], "share_of_role_postings"].sum() / total) if total else 0.0


def _optional(value: object) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def impact_status(value: float | None) -> str:
    """How a model what-if may be shown.

    Args:
        value: Dollars from serving.skill_impact, or None when the model can't say.

    Returns:
        'not_enough_data' (None), 'no_measurable_effect' (|value| < NO_EFFECT_BELOW,
        which would read "$0" at $1,000 rounding) or 'value'.
    """
    if value is None:
        return "not_enough_data"
    return "no_measurable_effect" if abs(value) < NO_EFFECT_BELOW else "value"


def top_missing_skills(
    resume_skills: Iterable[str],
    role: str,
    skill_demand_df: pd.DataFrame,
    salary_card: dict,
    model: XGBRegressor,
    spec: FeatureSpec,
    n: int = 3,
    *,
    seniority: str = UNKNOWN,
    state: str | None = None,
    remote: bool = False,
) -> list[dict]:
    """D3: the role's most in-demand skills the resume lacks, with salary associations.

    Two salary views per skill, each only where the data supports it:
    - model_impact: the model's what-if for this profile (skills in the card's
      what_if_skills for the role, and only when the card says use_model);
    - median_salary_difference: within-role median with vs without the skill
      (mart_skill_salary_by_role; only with MIN_SALARIES_PER_SIDE salaries on
      each side — smaller samples swing by tens of thousands).

    Args:
        resume_skills: Skills found on the resume.
        role: Target role.
        skill_demand_df: data.skill_demand().
        salary_card: data.salary_model_card().
        model: serving.load_model(data.salary_model_json()).
        spec: The model's feature spec.
        n: How many skills.
        seniority: The user's chosen level (for the what-if profile).
        state: The user's state, or None.
        remote: Whether the user wants remote work.

    Returns:
        Up to n dicts, most in-demand first: skill, skill_category,
        share_of_role_postings, demand_rank, model_impact, model_impact_status
        (impact_status), median_salary_difference, median_difference_status
        ('ok' or 'too_few_salaries'), n_salaried_with_skill, n_salaried_without_skill.
    """
    found = frozenset(resume_skills)
    rows = skill_demand_df[(skill_demand_df["role_name"] == role) & ~skill_demand_df["skill_name"].isin(found)]
    picks = rows.sort_values("demand_rank").head(n)
    eligible = set(salary_card.get("what_if_skills", {}).get(role, [])) if salary_card.get("use_model") else set()
    candidates = [s for s in picks["skill_name"] if s in eligible]
    impacts = (
        serving.skill_impact(model, spec, Profile(role, seniority, state, remote, found), candidates)
        if candidates
        else {}
    )
    result = []
    for row in picks.itertuples():
        n_with, n_without = int(row.n_salaried_with_skill), int(row.n_salaried_without_skill)
        difference = _optional(row.median_salary_difference)
        enough = (
            row.salary_sample_status == "ok"
            and difference is not None
            and min(n_with, n_without) >= MIN_SALARIES_PER_SIDE
        )
        impact = impacts.get(row.skill_name)
        result.append(
            {
                "skill": row.skill_name,
                "skill_category": row.skill_category,
                "share_of_role_postings": float(row.share_of_role_postings),
                "demand_rank": int(row.demand_rank),
                "model_impact": impact,
                "model_impact_status": impact_status(impact),
                "median_salary_difference": difference if enough else None,
                "median_difference_status": "ok" if enough else "too_few_salaries",
                "n_salaried_with_skill": n_with,
                "n_salaried_without_skill": n_without,
            }
        )
    return result


def level_salary(
    postings_df: pd.DataFrame, role: str, seniority: str, min_salaries: int = MIN_LEVEL_SALARIES
) -> dict:
    """Fix 1 (2026-10-14): the posted median for this role AND level, shown beside the estimate.

    The model pulls toward the overall average (e.g. junior data analyst estimated
    ~$121K vs a $79K posted median), so the level's own median keeps it honest.

    Args:
        postings_df: data.postings().
        role: Target role.
        seniority: The user's chosen level.
        min_salaries: Smallest sample worth a median.

    Returns:
        median (dollars or None), n (salaries found), status: 'ok', 'too_few_salaries',
        or 'no_level' when the user isn't sure of their level (postings whose own level
        is unknown say nothing about the user).
    """
    if seniority not in LEVEL_RANK:
        return {"median": None, "n": 0, "status": "no_level"}
    rows = postings_df[
        (postings_df["role_name"] == role)
        & (postings_df["seniority_effective"] == seniority)
        & postings_df["salary_mid_annual"].notna()
    ]
    n = len(rows)
    if n < min_salaries:
        return {"median": None, "n": n, "status": "too_few_salaries"}
    return {"median": float(rows["salary_mid_annual"].astype(float).median()), "n": n, "status": "ok"}


def predict_salary_for_resume(
    resume_skills: Iterable[str],
    role: str,
    seniority: str,
    state: str | None,
    remote: bool,
    salary_card: dict,
    model_json: dict,
) -> dict:
    """Predicted salary with its typical error, or the role median when the model isn't used.

    The model is used only if it beat the per-role median in cross-validation
    (salary_card["use_model"]); otherwise the role median is the estimate and the
    page says so. The range is ± the cross-validated MAE for the role (overall
    when the role has none).

    Args:
        resume_skills: Skills found on the resume.
        role: Target role.
        seniority: The user's chosen level.
        state: Two-letter state, or None.
        remote: Whether the user wants remote work.
        salary_card: data.salary_model_card().
        model_json: data.salary_model_json().

    Returns:
        salary, low, high, typical_error, method ('model' or 'role_median'),
        role_median, mlflow_run_id.

    Raises:
        ValueError: If the role is unknown to the model card.
    """
    role_medians = salary_card["baselines"]["role_median"]
    if role not in role_medians:
        raise ValueError(f"Unknown role {role!r}; the model knows {sorted(role_medians)}")
    mae = salary_card["cv_mae"]
    key = role.replace(" ", "_")
    if salary_card["use_model"]:
        method = "model"
        spec = FeatureSpec.from_dict(salary_card["feature_spec"])
        profile = Profile(role, seniority, state, remote, frozenset(resume_skills))
        salary = float(serving.predict_salary(serving.load_model(model_json), spec, [profile])[0])
    else:
        method = "role_median"
        salary = float(role_medians[role])
    error = float(mae.get(f"mae_{method}__{key}", mae[f"mae_{method}"]))
    return {
        "salary": salary,
        "low": max(salary - error, 0.0),
        "high": salary + error,
        "typical_error": error,
        "method": method,
        "role_median": float(role_medians[role]),
        "mlflow_run_id": salary_card.get("mlflow_run_id"),
    }


def match_postings(
    resume_embedding: np.ndarray,
    posting_embeddings_df: pd.DataFrame,
    postings_df: pd.DataFrame,
    role: str | None,
    top_n: int = 10,
    *,
    resume_skills: Iterable[str] = (),
    seniority: str | None = None,
    now: datetime | None = None,
) -> pd.DataFrame:
    """D1: the role's recent postings most similar to the resume (cosine similarity).

    "Recent" = fetched in the last RECENT_DAYS days; if the role has none, its
    latest collection instead (the free JSearch plan refreshes each role about
    every 5 days). frame.attrs says which: window ('last_7_days' or
    'latest_collection') and since (the oldest fetch date included).

    Fix 2 (2026-10-14): postings at or near the user's level (±1 step in
    LEVEL_RANK) come first, so a junior isn't shown only VP roles. Postings with
    an unknown level, or a user who isn't sure, count as near.

    Args:
        resume_embedding: The resume's vector (embeddings.embed_texts, length 1).
        posting_embeddings_df: data.posting_embeddings().
        postings_df: data.postings().
        role: Target role, or None for every role.
        top_n: How many postings.
        resume_skills: Skills found on the resume (to show the shared ones).
        seniority: The user's chosen level, or None / 'unknown' for no preference.
        now: Current time (tests pass a fixed one).

    Returns:
        Up to top_n postings — near the user's level first, then most similar:
        job_id, role_name, job_title, employer_name, location_name, is_remote,
        fetched_at, salary_mid_annual, apply_link, level (seniority_effective),
        near_level, similarity, shared_skills (tuple).

    Raises:
        ValueError: If the posting embeddings come from another model revision.
    """
    revision = posting_embeddings_df.attrs.get("model_revision")
    if revision and revision != EMBEDDING_MODEL_REVISION:
        raise ValueError(
            f"Posting embeddings use model revision {revision}, the app uses {EMBEDDING_MODEL_REVISION}; "
            "rerun the NLP step"
        )
    pool = postings_df if role is None else postings_df[postings_df["role_name"] == role]
    pool = pool[pool["job_id"].isin(set(posting_embeddings_df["job_id"]))]
    if pool.empty:
        frame = pool.assign(
            level=pd.Series(dtype=object),
            near_level=pd.Series(dtype=bool),
            similarity=pd.Series(dtype=float),
            shared_skills=pd.Series(dtype=object),
        )
        frame.attrs = {"window": "none", "since": None}
        return frame

    now = now or datetime.now(timezone.utc)
    recent = pool[pool["fetched_at"] >= now - timedelta(days=RECENT_DAYS)]
    if recent.empty:
        latest_day = pool["fetched_at"].max().date()
        recent, window = pool[pool["fetched_at"].dt.date == latest_day], "latest_collection"
    else:
        window = "last_7_days"

    vectors = posting_embeddings_df.set_index("job_id")["embedding"]
    matrix = np.vstack([vectors[j] for j in recent["job_id"]])
    query = np.asarray(resume_embedding, dtype=np.float32)
    similarity = matrix @ (query / np.linalg.norm(query))  # postings are already length 1

    found = set(resume_skills)
    columns = [
        "job_id", "role_name", "job_title", "employer_name", "location_name", "is_remote",
        "fetched_at", "salary_mid_annual", "apply_link",
    ]
    user_rank = LEVEL_RANK.get(seniority or UNKNOWN)
    near = [
        user_rank is None or level not in LEVEL_RANK or abs(LEVEL_RANK[level] - user_rank) <= 1
        for level in recent["seniority_effective"]
    ]
    frame = recent[columns].assign(
        level=recent["seniority_effective"],
        near_level=near,
        similarity=similarity,
        shared_skills=[
            tuple(skill for skill in posting_skills if skill in found) for posting_skills in recent["skills"]
        ],
    )
    frame = (
        frame.sort_values(["near_level", "similarity", "job_id"], ascending=[False, False, True])
        .head(top_n)
        .reset_index(drop=True)
    )
    frame.attrs = {"window": window, "since": recent["fetched_at"].min().date()}
    return frame


def salary_bands_for(
    postings_df: pd.DataFrame,
    bls_df: pd.DataFrame,
    seniority: str | None = None,
    state: str | None = None,
    min_salaries: int = 5,
) -> pd.DataFrame:
    """Posted-salary percentiles per role for a seniority / state slice, next to BLS.

    Percentiles interpolate linearly, like dbt's percentile_cont, so with no filters
    they equal mart_salary_bands. Fewer than min_salaries salaries (dbt's
    min_salary_sample) → no percentiles, status 'too_few_to_report'.

    Args:
        postings_df: data.postings().
        bls_df: data.salary_bands() (for each role's BLS median).
        seniority: seniority_effective to keep, or None for all.
        state: Two-letter state to keep, or None for all.
        min_salaries: Smallest sample worth reporting.

    Returns:
        One row per role in bls_df: n_salaries, salary_p25, salary_median, salary_p75,
        bls_median, median_vs_bls_pct, sample_status.
    """
    salaried = postings_df[postings_df["salary_mid_annual"].notna()]
    if seniority is not None:
        salaried = salaried[salaried["seniority_effective"] == seniority]
    if state is not None:
        salaried = salaried[salaried["state_code"] == state]
    rows = []
    for band in bls_df.itertuples():
        values = salaried.loc[salaried["role_name"] == band.role_name, "salary_mid_annual"].astype(float)
        enough = len(values) >= min_salaries
        p25, median, p75 = (values.quantile([0.25, 0.5, 0.75]).tolist() if enough else (None, None, None))
        bls = _optional(band.bls_median_annual_wage)
        rows.append(
            {
                "role_name": band.role_name,
                "n_salaries": len(values),
                "salary_p25": p25,
                "salary_median": median,
                "salary_p75": p75,
                "bls_median": bls,
                "median_vs_bls_pct": (median / bls - 1) if median is not None and bls else None,
                "sample_status": "ok" if enough else "too_few_to_report",
            }
        )
    return pd.DataFrame(rows)


def topic_role_mix(postings_df: pd.DataFrame) -> pd.DataFrame:
    """How each topic's postings split across the search roles.

    Args:
        postings_df: data.postings() (topic_id -1 = no topic; missing = not processed).

    Returns:
        One row per (topic, role): topic_id, topic_label, role_name, n_postings and
        share_of_topic; postings in no topic are left out.
    """
    topical = postings_df[postings_df["topic_id"].notna() & (postings_df["topic_id"] >= 0)]
    counts = (
        topical.groupby(["topic_id", "topic_label", "role_name"]).size().rename("n_postings").reset_index()
    )
    counts["topic_id"] = counts["topic_id"].astype(int)
    counts["share_of_topic"] = counts["n_postings"] / counts.groupby("topic_id")["n_postings"].transform("sum")
    return counts.sort_values(["topic_id", "n_postings"], ascending=[True, False]).reset_index(drop=True)
