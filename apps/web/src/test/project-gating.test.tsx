import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { App } from "../App";

// An initializing (status "ready") project: only Start + Settings should show.
vi.mock("../api/client", () => ({
  api: {
    listProjects: () => Promise.resolve({ projects: [] }),
    getProject: (id: string) =>
      Promise.resolve({
        id,
        name: "Fresh Project",
        source_repo: "src",
        status: "ready",
        backlog: [],
        runs: [],
        created_at: null,
      }),
    activeRuns: () => Promise.resolve({ runs: [] }),
    projectMessages: () => Promise.resolve({ messages: [] }),
    projectMrStatus: () => Promise.resolve({ state: null, url: "" }),
  },
}));
// Stub the chat panel so the Start surface renders without the full chat stack.
// The setup checklist has its own suite (setup-panel.test.tsx); this file is about tab gating.
vi.mock("../components/start/SetupPanel", () => ({ SetupPanel: () => null }));
vi.mock("../components/pm/PmChatPanel", () => ({ PmChatPanel: () => <div>chat</div> }));
// Chrome, not the subject: `SetupBanner` polls `/api/preflight` through `api/firstRun`,
// which this suite does not mock (it mocks `api/client`). Stubbed like `SetupPanel`
// above — an unmocked fetch in jsdom raises "Invalid URL" and fails the run on an
// unhandled error even while every assertion passes.
vi.mock("../components/setup/SetupBanner", () => ({ SetupBanner: () => null }));

function renderAt(path: string) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("initialize-phase gating", () => {
  it("shows only Start + Settings tabs (no Backlog/Overview) for a fresh project", async () => {
    renderAt("/projects/p1/start");
    // Wait until the project resolves and the sidebar filters down (the full-list
    // Backlog/Overview tabs disappear).
    await waitFor(() => expect(screen.queryByText("Backlog")).not.toBeInTheDocument());
    expect(screen.getAllByText("Start").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Settings").length).toBeGreaterThan(0);
    expect(screen.queryByText("Overview")).not.toBeInTheDocument();
    expect(screen.queryByText("Changes")).not.toBeInTheDocument();
  });

  it("redirects a locked section back to Start while initializing", async () => {
    renderAt("/projects/p1/backlog");
    // Backlog is gated → the Start surface renders (its Build CTA is present).
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Build the backlog/ })).toBeInTheDocument(),
    );
  });
});
