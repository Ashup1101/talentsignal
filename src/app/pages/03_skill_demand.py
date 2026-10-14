"""Skill Demand: which skills each role asks for, and the demand forecast's status."""

from src.app import ui  # first: pins OMP_NUM_THREADS before PyTorch / XGBoost load

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src.app import data  # noqa: E402
from src.app import formatting as fmt  # noqa: E402

MIN_WEEKS_TO_FORECAST = 12  # src/ml/demand_forecast.py (not imported: it needs Prophet)

ui.setup_page("Skill Demand", ":material/trending_up:")
st.title("Skill Demand")
st.write("How often each role's postings mention each skill, and where demand is heading.")

demand = ui.load(data.skill_demand, "skill demand")
forecast = ui.load(data.skill_demand_forecast, "the demand forecast")
roles = sorted(demand["role_name"].unique())
role = st.selectbox("Role", roles, index=roles.index("data engineer"), format_func=fmt.role_label)

rows = demand[demand["role_name"] == role].sort_values("demand_rank")
st.subheader(f"What {fmt.role_label(role)} postings ask for")
st.caption(f"Share of the role's {int(rows['n_role_postings'].iloc[0]):,} postings that mention each skill.")
st.dataframe(
    pd.DataFrame(
        {
            "Rank": rows["demand_rank"],
            "Skill": rows["skill_name"],
            "Category": rows["skill_category"].str.replace("_", " "),
            "Share of postings": rows["share_of_role_postings"],
            "Postings": rows["n_postings_with_skill"],
        }
    ),
    hide_index=True,
    column_config={
        "Share of postings": st.column_config.ProgressColumn(format="percent", min_value=0.0, max_value=1.0)
    },
    height=420,
)

st.subheader("Demand forecast")
role_fc = forecast[forecast["search_role"] == role]
weeks = int(role_fc["observed_weeks"].max()) if not role_fc.empty else 0
forecasting = sorted(role_fc.loc[role_fc["forecast_status"] == "forecast", "skill_name"].unique())
st.progress(
    min(weeks / MIN_WEEKS_TO_FORECAST, 1.0),
    text=f"{weeks} of {MIN_WEEKS_TO_FORECAST} weekly collections for {fmt.role_label(role)}",
)
if not forecasting:
    st.info(
        f"Forecasts start once a skill has {MIN_WEEKS_TO_FORECAST} weekly data points; the nightly pipeline "
        f"adds about one per week. Until then, the shares above are the current picture.",
        icon=":material/hourglass_top:",
    )
else:
    skill = st.selectbox("Skill", forecasting)
    history = ui.load(data.skill_demand_history, "the demand history")
    past = history[(history["search_role"] == role) & (history["skill_name"] == skill)]
    future = role_fc[(role_fc["skill_name"] == skill) & (role_fc["forecast_status"] == "forecast")]
    observed = alt.Chart(past).mark_line(point=True).encode(
        x=alt.X("collection_week:T", title="Week"),
        y=alt.Y("share_of_role_postings:Q", title="Share of postings", axis=alt.Axis(format="%")),
    )
    band = alt.Chart(future).mark_area(opacity=0.25).encode(
        x="forecast_week:T", y="share_lower:Q", y2="share_upper:Q"
    )
    line = alt.Chart(future).mark_line(strokeDash=[5, 4]).encode(x="forecast_week:T", y="share_forecast:Q")
    st.altair_chart(observed + band + line, width="stretch")
    st.caption("Solid: observed weekly share. Dashed: Prophet forecast (linear trend) with a 95% interval.")
