"""Tests for the API endpoints (src/api/main.py) through FastAPI's TestClient, on stub data.

tests/api_stubs.py replaces the database, S3 and the embedding model; the salary model
is a tiny real XGBoost model. Skipped where FastAPI / XGBoost aren't installed (the CI
pytest job); runs in the `ml` job.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("xgboost")

from fastapi.testclient import TestClient  # noqa: E402

from src.api import data, main  # noqa: E402
from tests import api_stubs  # noqa: E402
from tests.fixtures.make_resume_pdf import RESUME_PATH, pdf_with_lines  # noqa: E402

PDF = {"Content-Type": "application/pdf"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    api_stubs.install(monkeypatch)
    return TestClient(main.app)


def _analyze(client: TestClient, body: bytes, **params: str) -> object:
    return client.post("/api/analyze", params={"role": "data engineer", **params}, content=body, headers=PDF)


# --- Reference data ---------------------------------------------------------------------


def test_health_needs_no_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data, "postings", lambda: (_ for _ in ()).throw(RuntimeError("db down")))

    assert TestClient(main.app).get("/api/health").json() == {"status": "ok"}


def test_options_list_the_models_roles_levels_and_states(client: TestClient) -> None:
    body = client.get("/api/options").json()

    assert body["roles"] == api_stubs.ROLES
    assert [lvl["value"] for lvl in body["levels"]][-1] == "unknown" and body["max_upload_mb"] == 5
    assert "unknown" not in body["states"]


def test_overview_reports_freshness(client: TestClient) -> None:
    body = client.get("/api/overview").json()

    assert (body["n_postings"], body["n_salaried"], body["n_last_7_days"]) == (60, 50, 12)
    assert body["pipeline_current"] is True
    assert (body["forecast_weeks_observed"], body["forecast_weeks_needed"]) == (2, 12)


def test_backend_failures_become_a_plain_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> None:
        raise RuntimeError("password authentication failed for user app_reader")

    monkeypatch.setattr(data, "postings", broken)

    response = client.get("/api/overview")

    assert response.status_code == 503 and response.json()["code"] == "unavailable"
    assert "password" not in response.text  # no internals leak to the client


# --- Resume analysis ----------------------------------------------------------------------


def test_a_resume_is_analyzed_end_to_end(client: TestClient) -> None:
    response = _analyze(client, RESUME_PATH.read_bytes(), level="junior")

    assert response.status_code == 200
    body = response.json()
    assert {s["skill"] for s in body["skills"]} == {"Python", "SQL", "Spark", "Airflow", "dbt", "PostgreSQL", "AWS", "Docker"}
    assert len(body["role_matches"]) == 5 and all(0 <= m["match"] <= 1 for m in body["role_matches"])
    salary = body["salary"]
    assert salary["method"] == "model" and salary["low"] <= salary["estimate"] <= salary["high"]
    assert salary["level_median"]["status"] in {"ok", "too_few_salaries"}
    unsure = _analyze(client, RESUME_PATH.read_bytes()).json()  # level defaults to "unknown"
    assert unsure["salary"]["level_median"] == {"median": None, "n": 0, "status": "no_level"}
    assert body["missing_skills"] and all(m["model_impact_status"] for m in body["missing_skills"])
    postings = body["postings"]
    assert postings["window"] == "last_7_days" and len(postings["items"]) == 10
    near = [p["near_level"] for p in postings["items"]]
    assert near == sorted(near, reverse=True)  # postings near a junior's level come first
    assert "Alex Example" not in response.text  # the resume's text never comes back


def test_a_role_without_recent_postings_uses_its_latest_collection(client: TestClient) -> None:
    body = _analyze(client, RESUME_PATH.read_bytes(), role="data analyst").json()

    assert body["postings"]["window"] == "latest_collection"


@pytest.mark.parametrize(
    ("body", "headers", "params", "status", "code"),
    [
        (b"hello", {"Content-Type": "text/plain"}, {}, 415, "not_pdf"),
        (b"not a pdf at all", PDF, {}, 400, "unreadable_pdf"),
        (pdf_with_lines([]), PDF, {}, 422, "no_text"),
        (b"", PDF, {}, 400, "empty"),
        (b"%PDF-1.4", PDF, {"role": "chef"}, 422, "unknown_role"),
        (b"%PDF-1.4", PDF, {"level": "ceo"}, 422, "unknown_level"),
    ],
)
def test_bad_uploads_get_clear_errors(
    client: TestClient, body: bytes, headers: dict, params: dict, status: int, code: str
) -> None:
    response = client.post("/api/analyze", params={"role": "data engineer", **params}, content=body, headers=headers)

    assert (response.status_code, response.json()["code"]) == (status, code)


def test_uploads_over_the_limit_are_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 1000)

    response = _analyze(client, b"%PDF" + b"0" * 2000)

    assert (response.status_code, response.json()["code"]) == (413, "too_large")


def test_scanned_resume_message_is_shown_as_is(client: TestClient) -> None:
    response = _analyze(client, pdf_with_lines([]))

    assert "Scanned or image-only resumes aren't supported" in response.json()["detail"]


# --- Salary Explorer, Skill Demand, Job Insights --------------------------------------------


def test_salaries_per_role_and_filters(client: TestClient) -> None:
    every = client.get("/api/salaries").json()
    narrow = client.get("/api/salaries", params={"level": "staff_plus", "state": "NY"}).json()

    assert [b["n_salaries"] for b in every] == [10] * 5 and every[0]["bls_median"] is None
    assert {b["status"] for b in narrow} == {"too_few_to_report"} and narrow[0]["median"] is None


def test_skills_rank_and_forecast_progress(client: TestClient) -> None:
    body = client.get("/api/skills", params={"role": "data engineer"}).json()

    assert [s["rank"] for s in body["skills"]] == list(range(1, len(api_stubs.SKILLS) + 1))
    assert body["forecast"] == {"weeks_observed": 2, "weeks_needed": 12, "forecasting_skills": []}
    assert client.get("/api/skills", params={"role": "chef"}).status_code == 422


def test_forecast_series_once_it_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    api_stubs.install(monkeypatch, forecasting=True)
    client = TestClient(main.app)

    body = client.get("/api/forecast", params={"role": "data engineer", "skill": "SQL"}).json()

    assert body["status"] == "forecast" and len(body["history"]) == 14 and len(body["forecast"]) == 13
    assert all(p["lower"] <= p["share"] <= p["upper"] for p in body["forecast"])
    assert client.get("/api/forecast", params={"role": "data engineer", "skill": "Cobol"}).status_code == 404


def test_insights_topics_mix_levels_and_remote(client: TestClient) -> None:
    body = client.get("/api/insights").json()

    assert [t["label"] for t in body["topics"]] == ["data pipelines, spark", "dashboards, reporting"]
    assert body["unassigned_share"] == pytest.approx(1 / 3)
    assert body["remote_share_all"] == pytest.approx(0.25)
    assert {m["role"] for m in body["role_mix"]} == set(api_stubs.ROLES)
    assert sum(lvl["n_postings"] for lvl in body["levels"]) == 60


def test_openapi_documents_the_pdf_upload(client: TestClient) -> None:
    spec = client.get("/api/openapi.json").json()

    post = spec["paths"]["/api/analyze"]["post"]
    # OpenAPI 3.1 file body: contentMediaType (the docs page shows a file picker for it).
    assert post["requestBody"]["content"]["application/pdf"]["schema"] == {
        "type": "string", "contentMediaType": "application/pdf",
    }
    params = {p["name"]: p for p in post["parameters"]}
    assert set(params["role"]["examples"]) == set(main.SEARCH_ROLES)
    assert params["level"]["schema"]["enum"][-1] == "unknown"
    assert client.get("/api/docs").status_code == 200


def test_committed_openapi_matches_the_api() -> None:
    # web/openapi.json generates the frontend's TypeScript types; an endpoint change must
    # be re-exported (python -m src.api.export_openapi && cd web && npm run gen:api).
    from src.api import export_openapi

    assert export_openapi.OUTPUT.read_text() == export_openapi.render()
