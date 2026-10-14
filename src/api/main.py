"""TalentSignal API (Phase 6): FastAPI over the dbt marts, ml.* and the Phase 5 models.

The Next.js frontend (web/, a static export) calls these endpoints; in production
nginx serves both from one origin. Interactive docs: /api/docs.

Resumes: POST /api/analyze takes the raw PDF as the request body (no multipart, so
nothing is spooled to a temporary file), reads at most MAX_UPLOAD_BYTES into memory,
and returns the analysis only — never the text. Nothing is saved or logged.

Run locally: infra/api/run_local.sh  (http://localhost:8000/api/docs)
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import TypeVar

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from xgboost import XGBRegressor

from src.api import data, logic, serving  # src.api pins OMP_NUM_THREADS before PyTorch/XGBoost load
from src.api import schemas as s
from src.ml import embeddings, resume_features
from src.ml.features import UNKNOWN, FeatureSpec

T = TypeVar("T")

MAX_UPLOAD_MB = 5
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MIN_WEEKS_TO_FORECAST = 12  # src/ml/demand_forecast.py (not imported: it needs Prophet)
STALE_AFTER = timedelta(days=2)
LEVEL_LABELS = {
    "intern": "Intern",
    "junior": "Junior (0–1 years)",
    "mid": "Mid-level (2–3 years)",
    "senior": "Senior (4–6 years)",
    "staff_plus": "Staff / principal (7+ years)",
    "manager": "Manager",
    UNKNOWN: "Not sure",
}

app = FastAPI(
    title="TalentSignal API",
    version="1.0.0",
    summary="How a resume compares with real job postings.",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)
# Only for local development (the Next.js dev server runs on another port); in
# production nginx serves the frontend and the API from one origin.
if origins := [o.strip() for o in os.getenv("APP_CORS_ORIGINS", "").split(",") if o.strip()]:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["*"])


class ApiError(Exception):
    """An error the client can act on: HTTP status, plain message, machine-readable code."""

    def __init__(self, status: int, detail: str, code: str) -> None:
        super().__init__(detail)
        self.status, self.detail, self.code = status, detail, code


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": exc.detail, "code": exc.code})


def _load(func: Callable[[], T], what: str) -> T:
    # Backend failures (RDS, S3) become a 503 with a plain message; no stack traces leave the API.
    try:
        return func()
    except Exception as exc:
        raise ApiError(503, f"Couldn't load {what} right now; please try again in a minute.", "unavailable") from exc


_model_cache: dict[str, tuple[float, XGBRegressor]] = {}
_model_lock = threading.Lock()


def salary_model() -> XGBRegressor:
    """The exported salary model, loaded once and refreshed after data.CACHE_SECONDS.

    Returns:
        The single-threaded model (serving.load_model).
    """
    with _model_lock:
        hit = _model_cache.get("model")
        if hit is None or time.monotonic() - hit[0] >= data.CACHE_SECONDS:
            hit = (time.monotonic(), serving.load_model(data.salary_model_json()))
            _model_cache["model"] = hit
        return hit[1]


def _card_and_spec() -> tuple[dict, FeatureSpec]:
    card = _load(data.salary_model_card, "the salary model")
    return card, FeatureSpec.from_dict(card["feature_spec"])


def _roles(card: dict) -> list[str]:
    return sorted(card["baselines"]["role_median"])


def _check_role(role: str, roles: list[str]) -> None:
    if role not in roles:
        raise ApiError(422, f"Unknown role {role!r}; choose one of {roles}.", "unknown_role")


def _none_if_nan(value: object) -> object:
    return None if value is None or (isinstance(value, float) and np.isnan(value)) else value


# --- Reference data -------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness probe: the process is up (no database or S3 call)."""
    return {"status": "ok"}


@app.get("/api/options", response_model=s.Options)
def options() -> s.Options:
    """Choices for the Resume Analyzer form: roles, levels and states the model knows."""
    card, spec = _card_and_spec()
    return s.Options(
        roles=_roles(card),
        levels=[s.Level(value=v, label=label) for v, label in LEVEL_LABELS.items()],
        states=[st for st in spec.states if st != UNKNOWN],
        max_upload_mb=MAX_UPLOAD_MB,
    )


@app.get("/api/overview", response_model=s.Overview)
def overview() -> s.Overview:
    """How much data there is and how fresh it is."""
    postings = _load(data.postings, "the job postings")
    card, _ = _card_and_spec()
    forecast = _load(data.skill_demand_forecast, "the demand forecast")
    now = datetime.now(timezone.utc)
    newest = postings["fetched_at"].max().to_pydatetime()
    return s.Overview(
        n_postings=len(postings),
        n_salaried=int(postings["salary_mid_annual"].notna().sum()),
        newest_collection=newest,
        n_last_7_days=int((postings["fetched_at"] >= now - timedelta(days=7)).sum()),
        pipeline_current=now - newest <= STALE_AFTER,
        model_typical_error=float(card["cv_mae"]["mae_model"]),
        model_used=bool(card["use_model"]),
        model_trained_at=card.get("trained_at"),
        forecast_weeks_observed=int(forecast["observed_weeks"].max()) if not forecast.empty else 0,
        forecast_weeks_needed=MIN_WEEKS_TO_FORECAST,
    )


