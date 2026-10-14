// How the app words and rounds numbers. The API decides (statuses); this only formats.
// Money is shown to the nearest $1,000: the salary model's typical error is ~$30K.

/** $143,669 → "$144,000"; ±$14,500 → "±$15,000" (halves away from zero); missing → "—". */
export function money(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const thousands = Math.floor(Math.abs(value) / 1000 + 0.5);
  return `${value < 0 && thousands > 0 ? "-" : ""}$${(thousands * 1000).toLocaleString("en-US")}`;
}

/** +15000 → "+$15,000"; -6000 → "-$6,000". */
export function signedMoney(value: number): string {
  return `${value < 0 ? "-" : "+"}${money(Math.abs(value))}`;
}

/** 0.3449 → "34%". */
export function percent(share: number | null | undefined): string {
  if (share === null || share === undefined || Number.isNaN(share)) return "—";
  return `${Math.round(share * 100)}%`;
}

/** "machine learning engineer" → "Machine Learning Engineer". */
export function roleLabel(role: string): string {
  return role.replace(/\b\w/g, (c) => c.toUpperCase());
}

export const LEVEL_SHORT: Record<string, string> = {
  intern: "Intern",
  junior: "Junior",
  mid: "Mid-level",
  senior: "Senior",
  staff_plus: "Staff+",
  manager: "Manager",
  unknown: "Level not stated",
};

export function levelLabel(level: string | null | undefined): string {
  return level ? (LEVEL_SHORT[level] ?? level) : "Level not stated";
}

/** The salary model's what-if for a missing skill, in words (status decided by the API). */
export function impactText(status: string, value: number | null | undefined): string {
  if (status === "no_measurable_effect") return "No measurable effect";
  if (status === "value" && value !== null && value !== undefined) return signedMoney(value);
  return "Not enough data";
}

/** Within-role median salary with vs without a skill, with its sample sizes. */
export function medianDifferenceText(
  status: string,
  value: number | null | undefined,
  nWith: number,
  nWithout: number,
): string {
  if (status !== "ok" || value === null || value === undefined) return "Too few salaries to compare";
  return `${signedMoney(value)} (${nWith} vs ${nWithout} postings)`;
}

/** Which postings the match searched (MatchingPostings.window / since). */
export function windowText(window: string, since: string | null | undefined): string {
  const when = since
    ? new Date(`${since}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })
    : "";
  if (window === "last_7_days") return `Postings collected in the last 7 days (since ${when}).`;
  if (window === "latest_collection")
    return `No postings for this role were collected in the last 7 days, so these come from its latest collection (${when}). The free data plan refreshes each role about every 5 days.`;
  return "No postings for this role yet.";
}

/** "today", "1 day ago", "3 days ago". */
export function ageText(iso: string, now: Date = new Date()): string {
  const days = Math.floor(
    (Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()) -
      Date.UTC(new Date(iso).getUTCFullYear(), new Date(iso).getUTCMonth(), new Date(iso).getUTCDate())) /
      86_400_000,
  );
  if (days <= 0) return "today";
  return days === 1 ? "1 day ago" : `${days} days ago`;
}
