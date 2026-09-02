import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { BacklogItem, HistoryRun, Project } from "../api/client";
import { ProjectOverview } from "../components/overview/ProjectOverview";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      projectMrStatus: vi.fn(() => Promise.resolve({ state: "opened", url: "https://gl/mr/1" })),
      projectDiff: vi.fn(() =>
        Promise.resolve({ base: "main", diff: "d", has_changes: true, files: ["a.py", "b.py"] }),
      ),
      projectFiles: vi.fn(() => Promise.resolve({ files: ["src/index.html"] })),
      projectMessages: vi.fn(() =>
        Promise.resolve({
          messages: [
            { role: "user", content: "status?", created_at: "2026-07-05T10:00:00Z" },
            { role: "pm", content: "Homepage hero is next.", created_at: "2026-07-05T10:01:00Z" },
          ],
        }),
      ),
      approveProject: vi.fn(),
      // Pre-registered for the Overview decision band (2026-08-22). Without it the band's query
      // issues a real relative-URL fetch under jsdom, degrades to an error state with
      // `retry: false`, and every assertion about the band passes while testing NOTHING — the
      // vacuous-pin failure this repo has now shipped three times. Registered BEFORE the band
      // exists so the first assertion written against it can actually fail.
      projectDecisions: vi.fn(() => Promise.resolve({ decisions: [] })),
      // ADR-0109's server aggregate. Rejected on purpose in the default fixture so the panel
      // tests exercise the client-side FALLBACK deliberately; the served path gets its own test.
      projectProof: vi.fn(() => Promise.reject(new Error("no aggregate in this fixture"))),
      projectPatchUrl: (id: string) => `/api/projects/${id}/patch`,
      projectFileUrl: (id: string, path: string) => `/api/projects/${id}/files/${path}`,
    },
  };
});

function item(id: number, status: string, title = `item ${id}`): BacklogItem {
  return {
    id, project_id: "p1", title, description: "", acceptance: "",
    status, position: id, iteration: null, created_at: "2026-07-01T10:00:00Z",
  };
}

function run(over: Partial<HistoryRun> = {}): HistoryRun {
  return {
    id: "r1", task: "build the hero", status: "APPROVED", tests_passed: true,
    iterations: 1, commit_sha: "abc", source: "src", branch: "b",
    project_id: "p1", item_id: null, created_at: "2026-07-02T10:00:00Z", ...over,
  };
}

function project(over: Partial<Project> = {}): Project {
  return {
    id: "p1", name: "Demo Project", source_repo: "/tmp/demo", goal: "Ship the site",
    brief: "## Goals\nShip it", status: "active", branch: "", mr_url: "",
    autonomous: false, has_gitlab_token: false, gitlab_token_masked: "",
    error: "", created_at: "2026-07-01T00:00:00Z", backlog: [], runs: [], ...over,
  };
}