# --- Resume analysis ----------------------------------------------------------------------


async def _read_pdf(request: Request) -> bytes:
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/pdf":
        raise ApiError(415, "Send the resume as a PDF (Content-Type: application/pdf).", "not_pdf")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise ApiError(413, f"The file is larger than {MAX_UPLOAD_MB} MB.", "too_large")
    body = bytearray()
    async for chunk in request.stream():  # enforced while reading: an oversized upload is never held whole
        body.extend(chunk)
        if len(body) > MAX_UPLOAD_BYTES:
            raise ApiError(413, f"The file is larger than {MAX_UPLOAD_MB} MB.", "too_large")
    if not body:
        raise ApiError(400, "The upload was empty.", "empty")
    return bytes(body)


def _analyze(pdf: bytes, role: str, level: str, state: str | None, remote: bool) -> s.Analysis:
    card, spec = _card_and_spec()
    roles = _roles(card)
    _check_role(role, roles)
    try:
        text = resume_features.extract_text(pdf)
    except resume_features.NoTextError as exc:
        raise ApiError(422, str(exc), "no_text") from exc
    except ValueError as exc:
        raise ApiError(400, f"{exc} Please upload a PDF file.", "unreadable_pdf") from exc
    skills = resume_features.find_skills(text)

    demand = _load(data.skill_demand, "skill demand")
    postings = _load(data.postings, "the job postings")
    role_demand = demand[demand["role_name"] == role].set_index("skill_name")
    found = sorted(
        (
            s.SkillFound(
                skill=skill,
                share_of_role_postings=float(role_demand["share_of_role_postings"].get(skill, 0.0)),
                demand_rank=int(role_demand["demand_rank"][skill]) if skill in role_demand.index else None,
            )
            for skill in skills
        ),
        key=lambda f: (-f.share_of_role_postings, f.skill),
    )
    matches = sorted(
        (s.RoleMatch(role=r, match=logic.match_pct(skills, r, demand)) for r in roles), key=lambda m: -m.match
    )
    core = logic.core_skills(skills, role, demand)

    salary = logic.predict_salary_for_resume(
        skills, role, level, state, remote, card, _load(data.salary_model_json, "the salary model")
    )
    missing = logic.top_missing_skills(
        skills, role, demand, card, salary_model(), spec, seniority=level, state=state, remote=remote
    )

    matched = logic.match_postings(
        embeddings.embed_texts([text])[0],
        _load(data.posting_embeddings, "the posting embeddings"),
        postings,
        role,
        top_n=10,
        resume_skills=skills,
        seniority=level,
    )
    return s.Analysis(
        role=role,
        level=level,
        skills=found,
        role_matches=matches,
        core_skills=[
            s.CoreSkill(skill=r.skill_name, share_of_role_postings=float(r.share_of_role_postings), on_resume=r.on_resume)
            for r in core.itertuples()
        ],
        salary=s.SalaryEstimate(
            estimate=salary["salary"],
            low=salary["low"],
            high=salary["high"],
            typical_error=salary["typical_error"],
            method=salary["method"],
            role_median=salary["role_median"],
            level_median=s.LevelMedian(**logic.level_salary(postings, role, level)),
            model_run_id=salary["mlflow_run_id"],
        ),
        missing_skills=[s.MissingSkill(**m) for m in missing],
        postings=s.MatchingPostings(
            window=matched.attrs["window"],
            since=matched.attrs["since"],
            items=[
                s.MatchingPosting(
                    job_id=r.job_id,
                    title=r.job_title,
                    employer=_none_if_nan(r.employer_name),
                    location=_none_if_nan(r.location_name),
                    remote=bool(r.is_remote),
                    level=_none_if_nan(r.level),
                    near_level=bool(r.near_level),
                    similarity=float(r.similarity),
                    shared_skills=list(r.shared_skills),
                    salary=_none_if_nan(r.salary_mid_annual),
                    apply_link=_none_if_nan(r.apply_link),
                )
                for r in matched.itertuples()
            ],
        ),
    )


