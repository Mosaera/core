import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { HistoryRun, Project } from "../api/client";
import { ArtifactsWorkspace } from "../components/artifacts/ArtifactsWorkspace";

const mocks = vi.hoisted(() => ({
  projectFiles: vi.fn(),
  runReport: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      projectFiles: mocks.projectFiles,
      runReport: mocks.runReport,
    },
  };
});

function run(over: Partial<HistoryRun> = {}): HistoryRun {
  return {
    id: "r1", task: "Build the hero", status: "APPROVED", tests_passed: true, iterations: 1,
    commit_sha: "abc", source: "s", branch: "b", project_id: "p1", item_id: null,
    created_at: "2026-07-02T10:00:00Z", ...over,
  };
}

function project(over: Partial<Project> = {}): Project {
  return {
    id: "p1", name: "Demo", source_repo: "/tmp/demo", goal: "g",
    brief: "## Goals\nShip the site.",
    status: "active", branch: "mosaera/x", mr_url: "", autonomous: false,
    has_gitlab_token: true, gitlab_token_masked: "", error: "",
    created_at: "2026-07-01T00:00:00Z", backlog: [], runs: [], ...over,
  };
}

function renderArtifacts(p: Project) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[`/projects/${p.id}/artifacts`]}>
        <Routes>
          <Route path="/projects/:id/artifacts" element={<ArtifactsWorkspace project={p} />} />
          <Route path="/history/:id" element={<div>history page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.projectFiles.mockResolvedValue({
    files: ["pages/index.html", "pages/about.html", "README.md", "assets/logo bar.svg"],
  });
  mocks.runReport.mockResolvedValue({ markdown: "## Report\n\nDelivered the hero." });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Artifacts workspace", () => {
  it("shows honest toolbar summary, grouped files, and encoded download hrefs", async () => {
    renderArtifacts(project());
    expect(await screen.findByText("4 files · patch available · brief")).toBeInTheDocument();
    const panel = screen.getByRole("region", { name: "Produced files" });
    expect(within(panel).getByText("pages")).toBeInTheDocument();
    expect(within(panel).getByText("(root)")).toBeInTheDocument();
    // Per-segment URL encoding for odd paths.
    expect(
      within(panel).getByRole("button", { name: "Download assets/logo bar.svg" }),
    ).toHaveAttribute("href", "/api/projects/p1/files/assets/logo%20bar.svg");
    // Deliverables framing only — no diff/merge language.
    expect(screen.queryByText(/\+\d+ −\d+/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Delete project/i)).not.toBeInTheDocument();
  });

  it("empty state when nothing was produced; patch button hidden", async () => {
    mocks.projectFiles.mockResolvedValue({ files: [] });
    renderArtifacts(project({ brief: "" }));
    expect(await screen.findByText("No produced files yet")).toBeInTheDocument();
    expect(screen.getByText("Run a backlog item to produce deliverables.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Download patch/ })).not.toBeInTheDocument();
    expect(screen.getByText("No brief yet")).toBeInTheDocument();
  });

  it("renders the brief as markdown, not literal ##", async () => {
    renderArtifacts(project());
    const briefCard = await screen.findByRole("region", { name: "Project brief" });
    const heading = within(briefCard).getByText("Goals");
    expect(heading.tagName).toMatch(/^H\d$/);
    expect(within(briefCard).queryByText(/## Goals/)).not.toBeInTheDocument();
  });

  it("run reports moved to the run's Receipt evidence tab (#63) — no reports section here", async () => {
    renderArtifacts(project({ runs: [run()] }));
    await screen.findByRole("region", { name: "Project brief" });
    expect(screen.queryByRole("region", { name: "Run reports" })).not.toBeInTheDocument();
    expect(mocks.runReport).not.toHaveBeenCalled();
  });

  it("text preview opens a dialog with fetched content and closes on Escape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, text: () => Promise.resolve("# Acme\nRevamped.") }),
    );
    renderArtifacts(project());
    fireEvent.click(await screen.findByRole("button", { name: "Preview README.md" }));
    const dialog = await screen.findByRole("dialog", { name: "Preview: README.md" });
    expect(await within(dialog).findByText(/Revamped\./)).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: /Preview/ })).not.toBeInTheDocument();
  });

  it("preview button is absent for non-previewable types", async () => {
    mocks.projectFiles.mockResolvedValue({ files: ["font.woff2"] });
    renderArtifacts(project());
    await screen.findByText("font.woff2");
    expect(screen.queryByRole("button", { name: "Preview font.woff2" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download font.woff2" })).toBeInTheDocument();
  });
});
