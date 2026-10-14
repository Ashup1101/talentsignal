"""Resume Analyzer: upload a resume PDF → skills, match % per role, salary, missing skills, matches.

The resume is read in memory only (never cached, saved or logged). Calculations live
in src/app/logic.py; this page only lays them out.
"""

from src.app import ui  # first: pins OMP_NUM_THREADS before PyTorch / XGBoost load

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src.app import data, logic  # noqa: E402
from src.app import formatting as fmt  # noqa: E402
from src.ml import embeddings, resume_features  # noqa: E402
from src.ml.features import UNKNOWN, FeatureSpec  # noqa: E402

ui.setup_page("Resume Analyzer", ":material/description:")
st.title("Resume Analyzer")
st.write("See how your resume compares with what real job postings ask for.")
ui.privacy_note()

card = ui.load(data.salary_model_card, "the salary model")
demand = ui.load(data.skill_demand, "skill demand")
spec = FeatureSpec.from_dict(card["feature_spec"])
roles = sorted(card["baselines"]["role_median"])
seniorities = [s for s in fmt.SENIORITY_LABELS if s != UNKNOWN] + [UNKNOWN]
states = [s for s in spec.states if s != UNKNOWN] + [None]

c1, c2, c3, c4 = st.columns([3, 3, 2, 2])
role = c1.selectbox("Target role", roles, index=roles.index("data engineer"), format_func=fmt.role_label)
seniority = c2.selectbox(
    "Your level", seniorities, index=seniorities.index("mid"), format_func=fmt.SENIORITY_LABELS.get
)
state = c3.selectbox("State", states, format_func=lambda s: s or fmt.OTHER_STATE_LABEL)
remote = c4.toggle("Remote", help="Looking for remote work")

uploaded = st.file_uploader("Your resume (PDF with selectable text, up to 5 MB)", type="pdf")
if st.button("No resume at hand? Try a sample resume", icon=":material/science:"):
    st.session_state["use_sample"] = True
if uploaded is not None:
    st.session_state["use_sample"] = False

if uploaded is not None:
    pdf_bytes, source = uploaded.getvalue(), "your resume"
elif st.session_state.get("use_sample"):
    pdf_bytes, source = ui.SAMPLE_RESUME.read_bytes(), "the sample resume (a made-up data engineer)"
else:
    st.info("Upload a PDF to begin.", icon=":material/upload_file:")
    st.stop()

try:
    text = resume_features.extract_text(pdf_bytes)
except resume_features.NoTextError as exc:
    st.error(str(exc))
    st.stop()
except ValueError as exc:
    st.error(f"{exc} Please upload a PDF file.")
    st.stop()
skills = resume_features.find_skills(text)

# --- Skills found -------------------------------------------------------------------
st.header("Skills found", divider="gray")
st.caption(f"In {source}, using the same skill dictionary that reads every job posting.")
if not skills:
    st.warning(
        "No skills from our dictionary were found. The dictionary covers ~110 data and software skills "
        "(SQL, Python, Spark, Tableau, AWS, …); if your resume is a scanned image, its text can't be read."
    )
role_demand = demand[demand["role_name"] == role].set_index("skill_name")
found = pd.DataFrame(
    {
        "Skill": skills,
        f"Share of {fmt.role_label(role)} postings": [
            float(role_demand["share_of_role_postings"].get(s, 0.0)) for s in skills
        ],
    }
).sort_values(f"Share of {fmt.role_label(role)} postings", ascending=False)
st.dataframe(
    found,
    hide_index=True,
    column_config={
        f"Share of {fmt.role_label(role)} postings": st.column_config.ProgressColumn(
            format="percent", min_value=0.0, max_value=1.0
        )
    },
)