@app.post(
    "/api/analyze",
    response_model=s.Analysis,
    responses={
        400: {"model": s.ErrorBody}, 413: {"model": s.ErrorBody}, 415: {"model": s.ErrorBody},
        422: {"model": s.ErrorBody}, 503: {"model": s.ErrorBody},
    },
    openapi_extra={"requestBody": {"required": True, "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}},
)
async def analyze(
    request: Request,
    role: str = Query(..., description="Target role, e.g. 'data engineer'"),
    level: str = Query(UNKNOWN, description="The user's level (see /api/options)"),
    state: str | None = Query(None, description="Two-letter state, or omit"),
    remote: bool = Query(False),
) -> s.Analysis:
    """Analyze a resume PDF (the raw request body) against real postings for a target role.

    The PDF is read in memory, never stored or logged; the response never includes its text.
    """
    if level not in LEVEL_LABELS:
        raise ApiError(422, f"Unknown level {level!r}; choose one of {list(LEVEL_LABELS)}.", "unknown_level")
    pdf = await _read_pdf(request)
    # PDF parsing, embedding and XGBoost are CPU work: run them off the event loop.
    return await run_in_threadpool(_analyze, pdf, role, level, state, remote)


# --- Salary Explorer, Skill Demand, Job Insights --------------------------------------------


@app.get("/api/salaries", response_model=list[s.SalaryBand])
def salaries(level: str | None = None, state: str | None = None) -> list[s.SalaryBand]:
    """Posted-salary percentiles per role for a level / state slice, next to the BLS median."""
    bands = logic.salary_bands_for(
        _load(data.postings, "the job postings"), _load(data.salary_bands, "the salary bands"), level, state
    )
    return [
        s.SalaryBand(
            role=r.role_name, n_salaries=int(r.n_salaries), p25=_none_if_nan(r.salary_p25),
            median=_none_if_nan(r.salary_median), p75=_none_if_nan(r.salary_p75),
            bls_median=_none_if_nan(r.bls_median), median_vs_bls=_none_if_nan(r.median_vs_bls_pct),
            status=r.sample_status,
        )
        for r in bands.itertuples()
    ]


@app.get("/api/skills", response_model=s.SkillDemand)
def skills(role: str) -> s.SkillDemand:
    """The skills a role's postings ask for, ranked, and the demand forecast's progress."""
    demand = _load(data.skill_demand, "skill demand")
    _check_role(role, sorted(demand["role_name"].unique()))
    rows = demand[demand["role_name"] == role].sort_values("demand_rank")
    forecast = _load(data.skill_demand_forecast, "the demand forecast")
    role_fc = forecast[forecast["search_role"] == role]
    return s.SkillDemand(
        role=role,
        n_role_postings=int(rows["n_role_postings"].iloc[0]),
        skills=[
            s.RankedSkill(rank=int(r.demand_rank), skill=r.skill_name, category=r.skill_category,
                          share_of_postings=float(r.share_of_role_postings), postings=int(r.n_postings_with_skill))
            for r in rows.itertuples()
        ],
        forecast=s.ForecastStatus(
            weeks_observed=int(role_fc["observed_weeks"].max()) if not role_fc.empty else 0,
            weeks_needed=MIN_WEEKS_TO_FORECAST,
            forecasting_skills=sorted(role_fc.loc[role_fc["forecast_status"] == "forecast", "skill_name"].unique()),
        ),
    )


@app.get("/api/forecast", response_model=s.Forecast)
def forecast(role: str, skill: str) -> s.Forecast:
    """Weekly demand share for one role × skill, plus Prophet's forecast once it has enough weeks."""
    rows = _load(data.skill_demand_forecast, "the demand forecast")
    rows = rows[(rows["search_role"] == role) & (rows["skill_name"] == skill)]
    if rows.empty:
        raise ApiError(404, f"No demand series for {skill!r} in {role!r}.", "not_found")
    history = _load(data.skill_demand_history, "the demand history")
    past = history[(history["search_role"] == role) & (history["skill_name"] == skill)]
    ahead = rows[rows["forecast_status"] == "forecast"]
    return s.Forecast(
        role=role,
        skill=skill,
        status="forecast" if not ahead.empty else "insufficient_history",
        history=[s.WeeklyShare(week=r.collection_week, share=float(r.share_of_role_postings)) for r in past.itertuples()],
        forecast=[
            s.ForecastPoint(week=r.forecast_week, share=float(r.share_forecast),
                            lower=float(r.share_lower), upper=float(r.share_upper))
            for r in ahead.itertuples()
        ],
    )


@app.get("/api/insights", response_model=s.Insights)
def insights() -> s.Insights:
    """Topics found in the postings, the roles behind each, level mix and remote share."""
    topics = _load(data.job_insights, "the topics")
    postings = _load(data.postings, "the job postings")
    named = topics[topics["topic_id"] >= 0].sort_values("n_postings", ascending=False)
    levels = postings.groupby(["role_name", "seniority_effective"]).size().reset_index(name="n")
    remote = postings.groupby("role_name")["is_remote"].mean()
    return s.Insights(
        unassigned_share=float(topics.loc[topics["topic_id"] < 0, "share_of_postings"].sum()),
        topics=[
            s.Topic(topic_id=int(r.topic_id), label=r.topic_label, n_postings=int(r.n_postings),
                    share_of_postings=float(r.share_of_postings), keywords=list(r.top_words))
            for r in named.itertuples()
        ],
        role_mix=[
            s.TopicRole(topic_id=int(r.topic_id), topic_label=r.topic_label, role=r.role_name,
                        n_postings=int(r.n_postings), share_of_topic=float(r.share_of_topic))
            for r in logic.topic_role_mix(postings).itertuples()
        ],
        levels=[s.LevelCount(role=r.role_name, level=r.seniority_effective, n_postings=int(r.n)) for r in levels.itertuples()],
        remote=[s.RemoteShare(role=role, share=float(share)) for role, share in remote.items()],
        remote_share_all=float(pd.Series(postings["is_remote"]).mean()),
    )
