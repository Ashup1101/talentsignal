import { describe, expect, it } from "vitest";

import { ageText, impactText, medianDifferenceText, money, percent, roleLabel, signedMoney, windowText } from "./format";

describe("money", () => {
  it("rounds to the nearest $1,000, halves away from zero", () => {
    expect(money(143_669)).toBe("$144,000");
    expect(money(14_500)).toBe("$15,000");
    expect(money(-14_500)).toBe("-$15,000");
    expect(money(499)).toBe("$0");
  });
  it("shows a dash for missing values", () => {
    expect(money(null)).toBe("—");
    expect(money(undefined)).toBe("—");
    expect(money(Number.NaN)).toBe("—");
  });
  it("signs differences", () => {
    expect(signedMoney(15_250)).toBe("+$15,000");
    expect(signedMoney(-6_000)).toBe("-$6,000");
  });
});

describe("wording decided by the API's statuses", () => {
  it("words the model what-if", () => {
    expect(impactText("no_measurable_effect", 0)).toBe("No measurable effect");
    expect(impactText("not_enough_data", null)).toBe("Not enough data");
    expect(impactText("value", 4_200)).toBe("+$4,000");
  });
  it("words the median difference with its sample sizes", () => {
    expect(medianDifferenceText("ok", 35_000, 12, 51)).toBe("+$35,000 (12 vs 51 postings)");
    expect(medianDifferenceText("too_few_salaries", null, 9, 54)).toBe("Too few salaries to compare");
  });
});

describe("labels", () => {
  it("formats roles, shares, windows and ages", () => {
    expect(roleLabel("machine learning engineer")).toBe("Machine Learning Engineer");
    expect(percent(0.3449)).toBe("34%");
    expect(windowText("last_7_days", "2026-10-07")).toBe("Postings collected in the last 7 days (since Oct 7).");
    expect(windowText("latest_collection", "2026-10-03")).toContain("latest collection (Oct 3)");
    expect(windowText("none", null)).toBe("No postings for this role yet.");
    const now = new Date("2026-10-14T09:00:00Z");
    expect(ageText("2026-10-14T01:00:00Z", now)).toBe("today");
    expect(ageText("2026-10-13T22:00:00Z", now)).toBe("1 day ago");
    expect(ageText("2026-10-03T00:00:00Z", now)).toBe("11 days ago");
  });
});
