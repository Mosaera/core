import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HistoryRun, Project, RunDetail } from "../api/client";
import { ChangesCommitList } from "../components/changes/ChangesCommitList";
import { ProjectDetailPage } from "../pages/ProjectDetailPage";

const mocks = vi.hoisted(() => ({
  projectDiff: vi.fn(),
  projectMrStatus: vi.fn(),
  runDetail: vi.fn(),
  mergeProject: vi.fn(),
  getProject: vi.fn(),
  activeRuns: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      projectDiff: mocks.projectDiff,
      projectMrStatus: mocks.projectMrStatus,
      runDetail: mocks.runDetail,
      mergeProject: mocks.mergeProject,
      getProject: mocks.getProject,
      activeRuns: mocks.activeRuns,
    },
  };
});

function run(over: Partial<HistoryRun> = {}): HistoryRun {
  return {
    id: "r1", task: "Build the hero", status: "APPROVED", tests_passed: true, iterations: 1,
    commit_sha: "abc1234", source: "s", branch: "b", project_id: "p1", item_id: null,
    created_at: "2026-07-02T10:00:00Z", ...over,
  };
}

function project(over: Partial<Project> = {}): Project {
  return {
    id: "p1", name: "Demo", source_repo: "/tmp/demo", goal: "g", brief: "b",
    status: "active", branch: "mosaera/x", mr_url: "", autonomous: false,
    has_gitlab_token: true, gitlab_token_masked: "", error: "",
    created_at: "2026-07-01T00:00:00Z", backlog: [], runs: [], ...over,
  };
}

const DIFF_TEXT =
  "diff --git a/src/app.ts b/src/app.ts\n+++ b/src/app.ts\n@@ -1 +1,2 @@\n+one\n+two\n" +
  "diff --git a/README.md b/README.md\n+++ b/README.md\n@@ -1 +1 @@\n+doc\n-old\n";

function diffResponse(over: Record<string, unknown> = {}) {
  return {
    base: "main",
    diff: DIFF_TEXT,
    has_changes: true,
    files: ["src/app.ts", "README.md"],
    stats: [
      { path: "src/app.ts", additions: 2, deletions: 0 },
      { path: "README.md", additions: 1, deletions: 1 },
    ],
    ...over,
  };
}

function PmProbe() {
  const location = useLocation();
  const state = location.state as { pmPrefill?: string } | null;
  return <div>pm probe: {state?.pmPrefill ?? "(none)"}</div>;
}

function renderChanges(p: Project) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[`/projects/${p.id}/changes`]}>
        <Routes>
          <Route path="/projects/:id/changes" element={<ChangesCommitList project={p} />} />
          <Route path="/projects/:id/pm" element={<PmProbe />} />
          <Route path="/projects/:id/history/:runId/:slug?" element={<div>commit page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.projectDiff.mockResolvedValue(diffResponse());
  mocks.projectMrStatus.mockResolvedValue({ state: null, url: "" });
  mocks.runDetail.mockResolvedValue({
    ...run(),
    decisions: [], test_results: [], approvals: [],
    repo_changes: [
      { diff: "diff --git a/src/app.ts b/src/app.ts\n+++ b/src/app.ts\n+one\n", commit_sha: "abc", created_at: "t" },
    ],
  } satisfies RunDetail);
  mocks.mergeProject.mockResolvedValue({ opened: true, url: "https://gl/mr/9" });
  mocks.activeRuns.mockResolvedValue({ runs: [] });
});

