"""How the app words and rounds things (Phase 6 step 4). Pure: no Streamlit, so tested.

Money is shown to the nearest $1,000 (the salary model's typical error is ~$30K,
so more precision would be false). A what-if that would round to $0 reads "no
measurable effect" instead.
"""

from __future__ import annotations

import math
from datetime import date, datetime

NO_EFFECT_BELOW = 500  # dollars: anything smaller rounds to "$0" at $1,000 precision

SENIORITY_LABELS = {
    "intern": "Intern",
    "junior": "Junior (0–1 years)",
    "mid": "Mid-level (2–3 years)",
    "senior": "Senior (4–6 years)",
    "staff_plus": "Staff / principal (7+ years)",
    "manager": "Manager",
    "unknown": "Not sure",
}
OTHER_STATE_LABEL = "Other / not listed"


def role_label(role: str) -> str:
    """'machine learning engineer' → 'Machine Learning Engineer'."""
    return role.title()


def money(value: float | None) -> str:
    """$143,669 → '$144,000'; $14,500 → '$15,000' (half up, not round-half-even); missing → '—'.

    Missing means None or NaN (pandas' empty number, e.g. data analyst's absent BLS median).
    """
    if value is None or math.isnan(value):
        return "—"
    return f"${math.floor(value / 1000 + 0.5) * 1000:,.0f}"


def money_range(low: float, high: float) -> str:
    """'$116,000 – $171,000'."""
    return f"{money(low)} – {money(high)}"


def signed_money(value: float) -> str:
    """+15000 → '+$15,000'; -6000 → '-$6,000'."""
    sign = "+" if value >= 0 else "-"
    return f"{sign}{money(abs(value))}"


def model_impact_text(value: float | None) -> str:
    """The model's what-if for one missing skill, in words.

    Args:
        value: Dollars, or None when the model can't say (not a what-if skill for the
            role, or the model isn't used).

    Returns:
        'not enough data', 'no measurable effect', or a signed amount.
    """
    if value is None:
        return "not enough data"
    if abs(value) < NO_EFFECT_BELOW:
        return "no measurable effect"
    return signed_money(value)


def median_difference_text(value: float | None, n_with: int, n_without: int) -> str:
    """Within-role median salary with vs without a skill, with its sample sizes.

    Args:
        value: Dollars, or None when either side has too few salaries.
        n_with: Salaried postings mentioning the skill.
        n_without: Salaried postings not mentioning it.

    Returns:
        e.g. '+$15,000 (20 vs 30 postings)' or 'too few salaries to compare'.
    """
    if value is None:
        return "too few salaries to compare"
    return f"{signed_money(value)} ({n_with} vs {n_without} postings)"


def percent(share: float) -> str:
    """0.3449 → '34%'."""
    return f"{share:.0%}"


def window_text(attrs: dict) -> str:
    """Explain which postings match_postings searched (its frame.attrs).

    Args:
        attrs: {'window': 'last_7_days' | 'latest_collection' | 'none', 'since': date | None}.

    Returns:
        One sentence for the page.
    """
    since = attrs.get("since")
    when = f"{since:%b} {since.day}" if isinstance(since, date) else ""
    if attrs.get("window") == "last_7_days":
        return f"Postings collected in the last 7 days (since {when})."
    if attrs.get("window") == "latest_collection":
        return (
            f"No postings for this role were collected in the last 7 days, so these come from its "
            f"latest collection ({when}). The free data plan refreshes each role about every 5 days."
        )
    return "No postings for this role yet."


def age_text(latest: datetime, now: datetime) -> str:
    """How long ago the newest posting was collected: 'today', '1 day ago', '3 days ago'."""
    days = (now.date() - latest.date()).days
    if days <= 0:
        return "today"
    return "1 day ago" if days == 1 else f"{days} days ago"
