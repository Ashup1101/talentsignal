"""Response models of the TalentSignal API (Phase 6).

They document the API at /api/docs and are the source of the frontend's TypeScript
types (generated from /api/openapi.json). Amounts are dollars per year; shares are
fractions in [0, 1]. Statuses carry the decisions (thresholds live in src/api/logic.py),
so the frontend only formats.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class Level(BaseModel):
    value: str
    label: str


class Options(BaseModel):
    roles: list[str]
    levels: list[Level]
    states: list[str]
    max_upload_mb: int


class Overview(BaseModel):
    n_postings: int
    n_salaried: int
    newest_collection: datetime
    n_last_7_days: int
    pipeline_current: bool  # newest collection at most 2 days old
    model_typical_error: float
    model_used: bool
    model_trained_at: str | None
    forecast_weeks_observed: int
    forecast_weeks_needed: int


class SkillFound(BaseModel):
    skill: str
    share_of_role_postings: float  # 0 when the target role's postings never mention it
    demand_rank: int | None


class RoleMatch(BaseModel):
    role: str
    match: float


class CoreSkill(BaseModel):
    skill: str
    share_of_role_postings: float
    on_resume: bool


class LevelMedian(BaseModel):
    median: float | None
    n: int
    status: Literal["ok", "too_few_salaries", "no_level"]


class SalaryEstimate(BaseModel):
    estimate: float
    low: float
    high: float
    typical_error: float
    method: Literal["model", "role_median"]
    role_median: float
    level_median: LevelMedian
    model_run_id: str | None


class MissingSkill(BaseModel):
    skill: str
    skill_category: str
    share_of_role_postings: float
    demand_rank: int
    model_impact: float | None
    model_impact_status: Literal["value", "no_measurable_effect", "not_enough_data"]
    median_salary_difference: float | None
    median_difference_status: Literal["ok", "too_few_salaries"]
    n_salaried_with_skill: int
    n_salaried_without_skill: int


class MatchingPosting(BaseModel):
    job_id: str
    title: str
    employer: str | None
    location: str | None
    remote: bool
    level: str | None
    near_level: bool
    similarity: float
    shared_skills: list[str]
    salary: float | None
    apply_link: str | None


class MatchingPostings(BaseModel):
    window: Literal["last_7_days", "latest_collection", "none"]
    since: date | None
    items: list[MatchingPosting]


class Analysis(BaseModel):
    role: str
    level: str
    skills: list[SkillFound]
    role_matches: list[RoleMatch]
    core_skills: list[CoreSkill]
    salary: SalaryEstimate
    missing_skills: list[MissingSkill]
    postings: MatchingPostings


class SalaryBand(BaseModel):
    role: str
    n_salaries: int
    p25: float | None
    median: float | None
    p75: float | None
    bls_median: float | None
    median_vs_bls: float | None
    status: Literal["ok", "too_few_to_report"]


class RankedSkill(BaseModel):
    rank: int
    skill: str
    category: str
    share_of_postings: float
    postings: int


class ForecastStatus(BaseModel):
    weeks_observed: int
    weeks_needed: int
    forecasting_skills: list[str]


class SkillDemand(BaseModel):
    role: str
    n_role_postings: int
    skills: list[RankedSkill]
    forecast: ForecastStatus


class WeeklyShare(BaseModel):
    week: date
    share: float


class ForecastPoint(BaseModel):
    week: date
    share: float
    lower: float
    upper: float


class Forecast(BaseModel):
    role: str
    skill: str
    status: Literal["forecast", "insufficient_history"]
    history: list[WeeklyShare]
    forecast: list[ForecastPoint]


class Topic(BaseModel):
    topic_id: int
    label: str
    n_postings: int
    share_of_postings: float
    keywords: list[str]


class TopicRole(BaseModel):
    topic_id: int
    topic_label: str
    role: str
    n_postings: int
    share_of_topic: float


class LevelCount(BaseModel):
    role: str
    level: str
    n_postings: int


class RemoteShare(BaseModel):
    role: str
    share: float


class Insights(BaseModel):
    unassigned_share: float
    topics: list[Topic]
    role_mix: list[TopicRole]
    levels: list[LevelCount]
    remote: list[RemoteShare]
    remote_share_all: float


class ErrorBody(BaseModel):
    detail: str
    code: str
