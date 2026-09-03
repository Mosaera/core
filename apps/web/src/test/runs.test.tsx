import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ActiveRun, HistoryRun, Project, RunDetail } from "../api/client";
import { RunsWorkspace } from "../components/runs/RunsWorkspace";
import { ProjectDetailPage } from "../pages/ProjectDetailPage";

const mocks = vi.hoisted(() => ({
  runDetail: vi.fn(),
  cancelRun: vi.fn(),
  getProject: vi.fn(),
  activeRuns: vi.fn(),
  projectFiles: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      runDetail: mocks.runDetail,
      cancelRun: mocks.cancelRun,
      getProject: mocks.getProject,
      activeRuns: mocks.activeRuns,
      projectFiles: mocks.projectFiles,
    },
  };
});

function run(over: Partial<HistoryRun> = {}): HistoryRun {
  return {
    id: "r1", task: "Build the hero", status: "APPROVED", tests_passed: true, iterations: 2,
    commit_sha: "abc12345", source: "s", branch: "mosaera/x", project_id: "p1", item_id: null,
    created_at: "2026-07-02T10:00:00Z", ...over,
  };
}

function detail(over: Partial<RunDetail> = {}): RunDetail {
  return {
    ...run(), decisions: [], approvals: [],
    test_results: [{ passed: true, output: "[exit code 0]\n3 passed", created_at: null }],
    repo_changes: [
      {
        diff: "diff --git a/pages/index.html b/pages/index.html\n+++ b/pages/index.html\n+<h1>x</h1>\n",
        commit_sha: "abc", created_at: null,
      },
    ],
    ...over,
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

function PmProbe() {
  const location = useLocation();
  const state = location.state as { pmPrefill?: string } | null;
  return <div>pm probe: {state?.pmPrefill ?? "(none)"}</div>;
}

function renderRuns(p: Project, activeRun?: ActiveRun) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[`/projects/${p.id}/runs`]}>
        <Routes>
          <Route
            path="/projects/:id/runs"
            element={<RunsWorkspace project={p} activeRun={activeRun} />}
          />
          <Route path="/projects/:id/pm" element={<PmProbe />} />
          <Route path="/history/:id" element={<div>history page</div>} />
          <Route path="/runs/:id" element={<div>live run page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.runDetail.mockResolvedValue(detail());
  mocks.cancelRun.mockResolvedValue({ cancelled: "x" });
  mocks.activeRuns.mockResolvedValue({ runs: [] });
  mocks.projectFiles.mockResolvedValue({ files: [] });
});

const MIXED = [
  run({ id: "r-new", task: "Nav rework", tests_passed: false }),
  run({ id: "r-ok", task: "Homepage hero" }),
  run({ id: "r-gone", task: "Pricing tiers", status: "CANCELLED", tests_passed: false }),
];