function renderOverview(p: Project) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[`/projects/${p.id}/overview`]}>
        <ProjectOverview project={p} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ProjectOverview", () => {
  it("renders hero, pipeline and next action for an active project", async () => {
    renderOverview(
      project({
        backlog: [item(1, "todo", "first task"), item(2, "in_progress"), item(3, "in_review"), item(4, "done")],
        runs: [run()],
      }),
    );
    expect(screen.getByText("Demo Project")).toBeInTheDocument();
    expect(screen.getByText("Phase: Building")).toBeInTheDocument();
    expect(screen.getByText("Ship the site")).toBeInTheDocument();
    // Pipeline lanes (linked count tiles) + the live-numbers footer
    for (const label of ["Planned", "In progress", "Review", "Done"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(screen.getByText("Work pipeline")).toBeInTheDocument();
    // The lanes are COUNTS now (2026-08-22): the worklist above names the items that need
    // something, so listing titles in the lanes too rendered the same item twice on one page.
    // Exactly one render, and it is the worklist's.
    expect(screen.getAllByText(/first task/)).toHaveLength(1);
    expect(
      within(screen.getByRole("region", { name: "Worklist" })).getByText(/first task/),
    ).toBeInTheDocument();
    // The pipeline stats footer (runs / files changed / artifacts) was cut in the redundancy
    // audit 2026-08-22 — each number's own page states it.
    expect(screen.queryByText("files changed")).not.toBeInTheDocument();
    expect(screen.queryByText("artifacts")).not.toBeInTheDocument();
    // The worklist names the VERB for every open item. Item 3 is in_review, so it appears under
    // "Review and accept" — a bucket, not a single rule-derived "next action" that could name
    // only one thing to do. (The old negative pin on the nextAction string was left behind here
    // and would have passed vacuously forever once that derivation was deleted.)
    const worklist = screen.getByRole("region", { name: "Worklist" });
    expect(within(worklist).getByText("Review and accept")).toBeInTheDocument();
    expect(within(worklist).getByText(/item 3/)).toBeInTheDocument();
    expect(screen.getByText(/1 item waiting for review/)).toBeInTheDocument();
  });

  it("a parked last run outranks 'work is in flight' when nothing is running", () => {
    renderOverview(
      project({
        backlog: [item(1, "in_progress"), item(2, "done")],
        // item_id matters: the ladder reads a verdict from the item's OWN attempts. An unlinked
        // run is ad-hoc and diagnoses nothing — the fixture said "parked item" while modelling a
        // run that belonged to no item.
        runs: [
          run({
            status: "INCOMPLETE",
            tests_passed: null,
            item_id: 1,
            termination_reason: "budget",
            diagnosis: { outcome: "honest_park", park_cause: "give_up" } as never,
          }),
        ],
      }),
    );
    // Both "Work is in flight" and "Look at the last run" were nextAction strings; once that
    // derivation was scoped to lifecycle-only (2026-08-22) a negative pin on them could never
    // fail again. Asserting the replacement instead: the parked item lands under a real verb.
    expect(screen.getByText(/Last run parked — needs your look/)).toBeInTheDocument();
    const worklist = screen.getByRole("region", { name: "Worklist" });
    expect(within(worklist).getByText("Judge or re-scope")).toBeInTheDocument();
  });

  it("opens the full brief in a drawer from the charter band", () => {
    renderOverview(project({ brief: "## Goals\nShip the **whole** site fast." }));
    // The full brief lives behind an explicit affordance, not on the Artifacts tab only.
    const openBrief = screen.getByRole("button", { name: "View full brief" });
    fireEvent.click(openBrief);
    const drawer = screen.getByRole("dialog");
    expect(within(drawer).getByText("Project brief")).toBeInTheDocument();
    expect(within(drawer).getByText(/whole/)).toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: "Open in Artifacts" })).toHaveAttribute(
      "href",
      "/projects/p1/artifacts",
    );
  });

  it("shows clean empty states for a fresh active project", () => {
    renderOverview(project());
    expect(screen.getByText(/Building the backlog/)).toBeInTheDocument();
    // The pipeline empty state (the health card and its Delivery row are long gone —
    // healthRows was deleted as dead code, 2026-08-22).
    expect(screen.getAllByText("No backlog yet").length).toBeGreaterThan(0);
    expect(screen.getByText(/Nothing running right now/)).toBeInTheDocument();
    // The attention strip says so once, quietly.
    expect(screen.getByText(/Nothing needs you/)).toBeInTheDocument();
  });

  it("surfaces a failed run in the attention strip", () => {
    renderOverview(project({ runs: [run({ tests_passed: false, validation_status: "failed" })] }));
    expect(screen.getByText(/Last run validation failed — needs your look/)).toBeInTheDocument();
  });

  it("ready status points to the Start chat (intake), not a brief approval", () => {
    renderOverview(project({ status: "ready" }));
    expect(screen.getByText("Shape the project with Quincy")).toBeInTheDocument();
    expect(screen.getByText("Open Start")).toBeInTheDocument();
    expect(screen.queryByText(/Approve/)).not.toBeInTheDocument();
  });
});

describe("thrash signal", () => {
  it("surfaces an item that keeps failing the SAME way, above the ladder", async () => {
    const wall = ["validation_failed", "reviewer_unknown"];
    const attempt = (id: string, at: string): HistoryRun =>
      ({
        id, task: "t", status: "INCOMPLETE", tests_passed: false, iterations: 1, commit_sha: "",
        source: "s", branch: "b", project_id: "p1", item_id: 1, validation_status: "failed",
        created_at: at, diagnosis: { outcome: "honest_park", gate_reasons: wall },
      }) as HistoryRun;
    renderOverview(
      project({
        backlog: [item(1, "in_progress", "pipe-delimited output")],
        runs: [attempt("a", "2026-08-22"), attempt("b", "2026-08-21"), attempt("c", "2026-08-20")],
      }),
    );
    const worklist = await screen.findByRole("region", { name: "Worklist" });
    expect(within(worklist).getByText("Stop retrying")).toBeInTheDocument();
    expect(within(worklist).getByText(/same failure 3 times running/)).toBeInTheDocument();
    // The signature is named, so the operator knows WHAT wall it is.
    expect(within(worklist).getByText(/validation failed · reviewer unknown/)).toBeInTheDocument();
  });
});

