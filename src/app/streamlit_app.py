"""TalentSignal home page: what the app does, how fresh the data is, where to go next.

Run locally: infra/app/run_local.sh (http://localhost:8501).
"""

from src.app import ui  # first: pins OMP_NUM_THREADS before PyTorch / XGBoost load

from datetime import datetime, timedelta, timezone  # noqa: E402

import streamlit as st  # noqa: E402

from src.app import data  # noqa: E402
from src.app import formatting as fmt  # noqa: E402

ui.setup_page("Home", ":material/insights:")

st.title("TalentSignal")
st.markdown(
    "**How does your resume compare with what real job postings ask for?** "
    "Upload a resume to see the skills it shows, how well it matches five data and software roles, "
    "an estimated salary, the in-demand skills it's missing, and matching postings collected this week."
)

left, right = st.columns(2)
with left:
    st.page_link("pages/01_resume_analyzer.py", label="Resume Analyzer", icon=":material/description:")
    st.caption("Upload a resume: skills, match %, salary estimate, missing skills, matching postings.")
    st.page_link("pages/02_salary_explorer.py", label="Salary Explorer", icon=":material/payments:")
    st.caption("Posted salary ranges per role, by level and state, next to government (BLS) figures.")
with right:
    st.page_link("pages/03_skill_demand.py", label="Skill Demand", icon=":material/trending_up:")
    st.caption("Which skills each role asks for, and the forecast status.")
    st.page_link("pages/04_job_insights.py", label="Job Insights", icon=":material/hub:")
    st.caption("Topics found in the postings, seniority mix and remote work.")

st.divider()
st.subheader("Data freshness")
postings = ui.load(data.postings, "the job postings")
card = ui.load(data.salary_model_card, "the salary model")
now = datetime.now(timezone.utc)
latest = postings["fetched_at"].max()
recent = postings[postings["fetched_at"] >= now - timedelta(days=7)]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Job postings", f"{len(postings):,}")
c2.metric("Newest collection", fmt.age_text(latest, now), help=f"{latest:%Y-%m-%d %H:%M} UTC")
c3.metric("Collected in the last 7 days", f"{len(recent):,}")
c4.metric("Salary model error (typical)", fmt.money(card["cv_mae"]["mae_model"]), help="Cross-validated MAE")
if (now - latest).days > 2:
    st.warning(
        "The newest postings are more than 2 days old: the nightly pipeline hasn't run recently. "
        "Everything still works on the data collected so far."
    )
else:
    st.success("The nightly pipeline is running: postings, models and forecasts are current.")

with st.expander("How it works"):
    st.markdown(
        "- **Postings** come from the JSearch API every night (free plan: a few role × city searches a day) "
        "and salary benchmarks from the U.S. Bureau of Labor Statistics.\n"
        "- **Airflow** runs the pipeline: PySpark cleans and de-duplicates postings and finds skills with a "
        "shared dictionary; dbt models them in PostgreSQL.\n"
        "- **NLP**: years of experience (spaCy), embeddings (sentence-transformers) and topics (BERTopic).\n"
        "- **ML**: an XGBoost salary model tracked in MLflow (used only because it beats a per-role median "
        "in cross-validation) and Prophet demand forecasts once enough weeks are collected.\n"
        "- **Your resume** is matched with the same skill dictionary and the same embedding model as the "
        "postings — and never stored."
    )