describe("Runs workspace", () => {
  it("toolbar shows honest counts and a latest-run link", async () => {
    // Item consolidation (de-firehose phase 2): the toolbar speaks ITEM language with one honest
    // trailing attempt count. The cancelled ad-hoc run is archived out of the item count.
    renderRuns(project({ runs: MIXED }));
    expect(
      await screen.findByText("2 items · 1 needs attention · 1 delivered · 1 archived · 3 attempts"),
    ).toBeInTheDocument();
    const latestBtn = screen.getByRole("button", { name: "View latest run" });
    expect(latestBtn).toHaveAttribute("href", "/projects/p1/history/r-new");
    expect(screen.queryByText(/Delete project/i)).not.toBeInTheDocument();
  });

  it("gate: Delete project lives only on Settings", async () => {
    mocks.getProject.mockResolvedValue(project({ runs: MIXED }));
    const client = () => new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const at = (path: string) =>
      render(
        <QueryClientProvider client={client()}>
          <MemoryRouter initialEntries={[path]}>
            <Routes>
              <Route path="/projects/:id/:section" element={<ProjectDetailPage />} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>,
      );

    let view = at("/projects/p1/runs");
    expect(await screen.findByRole("heading", { name: "Runs" })).toBeInTheDocument();
    expect(screen.queryByText(/Delete project/i)).not.toBeInTheDocument();
    view.unmount();

    view = at("/projects/p1/artifacts");
    expect(await screen.findByRole("heading", { name: "Artifacts" })).toBeInTheDocument();
    expect(screen.queryByText(/Delete project/i)).not.toBeInTheDocument();
    view.unmount();

    at("/projects/p1/settings");
    // Delete now lives under the settings "Danger zone" section.
    fireEvent.click(await screen.findByRole("button", { name: "Danger zone" }));
    expect(await screen.findByRole("button", { name: "Delete project" })).toBeInTheDocument();
  });

  it("state reads honestly per item: approved-but-failing is attention; cancelled archives", async () => {
    // Redundancy audit 2026-08-22: the summary tiles were deleted (they restated the toolbar
    // line); the honesty rule is unchanged — a delivery whose validation failed is never green,
    // and the count now has ONE render: the toolbar summary.
    renderRuns(project({ runs: MIXED }));
    expect(await screen.findByText("Validation failed")).toBeInTheDocument();
    expect(screen.getByText(/1 needs attention/)).toBeInTheDocument();
    // Cancelled ad-hoc run: archived by default, on the record behind the toggle.
    expect(screen.queryByText("Pricing tiers")).not.toBeInTheDocument();
    expect(screen.getByText(/1 archived item hidden/)).toBeInTheDocument();
    // The archived toggle moved into the toolbar when the tiles were cut (2026-08-22).
    fireEvent.click(screen.getByRole("button", { name: /Archived/ }));
    // Once shown, the cancelled ad-hoc item renders its header (title) — the attempt card's
    // duplicate title/badge renders are suppressed under an item header.
    expect((await screen.findAllByText("Pricing tiers")).length).toBeGreaterThan(0);
  });

  it("latest run is selected by default with a Latest chip", async () => {
    renderRuns(project({ runs: MIXED }));
    const panel = await screen.findByRole("region", { name: "Run detail" });
    expect(within(panel).getByRole("heading", { name: "Nav rework" })).toBeInTheDocument();
    expect(within(panel).getByText("Latest")).toBeInTheDocument();
    await waitFor(() => expect(mocks.runDetail).toHaveBeenCalledWith("r-new"));
    // Only the selected run fetches.
    expect(mocks.runDetail).not.toHaveBeenCalledWith("r-ok");
  });

  it("panel verdict: validation failed with the approved helper and output excerpt", async () => {
    mocks.runDetail.mockResolvedValue(
      detail({
        tests_passed: false,
        test_results: [{ passed: false, output: "[exit code 1]\n1 failed: test_nav", created_at: null }],
      }),
    );
    renderRuns(project({ runs: [run({ id: "r-new", task: "Nav rework", tests_passed: false })] }));
    const panel = await screen.findByRole("region", { name: "Run detail" });
    expect(await within(panel).findByText("Validation failed")).toBeInTheDocument();
    expect(
      within(panel).getByText(
        "The agent completed and was approved, but validation did not pass. Review the run output before merging.",
      ),
    ).toBeInTheDocument();
    expect(within(panel).getByText(/1 failed: test_nav/)).toBeInTheDocument();
    // Changed files from the real per-run diff.
    expect(within(panel).getByText("pages/index.html")).toBeInTheDocument();
    // Diagnose ask appears only for failed verdicts.
    fireEvent.click(
      within(panel).getByRole("button", { name: "Ask PM to diagnose validation failure" }),
    );
    const probe = await screen.findByText(/pm probe:/);
    expect(probe.textContent).toContain("completed but its validation did not pass");
  });

  it("panel verdict: planner-unavailable shows the plan block with its reason", async () => {
    const plan = {
      project_type: "javascript",
      reason: "JavaScript project (package.json): no Node offline.",
      steps: [],
      results: [],
    };
    mocks.runDetail.mockResolvedValue(
      detail({
        validation_status: "unavailable",
        test_results: [],
        repo_changes: [],
        decisions: [{ kind: "validation_plan", content: JSON.stringify(plan), created_at: null }],
      }),
    );
    renderRuns(project({ runs: [run({ id: "r-js", tests_passed: false })] }));
    const panel = await screen.findByRole("region", { name: "Run detail" });
    expect(await within(panel).findByText("Validation unavailable")).toBeInTheDocument();
    // The reason appears as the verdict helper AND in the structured plan block.
    expect(
      within(panel).getAllByText("JavaScript project (package.json): no Node offline.").length,
    ).toBeGreaterThan(0);
    expect(within(panel).getByText(/Validation plan · javascript/)).toBeInTheDocument();
  });

  it("panel shows per-step plan results and joined evidence", async () => {
    const plan = {
      project_type: "static-site",
      reason: "static site: checking 2 HTML page(s)",
      steps: [{ name: "html-check" }],
      results: [{ name: "html-check", exit_code: 0, timed_out: false, ok: true, output: "OK" }],
    };
    mocks.runDetail.mockResolvedValue(
      detail({
        validation_status: "pass",
        test_results: [
          { passed: true, output: "[step html-check: exit code 0]\nchecked 2 html file(s): OK", created_at: null },
        ],
        decisions: [{ kind: "validation_plan", content: JSON.stringify(plan), created_at: null }],
      }),
    );
    renderRuns(project({ runs: [run({ id: "r-ss" })] }));
    const panel = await screen.findByRole("region", { name: "Run detail" });
    expect(await within(panel).findByText(/Validation plan · static-site/)).toBeInTheDocument();
    expect(within(panel).getByText("html-check")).toBeInTheDocument();
    expect(within(panel).getByText("exit code 0")).toBeInTheDocument();
    expect(within(panel).getByText(/checked 2 html file\(s\): OK/)).toBeInTheDocument();
  });

  it("panel verdict: no evidence recorded when test_results is empty", async () => {
    mocks.runDetail.mockResolvedValue(detail({ test_results: [], repo_changes: [] }));
    renderRuns(project({ runs: [run({ id: "r-x", status: "CANCELLED", tests_passed: false })] }));
    const panel = await screen.findByRole("region", { name: "Run detail" });
    expect(await within(panel).findByText("No validation evidence recorded")).toBeInTheDocument();
    expect(within(panel).getByText("This run has no stored validation output.")).toBeInTheDocument();
    expect(
      within(panel).getByText("No per-run diff was recorded for this run."),
    ).toBeInTheDocument();
  });

  it("panel verdict: exit-code-5 output reads as no test suite detected", async () => {
    mocks.runDetail.mockResolvedValue(
      detail({
        tests_passed: false,
        test_results: [{ passed: false, output: "[exit code 5]\nno tests ran in 0.12s", created_at: null }],
      }),
    );
    renderRuns(project({ runs: [run({ id: "r-n", tests_passed: false })] }));
    const panel = await screen.findByRole("region", { name: "Run detail" });
    expect(await within(panel).findByText("No test suite detected")).toBeInTheDocument();
    expect(within(panel).queryByText("Validation failed")).not.toBeInTheDocument();
  });

  it("live run: active group, pending verdict, no detail fetch, cancel works", async () => {
    const live: ActiveRun = {
      run_id: "r-live", status: "running", task: "t", phase: "implement",
      started_at: Date.now() / 1000, project_id: "p1", item_id: null,
    };
    renderRuns(
      project({ runs: [run({ id: "r-live", task: "Live work", status: "RUNNING" })] }),
      live,
    );
    // The item badge says Running; the attempt card's own badge is SUPPRESSED under an item
    // header (redundancy audit 2026-08-22: one fact, one render) — do not restore the dup.
    expect((await screen.findAllByText("Running")).length).toBeGreaterThan(0);
    const panel = screen.getByRole("region", { name: "Run detail" });
    expect(within(panel).getByText("Validation pending")).toBeInTheDocument();
    expect(within(panel).getByText("The run is still executing.")).toBeInTheDocument();
    expect(mocks.runDetail).not.toHaveBeenCalled();
    fireEvent.click(within(panel).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(mocks.cancelRun).toHaveBeenCalledWith("r-live"));
  });

  it("selecting a card pins it into the panel", async () => {
    renderRuns(project({ runs: MIXED }));
    fireEvent.click(await screen.findByRole("button", { name: "Select run Homepage hero" }));
    const panel = screen.getByRole("region", { name: "Run detail" });
    expect(
      await within(panel).findByRole("heading", { name: "Homepage hero" }),
    ).toBeInTheDocument();
    // The unpin affordance moved to the toolbar when the tiles were cut (2026-08-22): it only
    // renders while a non-latest run is pinned, and snaps the panel back without navigating.
    fireEvent.click(screen.getByRole("button", { name: "Back to latest run" }));
    expect(await within(panel).findByRole("heading", { name: "Nav rework" })).toBeInTheDocument();
  });

  it("PM handoffs: summarize, explain, and cancelled-run advice prefill exactly", async () => {
    renderRuns(project({ runs: MIXED }));
    fireEvent.click(await screen.findByRole("button", { name: /Ask PM to summarize runs/ }));
    let probe = await screen.findByText(/pm probe:/);
    expect(probe.textContent).toContain(
      "Summarize this project's run history (2 items · 1 needs attention · 1 delivered · " +
        "1 archived · 3 attempts).",
    );
  });

  it("every non-delivered end offers the unblock handoff, with the park facts", async () => {
    mocks.runDetail.mockResolvedValue(
      detail({
        test_results: [],
        repo_changes: [],
        diagnosis: { outcome: "honest_park", park_cause: "give_up", give_up_reason: "no convergence" },
      }),
    );
    renderRuns(project({ runs: [run({ id: "r-gone", task: "Pricing tiers", status: "CANCELLED" })] }));
    const panel = await screen.findByRole("region", { name: "Run detail" });
    fireEvent.click(
      await within(panel).findByRole("button", { name: "Ask PM how to unblock" }),
    );
    const probe = await screen.findByText(/pm probe:/);
    expect(probe.textContent).toContain('stopped without delivering. Stopped honestly, without delivering.');
    expect(probe.textContent).toContain("Why it stopped: no convergence");
    expect(probe.textContent).toContain("Propose how to unblock");
  });

  it("a delivered run gets no unblock handoff", async () => {
    renderRuns(project({ runs: [run({ id: "r-ok", task: "Homepage hero" })] }));
    const panel = await screen.findByRole("region", { name: "Run detail" });
    await within(panel).findByRole("button", { name: "Ask PM to explain this run" });
    expect(
      within(panel).queryByRole("button", { name: "Ask PM how to unblock" }),
    ).not.toBeInTheDocument();
  });

  it("explain-this-run handoff from the panel", async () => {
    renderRuns(project({ runs: [run({ id: "r-ok", task: "Homepage hero" })] }));
    const panel = await screen.findByRole("region", { name: "Run detail" });
    fireEvent.click(
      await within(panel).findByRole("button", { name: "Ask PM to explain this run" }),
    );
    const probe = await screen.findByText(/pm probe:/);
    expect(probe.textContent).toContain('Explain the run "Homepage hero" (r-ok).');
  });

  it("an item with an OPEN clarification always shows the ask badge — ADR-0107", async () => {
    // The grouped view must never tidy an unanswered question out of sight: a tidy item row
    // over an open ask is the suppression the Unsuppressible Ask invariant forbids.
    renderRuns(
      project({
        runs: [run({ id: "r-q", item_id: 7, status: "INCOMPLETE", tests_passed: null })],
        backlog: [
          {
            id: 7,
            title: "Needs an answer",
            status: "in_progress",
            clarification: { status: "open", question: "which separator?" },
          } as never,
        ],
      }),
    );
    expect(await screen.findByText("question open")).toBeInTheDocument();
  });

  it("the task PARAGRAPH never renders as a title — first line only (Firehose Audit #1)", async () => {
    // The full task (title + description + acceptance criteria) was the H1 on six surfaces, and
    // survived three redesign phases until the owner caught it in the after-screenshots. The list
    // shows the first line; the paragraph lives one disclosure away on the run page, never here.
    const woven =
      "Add a --sort flag\n\nThe list command in src/cli.py should accept --sort amount.\n\n" +
      "Acceptance criteria: exits 0.";
    renderRuns(project({ runs: [run({ id: "r-w", task: woven, item_id: null })] }));
    expect((await screen.findAllByText("Add a --sort flag")).length).toBeGreaterThan(0);
    expect(
      screen.queryByText(/The list command in src\/cli\.py should accept/),
    ).not.toBeInTheDocument();
  });

  it("merged project archives everything — history kept, nothing demands attention", async () => {
    renderRuns(project({ status: "merged", runs: MIXED }));
    expect(await screen.findByText(/3 archived items hidden/)).toBeInTheDocument();
    // Tiles cut 2026-08-22: zero-attention now reads as the ABSENCE of the attention clause in
    // the toolbar's one summary line.
    expect(screen.queryByText(/need(s)? attention/)).not.toBeInTheDocument();
    expect(screen.getByText("0 items · 3 archived · 3 attempts")).toBeInTheDocument();
  });

  it("panel receipt: collapses only when the diagnosis carries the reasons — and never over bad news", async () => {
    // Redundancy audit 2026-08-22: the diagnosis card owns the reasons render in the panel, so a
    // benign receipt folds. Puncture guard: a tamper/not_run reason keeps the receipt OPEN — bad
    // news never starts folded, even though the diagnosis says it too.
    const receiptRow = (reasons: string[]) => ({
      kind: "receipt",
      content: JSON.stringify({
        action: "require_human", reasons, reviewer_verdict: "APPROVE", tests_passed: true,
        validation_strength: "suite", unsatisfied_claims: [],
      }),
      created_at: null,
    });
    mocks.runDetail.mockResolvedValue(
      detail({
        decisions: [receiptRow(["require_human_approval"])],
        diagnosis: { outcome: "delivered", gate_reasons: ["require_human_approval"] },
      }),
    );
    const first = renderRuns(project({ runs: [run({ id: "r-fold" })] }));
    const panel = await screen.findByRole("region", { name: "Run detail" });
    // Folded: the summary is there, the receipt's reviewer chip is not rendered visible.
    const drawer = (await within(panel).findByText("Receipt")).closest("details");
    expect(drawer).not.toBeNull();
    expect(drawer!.open).toBe(false);
    first.unmount();

    mocks.runDetail.mockResolvedValue(
      detail({
        decisions: [receiptRow(["tests_tampered"])],
        diagnosis: { outcome: "delivered", gate_reasons: ["tests_tampered"] },
      }),
    );
    renderRuns(project({ runs: [run({ id: "r-tamper" })] }));
    const panel2 = await screen.findByRole("region", { name: "Run detail" });
    const label = await within(panel2).findByText("Receipt");
    expect(label.closest("details")).toBeNull(); // open section, no disclosure at all
  });

  it("empty state, and a healthy history claims no attention", async () => {
    const { unmount } = renderRuns(project({ runs: [] }));
    expect(await screen.findByText("No runs yet")).toBeInTheDocument();
    expect(
      screen.getByText("Run a backlog item to generate execution history."),
    ).toBeInTheDocument();
    unmount();
    // Tiles cut 2026-08-22: "nothing needs attention" is the summary line staying silent.
    renderRuns(project({ runs: [run()] }));
    expect(await screen.findByText(/1 item ·/)).toBeInTheDocument();
    expect(screen.queryByText(/need(s)? attention/)).not.toBeInTheDocument();
  });
});