describe("Changes commit list", () => {
  it("the merge bar shows an honest summary from real data", async () => {
    renderChanges(project({ runs: [run(), run({ id: "r2", tests_passed: false })] }));
    expect(
      await screen.findByText("2 files · +3 −1 vs main · 2 changes · 1 needs attention"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Delete project/i)).not.toBeInTheDocument();
  });

  it("gate: the Changes tab of the project page keeps the heading, carries no Delete Project", async () => {
    mocks.getProject.mockResolvedValue(project());
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <MemoryRouter initialEntries={["/projects/p1/changes"]}>
          <Routes>
            <Route path="/projects/:id/:section" element={<ProjectDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("heading", { name: "Changes" })).toBeInTheDocument();
    expect(screen.queryByText(/Delete project/i)).not.toBeInTheDocument();
  });

  it("lists changes as commit rows under a date group", async () => {
    renderChanges(project({ runs: [run()] }));
    // The commit row shows the task title + short sha.
    expect(await screen.findByText("Build the hero")).toBeInTheDocument();
    expect(screen.getByText("abc1234")).toBeInTheDocument();
  });

  it("ready state: Open merge request opens the compose sheet and pushes NOTHING yet", async () => {
    // This used to call api.mergeProject() bare — one click pushed the commits and opened an MR
    // the team could see, with no review, while the same call on Delivery got a full compose step.
    renderChanges(project({ runs: [run()] }));
    const btn = await screen.findByRole("button", { name: "Open merge request" });
    expect(btn).toBeEnabled();
    fireEvent.click(btn);
    expect(await screen.findByText("Compose merge request")).toBeInTheDocument();
    expect(mocks.mergeProject).not.toHaveBeenCalled();
  });

  it("the compose sheet is what actually sends, with the edited body", async () => {
    renderChanges(project({ runs: [run()], has_gitlab_api_token: true }));
    fireEvent.click(await screen.findByRole("button", { name: "Open merge request" }));
    const body = await screen.findByRole("textbox", { name: "Description" });
    fireEvent.change(body, { target: { value: "first line\n\nsecond line" } });
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Open merge request",
      }),
    );
    await waitFor(() =>
      expect(mocks.mergeProject).toHaveBeenCalledWith(
        "p1",
        expect.objectContaining({ body: "first line\n\nsecond line" }),
      ),
    );
  });

  it("blocked state: a failing latest run disables the merge action with a reason", async () => {
    renderChanges(project({ runs: [run({ tests_passed: false })] }));
    const btn = await screen.findByRole("button", { name: "Open merge request" });
    expect(btn).toBeDisabled();
    expect(screen.getByText(/latest settled run's validation did not pass/i)).toBeInTheDocument();
  });

  it("no runs: honest empty state", async () => {
    renderChanges(project({ runs: [] }));
    expect(await screen.findByText(/No changes yet/)).toBeInTheDocument();
  });

  it("no-token: the merge action links to THIS project's Integration pane", async () => {
    // Not the global settings page: the missing credential is the project's own, and the pane is
    // addressable now, so the CTA lands where the fix actually is.
    renderChanges(project({ has_gitlab_token: false, runs: [run()] }));
    expect(await screen.findByRole("button", { name: "Connect GitLab" })).toHaveAttribute(
      "href", "/projects/p1/settings?pane=integration",
    );
  });

  it("combined diff: toggled open, groups files by folder and mounts bodies only when expanded", async () => {
    renderChanges(project({ runs: [run()] }));
    fireEvent.click(await screen.findByRole("button", { name: "Combined diff" }));
    const panel = await screen.findByRole("region", { name: "File impact" });
    expect(within(panel).getByText("src")).toBeInTheDocument();
    expect(within(panel).getByText("(root)")).toBeInTheDocument();
    expect(within(panel).queryByText("+one")).not.toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: /src\/app\.ts/ }));
    expect(within(panel).getByText("+one")).toBeInTheDocument();
  });

  it("combined diff: truncated diff without server stats shows the honest partial note", async () => {
    mocks.projectDiff.mockResolvedValue(
      diffResponse({
        stats: undefined,
        diff: DIFF_TEXT + "\n... (diff truncated at 200000 chars)",
        files: ["src/app.ts", "README.md", "unparsed.bin"],
      }),
    );
    renderChanges(project({ runs: [run()] }));
    fireEvent.click(await screen.findByRole("button", { name: "Combined diff" }));
    expect(await screen.findByText(/Diff truncated at 200,000 characters/)).toBeInTheDocument();
    const panel = screen.getByRole("region", { name: "File impact" });
    expect(within(panel).getByText("binary")).toBeInTheDocument();
  });

  it("row expand lazily fetches the run detail and lists per-run files", async () => {
    renderChanges(project({ runs: [run()] }));
    fireEvent.click(await screen.findByRole("button", { name: "Show description" }));
    await waitFor(() => expect(mocks.runDetail).toHaveBeenCalledWith("r1"));
    expect(await screen.findByText("src/app.ts")).toBeInTheDocument();
  });

  it("row expand: missing per-run diff gets the honest note", async () => {
    mocks.runDetail.mockResolvedValue({
      ...run(), decisions: [], test_results: [], approvals: [], repo_changes: [],
    } satisfies RunDetail);
    renderChanges(project({ runs: [run()] }));
    fireEvent.click(await screen.findByRole("button", { name: "Show description" }));
    expect(
      await screen.findByText("No per-run diff was recorded for this change."),
    ).toBeInTheDocument();
  });

  it("Explain these changes hands the file count and base to the PM", async () => {
    renderChanges(project({ runs: [run()] }));
    await screen.findByText(/2 files · \+3 −1 vs main/);
    fireEvent.click(screen.getByRole("button", { name: /Explain these changes/ }));
    const probe = await screen.findByText(/pm probe:/);
    expect(probe.textContent).toContain("accumulated changes (2 files changed vs main)");
  });

  it("optimistic MR-open: after opening, the cached project flips to in_review", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const p = project({ runs: [run()] });
    qc.setQueryData(["project", "p1"], p);
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/projects/p1/changes"]}>
          <Routes>
            <Route path="/projects/:id/changes" element={<ChangesCommitList project={p} />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Open merge request" }));
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Open merge request",
      }),
    );
    await waitFor(() => expect(mocks.mergeProject).toHaveBeenCalled());
    const updated = qc.getQueryData<Project>(["project", "p1"]);
    expect(updated?.status).toBe("in_review");
    expect(updated?.mr_url).toBe("https://gl/mr/9");
  });

  it("a run's task PARAGRAPH never becomes a row label — the item's short name does", async () => {
    // Redundancy audit 2026-08-22. Fixtures elsewhere in this file use a single-line task with
    // item_id null, where taskTitle() and item lookup are both no-ops — such a fixture cannot
    // fail this rule. This one carries the real stored shape (title \n\n description \n\n
    // criteria, per task_spec.py) AND a backlog item, so the assertion can actually break.
    const PARAGRAPH =
      "Switch list output to pipe-delimited\n\nThe list command in src/budget_tracker/cli.py " +
      "should print expense rows separated by a pipe character instead of a comma.\n\n" +
      "Acceptance criteria: running `budget list` prints pipe-separated rows.";
    renderChanges(
      project({
        backlog: [
          { id: 113, title: "Switch list output to pipe-delimited", description: "", acceptance: "",
            status: "in_progress", position: 1, created_at: "2026-07-01T00:00:00Z" } as never,
        ],
        runs: [run({ id: "r-para", task: PARAGRAPH, item_id: 113 })],
      }),
    );
    expect(await screen.findByText("#113 · Switch list output to pipe-delimited")).toBeInTheDocument();
    expect(screen.queryByText(/should print expense rows separated by a pipe/)).not.toBeInTheDocument();
  });

  it("eight attempts of one item are ONE row with its history one disclosure away", async () => {
    // The exhibit-A defect: a stuck item filled the page with near-identical rows. The latest
    // attempt is the item's state; the priors stay on the record behind "N earlier".
    const attempts = Array.from({ length: 8 }, (_, i) =>
      run({
        id: `r-${i}`,
        task: "Switch list output to pipe-delimited\n\nbody",
        item_id: 113,
        status: i === 7 ? "INCOMPLETE" : "CANCELLED",
        created_at: `2026-07-0${i + 1}T10:00:00Z`,
      }),
    );
    renderChanges(
      project({
        backlog: [
          { id: 113, title: "Switch list output to pipe-delimited", description: "", acceptance: "",
            status: "in_progress", position: 1, created_at: "2026-07-01T00:00:00Z" } as never,
        ],
        runs: attempts,
      }),
    );
    // ONE labelled row, not eight.
    expect((await screen.findAllByText("#113 · Switch list output to pipe-delimited")).length).toBe(1);
    expect(screen.getByText(/attempt 8 of 8 · 7 earlier/)).toBeInTheDocument();
    // The summary counts ITEMS now, matching the Runs page and the overview: eight attempts of
    // one item read as ONE change needing attention, not eight.
    expect(await screen.findByText(/· 1 change · 1 needs attention/)).toBeInTheDocument();
  });
});
