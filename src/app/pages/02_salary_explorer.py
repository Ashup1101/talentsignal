"""Salary Explorer: posted salary ranges per role, by level and state, next to BLS medians."""

from src.app import ui  # first: pins OMP_NUM_THREADS before PyTorch / XGBoost load

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src.app import data, logic  # noqa: E402
from src.app import formatting as fmt  # noqa: E402

ui.setup_page("Salary Explorer", ":material/payments:")
st.title("Salary Explorer")
st.write(
    "Salaries posted in job ads (the midpoint of each posted range, per year), by role, "
    "next to the national median from the U.S. Bureau of Labor Statistics (BLS)."
)

postings = ui.load(data.postings, "the job postings")
bands = ui.load(data.salary_bands, "the salary bands")

levels = [s for s in fmt.SENIORITY_LABELS if s in set(postings["seniority_effective"])]
states = sorted(s for s in postings["state_code"].dropna().unique())
f1, f2 = st.columns(2)
seniority = f1.selectbox(
    "Level", [None, *levels], format_func=lambda s: "All levels" if s is None else fmt.SENIORITY_LABELS[s]
)
state = f2.selectbox("State", [None, *states], format_func=lambda s: "All states" if s is None else s)

table = logic.salary_bands_for(postings, bands, seniority=seniority, state=state)
shown = table[table["sample_status"] == "ok"]
too_few = table[table["sample_status"] != "ok"]

if shown.empty:
    st.warning("Fewer than 5 posted salaries for every role with these filters; try a broader selection.")
else:
    chart_data = shown.assign(role=shown["role_name"].map(fmt.role_label))
    bars = alt.Chart(chart_data).mark_bar(opacity=0.35, size=26).encode(
        y=alt.Y("role:N", title=None, sort="-x"),
        x=alt.X("salary_p25:Q", title="Annual salary (USD)", axis=alt.Axis(format="$,.0f")),
        x2="salary_p75:Q",
        tooltip=[
            alt.Tooltip("role:N", title="Role"),
            alt.Tooltip("salary_p25:Q", title="25th percentile", format="$,.0f"),
            alt.Tooltip("salary_median:Q", title="Median", format="$,.0f"),
            alt.Tooltip("salary_p75:Q", title="75th percentile", format="$,.0f"),
            alt.Tooltip("n_salaries:Q", title="Posted salaries"),
        ],
    )
    medians = alt.Chart(chart_data).mark_tick(thickness=3, size=30).encode(
        y=alt.Y("role:N", sort="-x"), x="salary_median:Q"
    )
    bls = alt.Chart(chart_data.dropna(subset=["bls_median"])).mark_point(shape="diamond", size=90, filled=True).encode(
        y=alt.Y("role:N", sort="-x"),
        x="bls_median:Q",
        color=alt.value("#d62728"),
        tooltip=[alt.Tooltip("bls_median:Q", title="BLS national median", format="$,.0f")],
    )
    st.altair_chart(bars + medians + bls, width="stretch")
    st.caption("Bar: middle half of posted salaries (25th–75th percentile). Tick: median. Red diamond: BLS median.")

    st.dataframe(
        pd.DataFrame(
            {
                "Role": shown["role_name"].map(fmt.role_label),
                "Posted salaries": shown["n_salaries"],
                "25th percentile": shown["salary_p25"].map(fmt.money),
                "Median": shown["salary_median"].map(fmt.money),
                "75th percentile": shown["salary_p75"].map(fmt.money),
                "BLS median": shown["bls_median"].map(fmt.money),
                "Median vs BLS": shown["median_vs_bls_pct"].map(lambda v: "—" if pd.isna(v) else f"{v:+.0%}"),
            }
        ),
        hide_index=True,
    )

if not too_few.empty:
    st.caption(
        "Too few posted salaries (under 5) to report: "
        + ", ".join(f"{fmt.role_label(r.role_name)} ({r.n_salaries})" for r in too_few.itertuples())
        + "."
    )
st.caption(
    "Posted salaries run above BLS medians: the postings come from five large metros and lean senior, and "
    "BLS covers every employer nationwide. Data analyst has no BLS benchmark (no matching occupation code)."
)
