import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StackedBar } from "./stacked-bar";

describe("StackedBar", () => {
  const segments = [
    { key: "junior", label: "Junior", value: 30, className: "bg-a" },
    { key: "senior", label: "Senior", value: 65, className: "bg-b" },
    { key: "intern", label: "Intern", value: 5, className: "bg-c" },
    { key: "manager", label: "Manager", value: 0, className: "bg-d" },
  ];

  it("normalizes counts to shares and describes them for screen readers", () => {
    render(<StackedBar label="Levels" segments={segments} />);

    expect(screen.getByRole("img", { name: "Levels: Junior 30%, Senior 65%, Intern 5%" })).toBeInTheDocument();
    expect(screen.getByTitle("Senior: 65%")).toHaveStyle({ width: "65%" });
    expect(screen.queryByTitle(/^Manager/)).toBeNull(); // empty segments aren't drawn
  });

  it("prints shares only where a segment is wide enough to hold them", () => {
    render(<StackedBar label="Levels" segments={segments} showValues />);

    expect(screen.getByTitle("Junior: 30%")).toHaveTextContent("30%");
    expect(screen.getByTitle("Intern: 5%")).toBeEmptyDOMElement();
  });
});
