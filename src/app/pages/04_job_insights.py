"""Job Insights: topics found in the postings, role mix per topic, seniority and remote work."""

from src.app import ui  # first: pins OMP_NUM_THREADS before PyTorch / XGBoost load

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src.app import data, logic  # noqa: E402
from src.app import formatting as fmt  # noqa: E402

ui.setup_page("Job Insights", ":material/hub:")
st.title("Job Insights")
st.write("What the postings are about, beyond the five job titles we search for.")

topics = ui.load(data.job_insights, "the topics")
postings = ui.load(data.postings, "the job postings")

# --- Topics ---------------------------------------------------------------------------
st.header("Topics", divider="gray")
unassigned = topics.loc[topics["topic_id"] < 0, "share_of_postings"].sum()
st.caption(
    "Found by BERTopic from the meaning of each posting's text (shared boilerplate removed). Keywords "
    f"describe each group; they didn't define it. {fmt.percent(unassigned)} of postings fit no clear topic, "
    "and topics are re-estimated every night, so they can shift as new postings arrive."
)
named = topics[topics["topic_id"] >= 0].sort_values("n_postings", ascending=False)
st.dataframe(
    pd.DataFrame(
        {
            "Topic": named["topic_label"],
            "Postings": named["n_postings"],
            "Share of all postings": named["share_of_postings"],
            "Keywords": named["top_words"].map(lambda words: ", ".join(words[:8])),
        }
    ),
    hide_index=True,
    column_config={
        "Share of all postings": st.column_config.ProgressColumn(format="percent", min_value=0.0, max_value=1.0)
    },
)

mix = logic.topic_role_mix(postings)
if not mix.empty:
    st.subheader("Which roles each topic comes from")
    heat = alt.Chart(mix.assign(role=mix["role_name"].map(fmt.role_label))).mark_rect().encode(
        x=alt.X("role:N", title=None),
        y=alt.Y("topic_label:N", title=None),
        color=alt.Color("share_of_topic:Q", title="Share of topic", scale=alt.Scale(scheme="blues")),
        tooltip=[
            alt.Tooltip("topic_label:N", title="Topic"),
            alt.Tooltip("role:N", title="Role"),
            alt.Tooltip("n_postings:Q", title="Postings"),
            alt.Tooltip("share_of_topic:Q", title="Share of topic", format=".0%"),
        ],
    )
    st.altair_chart(heat, width="stretch")

# --- Seniority and remote work ----------------------------------------------------------
st.header("Seniority and remote work", divider="gray")
left, right = st.columns(2)
with left:
    st.subheader("Level asked for")
    levels = postings.assign(
        role=postings["role_name"].map(fmt.role_label),
        level=postings["seniority_effective"].map(lambda s: fmt.SENIORITY_LABELS.get(s, s).split(" (")[0]),
    )
    st.altair_chart(
        alt.Chart(levels).mark_bar().encode(
            y=alt.Y("role:N", title=None),
            x=alt.X("count():Q", stack="normalize", title="Share of postings", axis=alt.Axis(format="%")),
            color=alt.Color(
                "level:N", title="Level", sort=[label.split(" (")[0] for label in fmt.SENIORITY_LABELS.values()]
            ),
            tooltip=["role:N", "level:N", "count():Q"],
        ),
        width="stretch",
    )
    st.caption("From the job title when it states a level, otherwise from the years of experience asked for.")
with right:
    st.subheader("Remote postings")
    remote = (
        postings.groupby("role_name")["is_remote"].mean().rename("share").reset_index()
        .assign(role=lambda f: f["role_name"].map(fmt.role_label))
    )
    st.altair_chart(
        alt.Chart(remote).mark_bar().encode(
            y=alt.Y("role:N", title=None, sort="-x"),
            x=alt.X("share:Q", title="Share of postings that are remote", axis=alt.Axis(format="%")),
            tooltip=[alt.Tooltip("role:N"), alt.Tooltip("share:Q", format=".0%")],
        ),
        width="stretch",
    )
    st.caption(f"{fmt.percent(postings['is_remote'].mean())} of all postings are remote.")
