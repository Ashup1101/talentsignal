"""Streamlit AppTest tests for every page, on stub data (tests/app_stubs.py).

AppTest runs each page script in this process, without a browser; uploads go through
the real file uploader. Skipped where Streamlit / XGBoost aren't installed (the CI
pytest job); runs in the `ml` job.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("xgboost")

from streamlit.testing.v1 import AppTest  # noqa: E402

from src.app import ui  # noqa: E402
from tests import app_stubs  # noqa: E402
from tests.fixtures.make_resume_pdf import RESUME_PATH, pdf_with_lines  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "src" / "app"


@pytest.fixture(autouse=True)
def stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    app_stubs.install(monkeypatch)


def _run(page: str) -> AppTest:
    at = AppTest.from_file(str(APP / page), default_timeout=60)
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def _texts(at: AppTest) -> str:
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption]
    parts += [e.value for e in (*at.info, *at.warning, *at.error, *at.success)]
    return "\n".join(parts)


# --- Home -----------------------------------------------------------------------------


def test_home_shows_data_freshness() -> None:
    at = _run("streamlit_app.py")

    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Job postings"] == "60"
    assert metrics["Newest collection"] == "1 day ago"
    assert metrics["Collected in the last 7 days"] == "12"  # the stub's data engineers
    assert metrics["Salary model error (typical)"] == "$30,000"
    assert at.success  # newest postings are under 2 days old


# --- Resume Analyzer --------------------------------------------------------------------


def test_resume_analyzer_waits_for_a_resume() -> None:
    at = _run("pages/01_resume_analyzer.py")

    assert at.info[0].value == "Upload a PDF to begin."
    assert not at.dataframe


def test_uploaded_resume_is_analyzed_end_to_end() -> None:
    at = _run("pages/01_resume_analyzer.py")
    at.file_uploader[0].upload("resume.pdf", RESUME_PATH.read_bytes(), "application/pdf").run()

    assert not at.exception, [e.message for e in at.exception]
    skills, matches, core, postings = (d.value for d in at.dataframe)
    assert set(skills["Skill"]) == {"Python", "SQL", "Spark", "Airflow", "dbt", "PostgreSQL", "AWS", "Docker"}
    assert sorted(matches["Role"]) == sorted(r.title() for r in app_stubs.ROLES)
    assert matches["Match"].between(0, 1).all()
    assert core["On resume"].any()
    assert at.metric[0].value.startswith("$")
    assert "Likely range $" in _texts(at)
    assert len(postings) == 10 and postings["Apply"].str.startswith("https://jobs.example/").all()
    assert "Postings collected in the last 7 days" in _texts(at)  # stub data engineers: 1 day old


def test_role_without_recent_postings_says_which_collection_it_used() -> None:
    at = _run("pages/01_resume_analyzer.py")
    at.selectbox[0].set_value("data analyst")
    at.file_uploader[0].upload("resume.pdf", RESUME_PATH.read_bytes(), "application/pdf").run()

    assert "so these come from its latest collection" in _texts(at)


def test_sample_resume_button_runs_the_same_analysis() -> None:
    at = _run("pages/01_resume_analyzer.py")
    at.button[0].click().run()

    assert not at.exception
    assert "In the sample resume (a made-up data engineer)" in _texts(at)
    assert len(at.dataframe) == 4


def test_scanned_pdf_gets_a_clear_message() -> None:
    at = _run("pages/01_resume_analyzer.py")
    at.file_uploader[0].upload("scan.pdf", pdf_with_lines([]), "application/pdf").run()

    assert "Scanned or image-only resumes aren't supported" in at.error[0].value
    assert not at.dataframe


def test_a_file_that_isnt_a_pdf_is_rejected() -> None:
    at = _run("pages/01_resume_analyzer.py")
    at.file_uploader[0].upload("resume.pdf", b"this is not a pdf", "application/pdf").run()

    assert at.error[0].value == "This file isn't a readable PDF. Please upload a PDF file."


def test_a_zero_what_if_reads_no_measurable_effect(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app import logic

    zero = {
        "skill": "Kafka", "skill_category": "data_engineering", "share_of_role_postings": 0.3, "demand_rank": 4,
        "model_impact": 0.0, "median_salary_difference": None, "salary_sample_status": "too_few_to_report",
        "n_salaried_with_skill": 2, "n_salaried_without_skill": 40,
    }
    monkeypatch.setattr(logic, "top_missing_skills", lambda *args, **kwargs: [zero])
    at = _run("pages/01_resume_analyzer.py")
    at.file_uploader[0].upload("resume.pdf", RESUME_PATH.read_bytes(), "application/pdf").run()

    texts = _texts(at)
    assert "**no measurable effect**" in texts and "$0" not in texts
    assert "**too few salaries to compare**" in texts


# --- Salary Explorer --------------------------------------------------------------------


def test_salary_explorer_shows_every_role_next_to_bls() -> None:
    at = _run("pages/02_salary_explorer.py")

    table = at.dataframe[0].value
    assert len(table) == 5 and table["Posted salaries"].tolist() == [10] * 5
    assert table.loc[table["Role"] == "Data Analyst", "BLS median"].item() == "—"  # no BLS benchmark


def test_salary_explorer_filters_report_too_few_salaries() -> None:
    at = _run("pages/02_salary_explorer.py")
    at.selectbox[0].set_value("staff_plus").run()  # the stub has 3 staff+ salaries per role (< 5)
    at.selectbox[1].set_value("NY").run()

    assert not at.dataframe
    assert "Fewer than 5 posted salaries" in at.warning[0].value
    assert "Too few posted salaries (under 5) to report" in _texts(at)


# --- Skill Demand ---------------------------------------------------------------------


def test_skill_demand_shows_ranks_and_forecast_progress() -> None:
    at = _run("pages/03_skill_demand.py")

    ranks = at.dataframe[0].value
    assert ranks["Rank"].tolist() == list(range(1, len(app_stubs.SKILLS) + 1))
    assert "Forecasts start once a skill has 12 weekly data points" in at.info[0].value


def test_skill_demand_charts_a_forecast_once_one_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    app_stubs.install(monkeypatch, forecasting=True)
    at = _run("pages/03_skill_demand.py")

    assert not at.info
    assert at.selectbox[1].value == "SQL"
    assert "Dashed: Prophet forecast" in _texts(at)


# --- Job Insights ---------------------------------------------------------------------


def test_job_insights_lists_topics_and_breakdowns() -> None:
    at = _run("pages/04_job_insights.py")

    topics = at.dataframe[0].value
    assert topics["Topic"].tolist() == ["data pipelines, spark", "dashboards, reporting"]
    texts = _texts(at)
    assert "33% of postings fit no clear topic" in texts
    assert "25% of all postings are remote" in texts


def test_sample_resume_is_the_test_fixture() -> None:
    assert ui.SAMPLE_RESUME.read_bytes() == RESUME_PATH.read_bytes()
