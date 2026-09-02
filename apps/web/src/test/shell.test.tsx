import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { App } from "../App";

// The shell only needs list/detail queries to resolve; everything else is inert.
vi.mock("../api/client", () => ({
  api: {
    listProjects: () => Promise.resolve({ projects: [] }),
    getProject: (id: string) =>
      Promise.resolve({
        id,
        name: "Demo Project",
        source_repo: "src",
        goal: "",
        brief: "b",
        status: "active",
        branch: "",
        mr_url: "",
        autonomous: false,
        has_gitlab_token: false,
        gitlab_token_masked: "",
        error: "",
        created_at: null,
        backlog: [
          { id: 1, project_id: id, title: "a", description: "", acceptance: "", status: "todo", position: 0, iteration: null, created_at: null },
          { id: 2, project_id: id, title: "b", description: "", acceptance: "", status: "done", position: 1, iteration: null, created_at: null },
        ],
        runs: [],
      }),
    activeRuns: () => Promise.resolve({ runs: [] }),
    projectDiff: () => Promise.resolve({ base: "main", diff: "", has_changes: false, files: [] }),
    projectMrStatus: () => Promise.resolve({ state: null, url: "" }),
    projectMessages: () => Promise.resolve({ messages: [] }),
    projectFiles: () => Promise.resolve({ files: [] }),
    projectPatchUrl: (id: string) => `/api/projects/${id}/patch`,
    projectFileUrl: (id: string, path: string) => `/api/projects/${id}/files/${path}`,
  },
}));

// Chrome, not the subject: `SetupBanner` polls `/api/preflight` through `api/firstRun`,
// which this suite does not mock (it mocks `api/client`). Stubbed like `SetupPanel`
// above — an unmocked fetch in jsdom raises "Invalid URL" and fails the run on an
// unhandled error even while every assertion passes.
vi.mock("../components/setup/SetupBanner", () => ({ SetupBanner: () => null }));

function renderAt(path: string) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("app shell", () => {
  it("shows the global console nav and no project group outside a project", () => {
    renderAt("/");
    for (const label of ["Projects", "New run", "Settings"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(screen.queryByText("Overview")).not.toBeInTheDocument();
    expect(screen.queryByText("Backlog")).not.toBeInTheDocument();
  });

  it("redirects /projects/:id to overview and shows the project section group", async () => {
    renderAt("/projects/p1");
    // Redirect landed on the Overview section: the dashboard renders.
    expect(await screen.findByText("Work pipeline")).toBeInTheDocument();
    // The rail gains the project's section items.
    for (const label of ["Overview", "PM", "Backlog", "Changes", "Delivery", "Artifacts", "Runs"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    // Project Settings entry joins the global footer Settings.
    expect(screen.getAllByText("Settings").length).toBeGreaterThan(1);
    // The project group is titled with the project name (shared query); the
    // page h1 shows it too, so expect at least one match.
    expect((await screen.findAllByText("Demo Project")).length).toBeGreaterThan(0);
  });

  it("marks the active section with aria-current", async () => {
    renderAt("/projects/p1/backlog");
    const active = await screen.findAllByRole("link", { current: "page" });
    expect(active.some((a) => a.textContent?.includes("Backlog"))).toBe(true);
  });

  it("keeps /projects/new on the new-project page (no project group)", () => {
    renderAt("/projects/new");
    expect(screen.queryByText("Artifacts")).not.toBeInTheDocument();
  });
});
