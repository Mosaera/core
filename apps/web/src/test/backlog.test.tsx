import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, useParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ActiveRun, BacklogItem, HistoryRun, Project } from "../api/client";
import { BacklogWorkspace } from "../components/backlog/BacklogWorkspace";

const mocks = vi.hoisted(() => ({
  runBacklogItem: vi.fn(),
  patchBacklogItem: vi.fn(),
  setItemDependencies: vi.fn(),
  addBacklogItem: vi.fn(),
  generateBacklog: vi.fn(),
  startAutonomous: vi.fn(),
  setAutonomous: vi.fn(),
  getProject: vi.fn(),
  activeRuns: vi.fn(),
  projectDiff: vi.fn(),
  projectMrStatus: vi.fn(),
  config: vi.fn(),
  resolveClarification: vi.fn(),
  curateBacklog: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      runBacklogItem: mocks.runBacklogItem,
      patchBacklogItem: mocks.patchBacklogItem,
      setItemDependencies: mocks.setItemDependencies,
      addBacklogItem: mocks.addBacklogItem,
      generateBacklog: mocks.generateBacklog,
      startAutonomous: mocks.startAutonomous,
      setAutonomous: mocks.setAutonomous,
      getProject: mocks.getProject,
      activeRuns: mocks.activeRuns,
      projectDiff: mocks.projectDiff,
      projectMrStatus: mocks.projectMrStatus,
      config: mocks.config,
      resolveClarification: mocks.resolveClarification,
      curateBacklog: mocks.curateBacklog,
    },
  };
});

function item(id: number, status: string, over: Partial<BacklogItem> = {}): BacklogItem {
  return {
    id, project_id: "p1", title: `item ${id}`, description: `desc ${id}`,
    acceptance: "", status, position: id, iteration: null,
    created_at: "2026-07-01T10:00:00Z", ...over,
  };
}

function run(over: Partial<HistoryRun> = {}): HistoryRun {
  return {
    id: "r-hist", task: "t", status: "APPROVED", tests_passed: true, iterations: 1,
    commit_sha: "abc", source: "s", branch: "b", project_id: "p1", item_id: null,
    created_at: "2026-07-02T10:00:00Z", ...over,
  };
}

function project(over: Partial<Project> = {}): Project {
  return {
    id: "p1", name: "Demo", source_repo: "/tmp/demo", goal: "g", brief: "## brief",
    status: "active", branch: "mosaera/x", mr_url: "", autonomous: false,
    has_gitlab_token: false, gitlab_token_masked: "", error: "",
    created_at: "2026-07-01T00:00:00Z", backlog: [], runs: [], ...over,
  };
}

const FULL_BOARD = [
  item(1, "todo", { title: "Homepage hero", acceptance: "- fast\n- accessible\n- responsive" }),
  item(2, "in_progress", { title: "Nav rework" }),
  item(3, "in_review", { title: "Case studies" }),
  item(4, "done", { title: "Contact form" }),
];

function PmProbe() {
  const location = useLocation();
  const state = location.state as { pmPrefill?: string } | null;
  return <div>pm probe: {state?.pmPrefill ?? "(no prefill)"}</div>;
}

function RunProbe() {
  const { id, runId } = useParams();
  return <div>run page {runId ?? id}</div>;
}

function renderBoard(p: Project, activeRun?: ActiveRun) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[`/projects/${p.id}/backlog`]}>
        <Routes>
          <Route
            path="/projects/:id/backlog"
            element={<BacklogWorkspace project={p} activeRun={activeRun} />}
          />
          <Route path="/projects/:id/pm" element={<PmProbe />} />
          <Route path="/projects/:id/runs/:runId" element={<RunProbe />} />
          <Route path="/projects/:id/history/:runId" element={<div>history page</div>} />
          <Route path="/runs/:id" element={<RunProbe />} />
          <Route path="/history/:id" element={<div>history page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.patchBacklogItem.mockResolvedValue(item(1, "todo"));
  mocks.setItemDependencies.mockResolvedValue(item(1, "todo"));
  mocks.config.mockResolvedValue({ gitlab: false, admin_required: false, max_iterations_ceiling: 12 });
  mocks.addBacklogItem.mockResolvedValue(item(99, "todo"));
  mocks.generateBacklog.mockResolvedValue({ status: "generating" });
  mocks.startAutonomous.mockResolvedValue({ status: "started" });
  mocks.runBacklogItem.mockResolvedValue({ run_id: "r9" });
});

