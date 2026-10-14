import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RangeChart } from "./salaries-view";

describe("RangeChart", () => {
  it("draws each role's range, median and BLS marker on one scale", () => {
    render(
      <RangeChart
        bands={[
          { role: "data engineer", n_salaries: 53, p25: 143_000, median: 162_500, p75: 205_000, bls_median: 139_500, median_vs_bls: 0.16, status: "ok" },
          { role: "data analyst", n_salaries: 63, p25: 90_000, median: 115_000, p75: 139_000, bls_median: null, median_vs_bls: null, status: "ok" },
        ]}
      />,
    );

    expect(screen.getByRole("img", { name: "Posted salary ranges by role" })).toBeInTheDocument();
    expect(screen.getByTitle("$143,000 – $205,000")).toBeInTheDocument();
    expect(screen.getByTitle("Median $163,000")).toBeInTheDocument();
    expect(screen.getByTitle("BLS median $140,000")).toBeInTheDocument();
    expect(screen.queryAllByTitle(/^BLS median/)).toHaveLength(1); // data analyst has no BLS benchmark
  });
});
