import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../api/client";
import { ProjectDetailPage } from "../pages/ProjectDetailPage";

const mocks = vi.hoisted(() => ({
  getProject: vi.fn(),
  activeRuns: vi.fn(),
  deleteProject: vi.fn(),
  projectBudget: vi.fn(),
  projectCost: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      getProject: mocks.getProject,
      activeRuns: mocks.activeRuns,
      deleteProject: mocks.deleteProject,
      projectBudget: mocks.projectBudget,
      projectCost: mocks.projectCost,
    },
  };
});

function project(over: Partial<Project> = {}): Project {
  return {
    id: "p1", name: "Demo", source_repo: "/tmp/demo", goal: "g", brief: "b",
    status: "active", branch: "mosaera/x", mr_url: "", autonomous: false,
    has_gitlab_token: true, gitlab_token_masked: "glpat-****abcd", error: "",
    created_at: "2026-07-01T00:00:00Z", backlog: [], runs: [], ...over,
  };
}

function renderSettings() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={["/projects/p1/settings"]}>
        <Routes>
          <Route path="/projects/:id/:section" element={<ProjectDetailPage />} />
          <Route path="/" element={<div>projects home</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Click into a settings sub-section (nav is local-state now). */
async function goto(label: string) {
  fireEvent.click(await screen.findByRole("button", { name: label }));
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.getProject.mockResolvedValue(project());
  mocks.activeRuns.mockResolvedValue({ runs: [] });
  mocks.deleteProject.mockResolvedValue({ deleted: "p1" });
  mocks.projectBudget.mockResolvedValue({
    budget_usd: null, budget_tokens: null, spent_usd: 0, spent_tokens: 0,
    cycle_start: "2026-08-01T00:00:00+00:00", resets_at: "2026-09-01T00:00:00+00:00",
    pct: 0, warn: false, over: false, reason: "",
  });
  mocks.projectCost.mockResolvedValue({
    input_tokens: 300_000, output_tokens: 120_000, total_tokens: 420_000, usd: 3.5,
    calls: 84, runs_metered: 7, runs_total: 9, by_agent: [], by_model: [],
  });
});

describe("Project settings", () => {
  // The GitLab credential surface moved to settings/gitlab/* — see gitlab-connect.test.tsx.

  it("General shows lifetime usage (moved from the overview Budgets card, 2026-08-22)", async () => {
    renderSettings();
    // General is the default pane; the lifetime figures render here — the product's one render.
    expect(await screen.findByText("Lifetime usage")).toBeInTheDocument();
    expect(await screen.findByText("84")).toBeInTheDocument();
    expect(screen.getByText("420,000")).toBeInTheDocument();
    expect(screen.getByText("$0.50")).toBeInTheDocument();
    expect(screen.getByText(/7\/9 runs metered/)).toBeInTheDocument();
  });

  it("type-to-confirm: delete stays disabled until the exact project id is typed", async () => {
    renderSettings();
    await goto("Danger zone");
    const del = await screen.findByRole("button", { name: "Delete project" });
    expect(del).toBeDisabled();
    const confirm = screen.getByLabelText("Confirm project id");
    fireEvent.change(confirm, { target: { value: "wrong" } });
    expect(del).toBeDisabled();
    fireEvent.change(confirm, { target: { value: "p1" } });
    expect(del).toBeEnabled();
    fireEvent.click(del);
    await waitFor(() => expect(mocks.deleteProject).toHaveBeenCalledWith("p1"));
    expect(await screen.findByText("projects home")).toBeInTheDocument();
  });

  it("delete blocked by an active run surfaces the 409 inline, never an alert", async () => {
    mocks.deleteProject.mockRejectedValue(
      new Error("409: a run is active on this project; stop it before deleting"),
    );
    const alertSpy = vi.spyOn(window, "alert");
    renderSettings();
    await goto("Danger zone");
    fireEvent.change(await screen.findByLabelText("Confirm project id"), {
      target: { value: "p1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Delete project" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("a run is active");
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("states exactly what deletion does", async () => {
    renderSettings();
    await goto("Danger zone");
    expect(
      await screen.findByText(/Past runs are kept in history but unlinked from the project/),
    ).toBeInTheDocument();
  });
});
