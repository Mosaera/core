import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { DiffView } from "../components/DiffView";
import { FindingsList } from "../components/FindingsList";
import { SubmitPage } from "../pages/SubmitPage";

describe("SubmitPage", () => {
  it("renders the dispatch form", () => {
    render(
      <MemoryRouter>
        <SubmitPage />
      </MemoryRouter>,
    );
    expect(screen.getByText("Commission a run")).toBeInTheDocument();
    expect(screen.getByText(/Dispatch run/)).toBeInTheDocument();
  });
});

describe("finding + diff rendering", () => {
  it("marks a clean scan and parses a finding", () => {
    const { rerender } = render(<FindingsList text="No security findings." />);
    expect(screen.getByText("clean")).toBeInTheDocument();

    rerender(
      <FindingsList text={"1 security finding(s):\n- [gitleaks:github-pat] settings.py:2 — token"} />,
    );
    expect(screen.getByText("gitleaks:github-pat")).toBeInTheDocument();
  });

  it("colors diff add/remove lines", () => {
    const { container } = render(<DiffView diff={"@@ -1 +1 @@\n-old\n+new"} />);
    expect(container.querySelector('[data-kind="add"]')?.textContent).toBe("+new");
    expect(container.querySelector('[data-kind="del"]')?.textContent).toBe("-old");
  });
});