describe("Backlog board", () => {
  it("renders four informative columns with counts and an honest toolbar summary", () => {
    renderBoard(project({ backlog: FULL_BOARD }));
    expect(screen.getByRole("heading", { name: "Backlog" })).toBeInTheDocument();
    expect(screen.getByText("4 items · 1 in progress · 1 needs review · 1 done")).toBeInTheDocument();
    for (const label of ["To do", "In progress", "In review", "Done"]) {
      expect(screen.getByRole("region", { name: label })).toBeInTheDocument();
    }
    // Status meanings ride under the column labels.
    expect(screen.getByText("Waiting for your approval")).toBeInTheDocument();
    // The destructive project action is gone from this tab.
    expect(screen.queryByText(/Delete project/i)).not.toBeInTheDocument();
    // No fake controls.
    expect(screen.queryByPlaceholderText(/search/i)).not.toBeInTheDocument();
  });

  it("shows a useful empty state per column", () => {
    renderBoard(project({ backlog: [item(1, "todo")] }));
    expect(screen.getByText("Nothing running")).toBeInTheDocument();
    expect(screen.getByText("Nothing waiting on you")).toBeInTheDocument();
    expect(screen.getByText("Nothing approved yet")).toBeInTheDocument();
    expect(screen.queryByText("Nothing queued")).not.toBeInTheDocument();
  });

  it("whole-board empty state stays honest for active vs ready projects", () => {
    const { unmount } = renderBoard(project({ status: "active", backlog: [] }));
    expect(screen.getByText(/The PM is drafting the backlog/)).toBeInTheDocument();
    unmount();
    renderBoard(project({ status: "ready", backlog: [] }));
    expect(screen.getByText(/Approve the brief on Overview/)).toBeInTheDocument();
  });

  it("run action launches the item and navigates to the run", async () => {
    renderBoard(project({ backlog: [item(1, "todo", { title: "Homepage hero" })] }));
    fireEvent.click(screen.getByRole("button", { name: "Run guided ▸" }));
    // The compact board quick-run uses the default Guided mode and no limits.
    await waitFor(() =>
      expect(mocks.runBacklogItem).toHaveBeenCalledWith("p1", 1, "guided", undefined),
    );
    expect(await screen.findByText("run page r9")).toBeInTheDocument();
  });

  it("run is gated while another item is in progress", () => {
    renderBoard(project({ backlog: [item(1, "todo"), item(2, "in_progress")] }));
    const runBtn = screen.getByRole("button", { name: "Run guided ▸" });
    expect(runBtn).toBeDisabled();
    expect(runBtn).toHaveAttribute("title", "another item is running on this project");
  });

  it("in-progress card links to the live run when one matches", () => {
    renderBoard(project({ backlog: [item(2, "in_progress")] }), {
      run_id: "r1", status: "running", task: "t", phase: "implement",
      started_at: Date.now() / 1000, project_id: "p1", item_id: 2,
    });
    const links = screen.getAllByRole("link").map((l) => l.getAttribute("href"));
    expect(links).toContain("/projects/p1/runs/r1");
    expect(screen.queryByRole("button", { name: "Reset to todo" })).not.toBeInTheDocument();
  });

  it("orphaned in-progress card offers reset to todo", async () => {
    renderBoard(project({ backlog: [item(2, "in_progress")] }));
    fireEvent.click(screen.getByRole("button", { name: "Reset to todo" }));
    await waitFor(() =>
      expect(mocks.patchBacklogItem).toHaveBeenCalledWith("p1", 2, { status: "todo" }),
    );
  });

  it("review/done cards link to their exact run via item_id", () => {
    renderBoard(
      project({
        backlog: [item(3, "in_review")],
        runs: [run({ id: "r-linked", item_id: 3, tests_passed: false })],
      }),
    );
    // The label now comes from `runOutcome` rather than the raw `tests_passed` flag; the
    // assertion here is the href, and the name is only how the link is found.
    const link = screen.getByRole("link", { name: /latest run · validation failed/ });
    expect(link).toHaveAttribute("href", "/projects/p1/history/r-linked");
  });

  it("a run that never reached a test phase is not labelled a test failure", () => {
    // 20260806-205850-033b61: the intake gate refused an under-specified item at 0 tokens, and
    // the card called it a red TESTS FAIL.
    renderBoard(
      project({
        backlog: [item(3, "in_review")],
        runs: [
          run({
            id: "r-parked",
            item_id: 3,
            status: "INCOMPLETE",
            tests_passed: null,
            termination_reason: "under_specified: no material acceptance claim is checkable",
          }),
        ],
      }),
    );
    expect(screen.queryByText(/tests fail/i)).toBeNull();
    expect(screen.getByRole("link", { name: /latest run · parked/ })).toBeInTheDocument();
  });

  it("clicking a card opens the detail drawer with real fields only", async () => {
    renderBoard(project({ backlog: FULL_BOARD }));
    fireEvent.click(screen.getByRole("button", { name: "Open details for Homepage hero" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Homepage hero")).toBeInTheDocument();
    expect(within(dialog).getByText("desc 1")).toBeInTheDocument();
    // Parsed acceptance criteria, counted honestly.
    expect(within(dialog).getByText(/Acceptance criteria · 3/)).toBeInTheDocument();
    expect(within(dialog).getByText("accessible")).toBeInTheDocument();
    expect(within(dialog).getByText(/Created/)).toBeInTheDocument();
    // No invented fields.
    expect(within(dialog).queryByText(/priority/i)).not.toBeInTheDocument();
    expect(within(dialog).queryByText(/estimate/i)).not.toBeInTheDocument();
    // No delete — there is no endpoint.
    expect(within(dialog).queryByText(/delete|archive/i)).not.toBeInTheDocument();
  });

  it("drawer run-mode selector launches the item in the chosen mode", async () => {
    renderBoard(project({ backlog: [item(1, "todo", { title: "Homepage hero" })] }));
    fireEvent.click(screen.getByRole("button", { name: "Open details for Homepage hero" }));
    const dialog = await screen.findByRole("dialog");
    // Guided is the default; pick Autonomous, then run.
    fireEvent.click(within(dialog).getByRole("radio", { name: "Autonomous" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Run item ▸" }));
    // The run sheet carries the limit sliders' defaults (3 revisions, 200k
    // token safety-net, no $ cap).
    await waitFor(() =>
      expect(mocks.runBacklogItem).toHaveBeenCalledWith("p1", 1, "autonomous", {
        max_iterations: 3,
        budget_tokens: 200000,
        budget_usd: null,
        cost_mode: null, // no cost-modes configured in this test → default applies
      }),
    );
  });

  it("drawer edit saves via PATCH and never invents fields", async () => {
    renderBoard(project({ backlog: [item(1, "todo", { title: "Homepage hero" })] }));
    fireEvent.click(screen.getByRole("button", { name: "Open details for Homepage hero" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Edit" }));
    fireEvent.change(within(dialog).getByLabelText("Item title"), {
      target: { value: "Hero v2" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(mocks.patchBacklogItem).toHaveBeenCalledWith("p1", 1, {
        title: "Hero v2",
        description: "desc 1",
        acceptance: "",
      }),
    );
  });

  it("review workflow: Review opens the drawer; Approve marks done", async () => {
    renderBoard(project({ backlog: [item(3, "in_review", { title: "Case studies" })] }));
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve — mark done" }));
    await waitFor(() =>
      expect(mocks.patchBacklogItem).toHaveBeenCalledWith("p1", 3, { status: "done" }),
    );
  });

  it("request edits hands full item context to the PM composer via router state", async () => {
    renderBoard(
      project({
        backlog: [
          item(3, "in_review", { title: "Case studies", acceptance: "- has grid" }),
        ],
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Request edits" }));
    const probe = await screen.findByText(/pm probe:/);
    expect(probe.textContent).toContain('"Case studies"');
    expect(probe.textContent).toContain("desc 3");
    expect(probe.textContent).toContain("- has grid");
  });

  it("Ask PM to reprioritize navigates with a prefill, never sends", async () => {
    renderBoard(project({ backlog: [item(1, "todo")] }));
    fireEvent.click(screen.getByRole("button", { name: /Ask PM to reprioritize/ }));
    const probe = await screen.findByText(/pm probe:/);
    expect(probe.textContent).toContain("Review the backlog priorities");
  });

  it("refresh backlog asks for confirmation and respects a decline", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderBoard(project({ backlog: [item(1, "todo")] }));
    fireEvent.click(screen.getByRole("button", { name: /Refresh backlog/ }));
    expect(confirm).toHaveBeenCalledOnce();
    expect(confirm.mock.calls[0][0]).toMatch(/"To do" items are removed/);
    expect(mocks.generateBacklog).not.toHaveBeenCalled();

    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: /Refresh backlog/ }));
    await waitFor(() => expect(mocks.generateBacklog).toHaveBeenCalledWith("p1"));
    confirm.mockRestore();
  });

  it("add item posts the title and closes the inline input", async () => {
    renderBoard(project({ backlog: [item(1, "todo")] }));
    fireEvent.click(screen.getByRole("button", { name: /Add item/ }));
    const input = screen.getByLabelText("New backlog item title");
    fireEvent.change(input, { target: { value: "New thing" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() =>
      expect(mocks.addBacklogItem).toHaveBeenCalledWith("p1", { title: "New thing" }),
    );
    await waitFor(() =>
      expect(screen.queryByLabelText("New backlog item title")).not.toBeInTheDocument(),
    );
  });

  it("run autonomously appears only for autonomous projects with todo work", () => {
    const { unmount } = renderBoard(
      project({ autonomous: true, backlog: [item(1, "todo")] }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Run autonomously ▸" }));
    expect(mocks.startAutonomous).toHaveBeenCalledWith("p1");
    unmount();
    renderBoard(project({ autonomous: false, backlog: [item(1, "todo")] }));
    expect(screen.queryByRole("button", { name: "Run autonomously ▸" })).not.toBeInTheDocument();
  });

  it("the Autonomous toggle enables autonomous on a project that lacks it", async () => {
    mocks.setAutonomous.mockResolvedValue(project({ autonomous: true }));
    // A project created without the flag: the toggle is the only way to enable it.
    renderBoard(project({ autonomous: false, backlog: [item(1, "todo")] }));
    const toggle = screen.getByRole("button", { name: /Auto-sweep off/ });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);
    await waitFor(() => expect(mocks.setAutonomous).toHaveBeenCalledWith("p1", true));
  });

  it("surfaces a server 409 in the toolbar error line", async () => {
    mocks.runBacklogItem.mockRejectedValue(new Error("409: another run is active"));
    renderBoard(project({ backlog: [item(1, "todo")] }));
    fireEvent.click(screen.getByRole("button", { name: "Run guided ▸" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/409/);
  });

  it("a blocked item shows a Blocked badge and its Run action is disabled", () => {
    // Item 2 (todo) depends on item 1, which isn't delivered → blocked_by non-empty.
    renderBoard(
      project({
        backlog: [
          item(1, "todo", { title: "Foundation" }),
          item(2, "todo", { title: "Dependent", depends_on: [1], blocked_by: [1] }),
        ],
      }),
    );
    const card = screen.getByRole("button", { name: "Open details for Dependent" });
    expect(within(card).getByText(/Blocked · 1/)).toBeInTheDocument();
    // The blocked item's Run button is disabled (backend also 409s).
    expect(within(card).getByRole("button", { name: "Run guided ▸" })).toBeDisabled();
  });

  it("an UNDER_SPECIFIED item shows the Needs-clarifying badge; a CHECKABLE one shows bound claims", () => {
    // ADR-0079/0080 Wave 3 stage 1: the checkability chip renders from the additive API fields.
    renderBoard(
      project({
        backlog: [
          item(1, "todo", { title: "Vague", checkability: "UNDER_SPECIFIED", claims: [] }),
          item(2, "todo", {
            title: "Crisp",
            checkability: "CHECKABLE",
            claims: [
              {
                id: "2-c1",
                item_id: 2,
                text: "prints every matching note",
                provenance: "ENTAILED",
                oracle_kind: "acceptance_test",
                material: true,
              },
            ],
          }),
        ],
      }),
    );
    const vague = screen.getByRole("button", { name: "Open details for Vague" });
    expect(within(vague).getByText(/Needs clarifying/i)).toBeInTheDocument();
    const crisp = screen.getByRole("button", { name: "Open details for Crisp" });
    expect(within(crisp).getByText(/1 claims bound/)).toBeInTheDocument();
  });

  it("a CHECKABLE but UNDECIDABLE item is called out separately from a vague one", () => {
    // The dangerous cell: the check binds, so "Needs clarifying" never fires and the card used
    // to read as clean — the shape that shipped 48 green tests over an invented scoring model.
    renderBoard(
      project({
        backlog: [
          item(1, "todo", {
            title: "Scorer",
            checkability: "CHECKABLE",
            decidability: "UNDECIDABLE",
            claims: [],
          }),
        ],
      }),
    );
    const card = screen.getByRole("button", { name: "Open details for Scorer" });
    expect(within(card).getByText(/One answer\?/i)).toBeInTheDocument();
    expect(within(card).queryByText(/Needs clarifying/i)).not.toBeInTheDocument();
  });

  it("an UNREACHABLE item says so on the board, not at launch (#121)", () => {
    // The third intake axis (F76, #78) has been computed and SERVED since it shipped and was never
    // rendered, so "the engine has no tool for this work" surfaced only as a 409 after the operator
    // had already committed to running it. Item 88 cost five runs and ~2.9M tokens to that silence.
    renderBoard(
      project({
        backlog: [
          item(1, "todo", {
            title: "Untrack the egg-info",
            checkability: "CHECKABLE",
            reachability: "UNREACHABLE",
            claims: [],
          }),
        ],
      }),
    );
    const card = screen.getByRole("button", { name: "Open details for Untrack the egg-info" });
    expect(within(card).getByText(/Can't be built/i)).toBeInTheDocument();
    // It is a DIFFERENT problem from an unclear spec: this item is perfectly clear and still
    // impossible, so the clarify badges must not fire and send the operator to reword it.
    expect(within(card).queryByText(/Needs clarifying/i)).not.toBeInTheDocument();
    expect(within(card).queryByText(/One answer\?/i)).not.toBeInTheDocument();
  });

  it("a REACHABLE item is not badged — the board stays quiet when nothing is wrong", () => {
    renderBoard(
      project({
        backlog: [item(1, "todo", { title: "Fine", reachability: "REACHABLE", claims: [] })],
      }),
    );
    const card = screen.getByRole("button", { name: "Open details for Fine" });
    expect(within(card).queryByText(/Can't be built/i)).not.toBeInTheDocument();
  });

  it("settled work authored before the intake checks is marked pre-standard, not wrong", () => {
    renderBoard(
      project({
        backlog: [
          item(1, "done", {
            title: "Old scorer",
            compliant: false,
            compliance_reasons: ["the text names a value it never states a rule for"],
          }),
          item(2, "done", { title: "Good one", compliant: true }),
          // A todo item already carries its own chips; a third saying the same thing is noise.
          item(3, "todo", { title: "Fresh", compliant: false, checkability: "UNDER_SPECIFIED" }),
        ],
      }),
    );
    const old = screen.getByRole("button", { name: "Open details for Old scorer" });
    expect(within(old).getByText(/Pre-standard/i)).toBeInTheDocument();
    const good = screen.getByRole("button", { name: "Open details for Good one" });
    expect(within(good).queryByText(/Pre-standard/i)).not.toBeInTheDocument();
    const fresh = screen.getByRole("button", { name: "Open details for Fresh" });
    expect(within(fresh).queryByText(/Pre-standard/i)).not.toBeInTheDocument();
    expect(within(fresh).getByText(/Needs clarifying/i)).toBeInTheDocument();
  });

  it("the clarify card accepts a proposal with one click (ADR-0080)", async () => {
    mocks.resolveClarification.mockResolvedValue(
      item(1, "todo", { title: "Vague", acceptance: "prints every matching note" }),
    );
    renderBoard(
      project({
        backlog: [
          item(1, "todo", {
            title: "Vague",
            checkability: "UNDER_SPECIFIED",
            clarification: {
              claim_text: "everything wired up nicely",
              why_unbindable: "no observable behaviour",
              proposals: ["prints every matching note in id order; exits 0 on no match"],
              proposal_kind: "acceptance",
              axis: "checkability",
              status: "open",
              asked_at: "2026-08-03T00:00:00",
            },
          }),
        ],
      }),
    );
    // The board shows the question badge; open the sheet and accept the proposal.
    fireEvent.click(screen.getByRole("button", { name: "Open details for Vague" }));
    expect(screen.getByText(/Quincy asks/i)).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: /prints every matching note in id order/i }),
    );
    await waitFor(() =>
      expect(mocks.resolveClarification).toHaveBeenCalledWith("p1", 1, {
        accepted_proposal_index: 0,
      }),
    );
  });

  it("a DIRECTION ask offers no one-click bar change (ADR-0091)", async () => {
    // The ESCALATE arm's proposals are instructions for a human ("amend the criteria so
    // tests/x.py can pass"). Rendering those as buttons is what let one click make that sentence
    // the item's acceptance. They must appear as context, with no clickable path to the bar.
    renderBoard(
      project({
        backlog: [
          item(1, "todo", {
            title: "Blocked",
            clarification: {
              claim_text: "This item's acceptance cannot be met as written (tests/test_add.py).",
              why_unbindable: "every failing test is protected",
              proposals: ["Amend the acceptance criteria so tests/test_add.py can pass as written."],
              proposal_kind: "direction",
              axis: "reachability",
              status: "open",
              asked_at: "2026-08-08T00:00:00",
            },
          }),
        ],
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Open details for Blocked" }));
    expect(screen.getByText(/Amend the acceptance criteria/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Amend the acceptance criteria/i }),
    ).not.toBeInTheDocument();

    // ...and the operator can say the bar is right without reaching for "Dismiss".
    fireEvent.click(screen.getByRole("button", { name: /the code is wrong/i }));
    await waitFor(() =>
      expect(mocks.resolveClarification).toHaveBeenCalledWith("p1", 1, {
        disposition: "bar_stands_retry",
      }),
    );
  });

  it("the depends-on selector persists via setItemDependencies", async () => {
    renderBoard(
      project({
        backlog: [
          item(1, "todo", { title: "Foundation" }),
          item(2, "todo", { title: "Dependent" }),
        ],
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Open details for Dependent" }));
    const dialog = await screen.findByRole("dialog");
    // Tick "Foundation" as a dependency, then save.
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Depend on Foundation" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Save dependencies" }));
    await waitFor(() =>
      expect(mocks.setItemDependencies).toHaveBeenCalledWith("p1", 2, [1]),
    );
  });
});

describe("curate", () => {
  beforeEach(() => {
    mocks.curateBacklog.mockReset();
    mocks.curateBacklog.mockResolvedValue({ changeset: [] });
  });

  it("collects the focus inline, never through a native browser dialog", async () => {
    // `window.prompt` froze the whole tab, could not be styled, and rendered as an
    // "app.mosaera.dev says" box that reads like a phishing prompt rather than the product.
    const nativePrompt = vi.spyOn(window, "prompt");
    renderBoard(project({ backlog: FULL_BOARD }));

    fireEvent.click(screen.getByRole("button", { name: /curate backlog/i }));
    expect(nativePrompt).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/curation focus/i), {
      target: { value: "fold the duplicates" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^curate$/i }));

    await waitFor(() =>
      expect(mocks.curateBacklog).toHaveBeenCalledWith("p1", "fold the duplicates"),
    );
    nativePrompt.mockRestore();
  });

  it("treats an empty focus as the full pass rather than a cancel", async () => {
    // Unlike "Add item", a blank field is MEANINGFUL here — it is the whole-backlog pass — so it
    // must still submit. Bailing on blank would make the default action unreachable.
    // It arrives as `undefined`, not "": the workspace maps a blank focus to an omitted field so
    // the request body carries no instruction at all, which is what it did before this change.
    renderBoard(project({ backlog: FULL_BOARD }));

    fireEvent.click(screen.getByRole("button", { name: /curate backlog/i }));
    fireEvent.click(screen.getByRole("button", { name: /^curate$/i }));

    await waitFor(() => expect(mocks.curateBacklog).toHaveBeenCalledWith("p1", undefined));
  });

  it("cancels without asking Quincy anything", async () => {
    renderBoard(project({ backlog: FULL_BOARD }));

    fireEvent.click(screen.getByRole("button", { name: /curate backlog/i }));
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

    expect(mocks.curateBacklog).not.toHaveBeenCalled();
    expect(screen.queryByLabelText(/curation focus/i)).toBeNull();
  });

  it("a DEFERRED item can be put back in the queue — no state the operator cannot leave", async () => {
    /* F66 (#93), found driving the project through the UI (case study #2, 2026-08-23): the sweep
       could defer an item and the sheet then offered only Edit and Ask PM — no run, no un-defer,
       no status control — on a column the board itself labels "needs attention". The only way out
       was asking the PM, which had to DELETE and re-create the item, destroying its run history. */
    renderBoard(project({ backlog: [item(7, "deferred")] }));
    fireEvent.click(await screen.findByText("item 7"));
    const back = await screen.findByRole("button", { name: "Put back in the queue" });
    fireEvent.click(back);
    await waitFor(() =>
      expect(mocks.patchBacklogItem).toHaveBeenCalledWith("p1", 7, { status: "todo" }),
    );
  });

  it("the run controls stay gated on todo, so un-deferring is what reveals them", async () => {
    // Two steps on purpose: putting it back in the queue is a decision, running it is another.
    renderBoard(project({ backlog: [item(8, "deferred")] }));
    fireEvent.click(await screen.findByText("item 8"));
    expect(screen.queryByRole("button", { name: /Run item/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Put back in the queue" })).toBeInTheDocument();
  });

  it("review offers the DELIVERING run's evidence before the approve button (F68/F69)", async () => {
    /* Driving LedgerCLI (case study #2) I was asked to approve nine items with no diff and no
       labelled evidence link; the run was reachable only as a mono id beside the approve button,
       and hitting it by accident ejected me from the board. The link is now labelled, listed
       first, and points at the run that DELIVERED rather than the newest attempt. */
    const delivered = run({ id: "r-delivered", item_id: 9, status: "APPROVED" });
    const cancelledLater = run({ id: "r-cancelled", item_id: 9, status: "CANCELLED" });
    renderBoard(
      project({ backlog: [item(9, "in_review")], runs: [cancelledLater, delivered] }),
    );
    fireEvent.click(await screen.findByText("item 9"));
    const evidence = (await screen.findByText("See what changed")).closest("a") as HTMLAnchorElement;
    expect(evidence).not.toBeNull();
    expect(evidence.getAttribute("href")).toContain("r-delivered");
    expect(evidence.getAttribute("href")).not.toContain("r-cancelled");
    expect(screen.getByRole("button", { name: "Approve — mark done" })).toBeInTheDocument();
  });
});