describe("ProofCard — project-wide, independence first", () => {
  const delivered = (id: string, over: Record<string, unknown> = {}): HistoryRun =>
    ({
      id, task: "t", status: "APPROVED", tests_passed: true, iterations: 1, commit_sha: "abc",
      source: "s", branch: "b", project_id: "p1", item_id: Number(id.charCodeAt(0)),
      validation_status: "pass", created_at: "2026-08-22", receipt_id: "9f".padEnd(64, "0"),
      diagnosis: { outcome: "clean_deliver", gate_reasons: [], tests_modified: false, ...over },
    }) as HistoryRun;

  it("honest empty state: nothing delivered -> a sentence, never a shape", async () => {
    renderOverview(project({ runs: [] }));
    expect(await screen.findByText(/Nothing has delivered yet/)).toBeInTheDocument();
    expect(document.querySelector('[aria-label^="Proof radar"]')).toBeNull();
  });

  it("leads with independence and shows the MEASURED denominator, not the delivered count", async () => {
    // Two deliveries: one recorded "no independent vouch", one recorded nothing at all. The
    // second is not a failure — the vouch field returned "" on every run before the instrument
    // was wired — so the denominator is 1, not 2, and the difference is stated in the open.
    renderOverview(
      project({
        runs: [
          delivered("a", { vouch: "no_vouch:not_behavior_preserving" }),
          delivered("b", { vouch: "" }),
        ],
      }),
    );
    // The counts live ON the chart, one denominator per spoke — asserted through its accessible
    // label, which is also what a screen reader gets (the SVG text is decorative to it).
    const chart = await screen.findByRole("img", { name: /Project proof/ });
    expect(chart).toHaveAccessibleName(/Independence: 0 of 1/);
    // ...and the delivered population is stated separately, so the two numbers cannot be confused.
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("renders the SERVER aggregate's six axes when it answers (ADR-0109)", async () => {
    const { api } = await import("../api/client");
    vi.spyOn(api, "projectProof").mockResolvedValue({
      delivered: 2,
      axes: [
        { key: "independence", label: "Independence", note: "n", proven: 0, failed: 1, unknown: 1, measured: 1 },
        { key: "checks", label: "Checks", note: "n", proven: 2, failed: 0, unknown: 0, measured: 2 },
        { key: "integrity", label: "Integrity", note: "n", proven: 2, failed: 0, unknown: 0, measured: 2 },
        { key: "review", label: "Review", note: "n", proven: 1, failed: 0, unknown: 1, measured: 1 },
        { key: "security", label: "Security", note: "n", proven: 0, failed: 0, unknown: 2, measured: 0 },
        { key: "proof_depth", label: "Proof depth", note: "n", proven: 0, failed: 2, unknown: 0, measured: 2 },
      ],
      sources: { receipts_read: ["a", "b"], receipts_unreadable: [] },
    });
    renderOverview(project({ runs: [delivered("a")] }));
    // The three receipt-only axes exist only in the served payload — they cannot come from the
    // run list, so their presence proves the aggregate is what is rendering.
    // The chart mounts with the client-side fallback first, so wait for the served payload rather
    // than asserting on the first frame. The three receipt-only axes exist ONLY in that payload —
    // they cannot come from the run list, so their presence proves the aggregate is rendering.
    const chart = await screen.findByRole("img", { name: /Project proof/ });
    await waitFor(() => expect(chart).toHaveAccessibleName(/Review: 1 of 1/));
    expect(chart).toHaveAccessibleName(/Proof depth: 0 of 2/);
    // An axis nothing recorded says so; it never borrows a neighbour's verdict (ADR-0109 rule 2)
    // and it is never drawn as a zero.
    expect(chart).toHaveAccessibleName(/Security: not recorded/);
  });

  it("an empty gate-reasons list never becomes a green axis (green-by-vacancy)", async () => {
    renderOverview(project({ runs: [delivered("a")] }));
    // No vouch recorded on this delivery: the axis says so rather than counting the silence.
    // Asserted on the chart's label, where each axis states its own denominator.
    const chart = await screen.findByRole("img", { name: /Project proof/ });
    expect(chart).toHaveAccessibleName(/Independence: not recorded/);
    expect(chart).toHaveAccessibleName(/Checks: 1 of 1/);
  });
});
