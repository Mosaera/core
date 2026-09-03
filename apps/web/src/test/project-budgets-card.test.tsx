import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { Project, ProjectBudgetStatus, ProjectCost } from "../api/client";
import { ProjectBudgetsCard } from "../components/overview/ProjectBudgetsCard";

const mocks = vi.hoisted(() => ({
  projectBudget: vi.fn(),
  projectCost: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return {
    ...mod,
    api: { ...mod.api, projectBudget: mocks.projectBudget, projectCost: mocks.projectCost },
  };
});

const PROJECT = { id: "p1" } as Project;

function budget(over: Partial<ProjectBudgetStatus> = {}): ProjectBudgetStatus {
  return {
    budget_usd: null, budget_tokens: null, spent_usd: 3.5, spent_tokens: 420_000,
    cycle_start: "2026-08-01T00:00:00+00:00", resets_at: "2026-09-01T00:00:00+00:00",
    pct: 0, warn: false, over: false, reason: "", ...over,
  };
}

function cost(over: Partial<ProjectCost> = {}): ProjectCost {
  return {
    input_tokens: 300_000, output_tokens: 120_000, total_tokens: 420_000, usd: 3.5,
    calls: 84, runs_metered: 7, runs_total: 9, by_agent: [], by_model: [], ...over,
  };
}

function renderCard() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <ProjectBudgetsCard project={PROJECT} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ProjectBudgetsCard", () => {
  it("shows the month's spend honestly when no cap is configured", async () => {
    mocks.projectBudget.mockResolvedValue(budget());
    mocks.projectCost.mockResolvedValue(cost());
    renderCard();
    // Spend appears WITHOUT a cap — the API reports it either way (capless-spend fix).
    expect(await screen.findByText(/\$3\.50 · 420,000 tokens/)).toBeInTheDocument();
    expect(screen.getByText("no budget set")).toBeInTheDocument();
    // The LIFETIME block moved to project Settings → General (redundancy audit 2026-08-22);
    // its assertions live in settings.test.tsx now. The overview card keeps only the month.
    expect(screen.queryByText("Lifetime")).not.toBeInTheDocument();
    expect(screen.getByText("Edit budgets")).toHaveAttribute("href", "/projects/p1/settings");
  });

  it("renders cap meters and the warn badge when spend crosses 80%", async () => {
    mocks.projectBudget.mockResolvedValue(
      budget({ budget_usd: 4.0, pct: 0.875, warn: true }),
    );
    mocks.projectCost.mockResolvedValue(cost());
    renderCard();
    expect(await screen.findByText("88% used")).toBeInTheDocument();
    expect(screen.getByText("$3.50 / $4.00")).toBeInTheDocument();
  });

  it("renders the over badge at the cap", async () => {
    mocks.projectBudget.mockResolvedValue(
      budget({ budget_tokens: 400_000, pct: 1.05, warn: true, over: true, reason: "tokens" }),
    );
    mocks.projectCost.mockResolvedValue(cost());
    renderCard();
    expect(await screen.findByText("Over budget")).toBeInTheDocument();
    expect(screen.getByText("420,000 / 400,000")).toBeInTheDocument();
  });
});