# --- Match % per role -----------------------------------------------------------------
st.header("Match by role", divider="gray")
st.caption(
    "Each role's core skills are those in at least 10% of its postings; the match weighs each one by how "
    "often postings ask for it."
)
matches = pd.DataFrame(
    {"Role": [fmt.role_label(r) for r in roles], "Match": [logic.match_pct(skills, r, demand) for r in roles]}
).sort_values("Match", ascending=False)
st.dataframe(
    matches,
    hide_index=True,
    column_config={"Match": st.column_config.ProgressColumn(format="percent", min_value=0.0, max_value=1.0)},
)
core = logic.core_skills(skills, role, demand)
with st.expander(f"{fmt.role_label(role)}: {int(core['on_resume'].sum())} of {len(core)} core skills on your resume"):
    st.dataframe(
        core.rename(
            columns={"skill_name": "Skill", "share_of_role_postings": "Share of postings", "on_resume": "On resume"}
        )[["Skill", "Share of postings", "On resume"]],
        hide_index=True,
        column_config={
            "Share of postings": st.column_config.ProgressColumn(format="percent", min_value=0.0, max_value=1.0)
        },
    )

# --- Salary ---------------------------------------------------------------------------
st.header("Estimated salary", divider="gray")
salary = logic.predict_salary_for_resume(
    skills, role, seniority, state, remote, card, ui.load(data.salary_model_json, "the salary model")
)
s1, s2 = st.columns(2)
level = fmt.SENIORITY_LABELS[seniority].split(" (")[0].lower()
s1.metric(f"{fmt.role_label(role)}, {level}", fmt.money(salary["salary"]))
s1.caption(
    f"Likely range {fmt.money_range(salary['low'], salary['high'])}: ± the model's typical error for this role "
    f"({fmt.money(salary['typical_error'])}, from cross-validation)."
)
s2.metric(f"Median posted salary, all {fmt.role_label(role)} postings", fmt.money(salary["role_median"]))
if salary["method"] == "role_median":
    st.info(
        "The salary model didn't beat this simple median in testing, so the estimate is the role median.",
        icon=":material/info:",
    )
st.caption(
    "Estimated from salaries posted in job ads (mostly large U.S. metros), not from offers or pay surveys."
)

# --- Missing skills -------------------------------------------------------------------
st.header("Top skills to add", divider="gray")
st.caption(
    f"The most in-demand {fmt.role_label(role)} skills missing from your resume. Salary figures are "
    "associations in posted salaries, not promises: postings that ask for a skill can differ in other ways."
)
missing = logic.top_missing_skills(
    skills, role, demand, card, ui.salary_model(), spec, seniority=seniority, state=state, remote=remote
)
if not missing:
    st.success("Your resume already covers every skill these postings ask for.")
for item in missing:
    with st.container(border=True):
        a, b, c = st.columns([2, 2, 3])
        a.markdown(f"**{item['skill']}**")
        a.caption(f"In {fmt.percent(item['share_of_role_postings'])} of {fmt.role_label(role)} postings")
        b.markdown("Salary model what-if")
        b.markdown(f"**{fmt.model_impact_text(item['model_impact'])}**")
        c.markdown("Median posted salary, with vs without it")
        c.markdown(
            "**"
            + fmt.median_difference_text(
                item["median_salary_difference"], item["n_salaried_with_skill"], item["n_salaried_without_skill"]
            )
            + "**"
        )

# --- Matching postings ----------------------------------------------------------------
st.header("Matching job postings", divider="gray")
with st.spinner("Comparing your resume with recent postings…"):
    resume_vector = embeddings.embed_texts([text])[0]
    matched = logic.match_postings(
        resume_vector,
        ui.load(data.posting_embeddings, "the posting embeddings"),
        ui.load(data.postings, "the job postings"),
        role,
        top_n=10,
        resume_skills=skills,
    )
st.caption(fmt.window_text(matched.attrs) + " Ranked by similarity of meaning, not just shared keywords.")
if not matched.empty:
    st.dataframe(
        pd.DataFrame(
            {
                "Similarity": matched["similarity"],
                "Job": matched["job_title"],
                "Employer": matched["employer_name"],
                "Location": matched["location_name"],
                "Shared skills": [", ".join(s) for s in matched["shared_skills"]],
                "Apply": matched["apply_link"],
            }
        ),
        hide_index=True,
        column_config={
            "Similarity": st.column_config.ProgressColumn(format="%.2f", min_value=0.0, max_value=1.0),
            "Apply": st.column_config.LinkColumn(display_text="Open posting"),
        },
    )
