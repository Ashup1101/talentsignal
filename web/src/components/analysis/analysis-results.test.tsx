import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import type { Analysis } from "@/lib/api";

import { AnalysisResults } from "./analysis-results";

function fixture(overrides: Partial<Analysis> = {}): Analysis {
  return {
    role: "data analyst",
    level: "junior",
    skills: [
      { skill: "SQL", share_of_role_postings: 0.67, demand_rank: 1 },
      { skill: "dbt", share_of_role_postings: 0, demand_rank: null },
    ],
    role_matches: [
      { role: "data analyst", match: 0.82 },
      { role: "data engineer", match: 0.41 },
    ],
    core_skills: [
      { skill: "SQL", share_of_role_postings: 0.67, on_resume: true },
      { skill: "Statistics", share_of_role_postings: 0.47, on_resume: false },
    ],
    salary: {
      estimate: 121_650,
      low: 99_093,
      high: 144_207,
      typical_error: 22_557,
      method: "model",
      role_median: 115_000,
      level_median: { median: 79_200, n: 5, status: "ok" },
      model_run_id: "run",
    },
    missing_skills: [
      {
        skill: "Data Modeling", skill_category: "data_engineering", share_of_role_postings: 0.45, demand_rank: 3,
        model_impact: 0, model_impact_status: "no_measurable_effect",
        median_salary_difference: null, median_difference_status: "too_few_salaries",
        n_salaried_with_skill: 9, n_salaried_without_skill: 54,
      },
      {
        skill: "dbt", skill_category: "data_engineering", share_of_role_postings: 0.3, demand_rank: 4,
        model_impact: 11_200, model_impact_status: "value",
        median_salary_difference: 35_000, median_difference_status: "ok",
        n_salaried_with_skill: 12, n_salaried_without_skill: 51,
      },
    ],
    postings: {
      window: "latest_collection",
      since: "2026-10-03",
      items: [
        {
          job_id: "a", title: "Data Analyst II", employer: "Shirley Ryan", location: "Chicago, IL", remote: false,
          level: "mid", near_level: true, similarity: 0.71, shared_skills: ["SQL", "Tableau"], salary: null,
          apply_link: "https://jobs.example/a",
        },
        {
          job_id: "b", title: "Data Analytics Manager", employer: "Capital One", location: "New York, NY", remote: true,
          level: "manager", near_level: false, similarity: 0.8, shared_skills: [], salary: null, apply_link: null,
        },
      ],
    },
    ...overrides,
  };
}

function renderResults(analysis: Analysis) {
  return render(
    <TooltipProvider>
      <AnalysisResults analysis={analysis} />
    </TooltipProvider>,
  );
}

describe("AnalysisResults", () => {
  it("puts the estimate next to the posted median for the user's level", () => {
    renderResults(fixture());

    expect(screen.getAllByText("$122,000").length).toBeGreaterThan(0);
    expect(screen.getByText("Posted median, Data Analyst, junior")).toBeInTheDocument();
    expect(screen.getByText("$79,000 (5 postings)")).toBeInTheDocument();
    expect(screen.getByText("$115,000")).toBeInTheDocument();
  });

  it("asks for a level instead of showing a median that doesn't describe the user", () => {
    renderResults(fixture({ level: "unknown", salary: { ...fixture().salary, level_median: { median: null, n: 0, status: "no_level" } } }));

    expect(screen.getByText("choose your level to see it")).toBeInTheDocument();
  });

  it("words missing skills from the API's statuses", () => {
    renderResults(fixture());

    const modeling = screen.getByText("Data Modeling").closest("[data-slot=card]") as HTMLElement;
    expect(within(modeling).getByText("No measurable effect")).toBeInTheDocument();
    expect(within(modeling).getByText("Too few salaries to compare")).toBeInTheDocument();
    const dbt = screen.getAllByText("dbt").map((el) => el.closest("[data-slot=card]")).find((c) => c?.textContent?.includes("what-if")) as HTMLElement;
    expect(within(dbt).getByText("+$11,000")).toBeInTheDocument();
    expect(within(dbt).getByText("+$35,000 (12 vs 51 postings)")).toBeInTheDocument();
  });

  it("lists postings with their level and apply links, explaining the window", () => {
    renderResults(fixture());

    expect(screen.getByText(/latest collection \(Oct 3\)/)).toBeInTheDocument();
    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("Data Analyst II")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Mid-level")).toBeInTheDocument();
    expect(within(rows[0]).getByRole("link", { name: /Open the posting/ })).toHaveAttribute("href", "https://jobs.example/a");
    expect(within(rows[1]).queryByRole("link")).toBeNull();
  });
});
