import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RunDetail, RunSnapshot } from "../api/client";
import { RunWorkbench } from "../components/runs/RunWorkbench";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners: Record<string, (e: unknown) => void> = {};
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, cb: (e: unknown) => void) {
    this.listeners[type] = cb;
  }
  close() {}
}

const getRun = vi.fn();
const runDetail = vi.fn();
const runReport = vi.fn();
const approve = vi.fn((_id: string, _a: boolean, _f: string) => Promise.resolve({} as unknown));
vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      getRun: (id: string) => getRun(id),
      runDetail: (id: string) => runDetail(id),
      runReport: (id: string) => runReport(id),
      approve: (id: string, a: boolean, f: string) => approve(id, a, f),
    },
  };
});

function snap(over: Partial<RunSnapshot> = {}): RunSnapshot {
  return {
    run_id: "r1", status: "running", phase: "implement", started_at: 1,
    pending_interrupt: null, approved: null, report_path: null, commit_sha: null, ...over,
  };
}

function detail(over: Partial<RunDetail> = {}): RunDetail {
  return {
    id: "r1", task: "Build the hero", status: "APPROVED", tests_passed: true, iterations: 2,
    commit_sha: "deadbeef", source: "s", branch: "mosaera/r1", project_id: "p1", item_id: null,
    validation_status: "pass", created_at: null,
    decisions: [{ kind: "plan", content: "1. do the thing", created_at: null }],
    test_results: [{ passed: true, output: "[step pytest: exit code 0]\n3 passed", created_at: null }],
    repo_changes: [{ diff: "diff --git a/x b/x\n@@ -1 +1 @@\n-old\n+new", commit_sha: "deadbeef", created_at: null }],
    approvals: [],
    ...over,
  };
}

function renderWb(rid = "r1", projectId?: string) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <RunWorkbench rid={rid} projectId={projectId} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  FakeEventSource.instances = [];
  (globalThis as unknown as { EventSource: unknown }).EventSource = FakeEventSource;
  getRun.mockReset();
  runDetail.mockReset();
  runReport.mockReset();
  runReport.mockResolvedValue({ markdown: "## Report\n\nDelivered the hero." });
  approve.mockClear();
});

describe("RunWorkbench", () => {
  it("all-clear gate: primary action is Approve & deliver, wired to api.approve", async () => {
    getRun.mockResolvedValue(
      snap({
        status: "awaiting_approval",
        pending_interrupt: {
          id: "i1",
          value: {
            action: "deliver",
            summary: "approve delivery?",
            gate_decision: {
              action: "require_human", reasons: [], tests_passed: true, reviewer_verdict: "APPROVE",
            },
          },
        },
      }),
    );
    renderWb();
    // The gate docks collapsed (ADR-0101): open it, then decide.
    fireEvent.click(await screen.findByRole("button", { name: "Review" }));
    expect(await screen.findByRole("alertdialog", { name: "approval required" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve & deliver" }));
    await waitFor(() => expect(approve).toHaveBeenCalledWith("r1", true, ""));
  });

  it("reviewer-requested-changes gate leads with revise: primary sends back, override is secondary", async () => {
    getRun.mockResolvedValue(
      snap({
        status: "awaiting_approval",
        pending_interrupt: {
          id: "i2",
          value: {
            action: "deliver",
            review: "VERDICT: REQUEST_CHANGES\nSplit the function and add a guard clause.",
            iteration: 1,
            max_iterations: 3,
            gate_decision: {
              action: "require_human",
              reasons: ["reviewer_requested_changes"],
              tests_passed: true,
              reviewer_verdict: "REQUEST_CHANGES",
            },
          },
        },
      }),
    );
    renderWb();
    fireEvent.click(await screen.findByRole("button", { name: "Review" }));
    // Leads with the reviewer's actual request.
    expect(await screen.findByText("Reviewer requested changes")).toBeInTheDocument();
    // Revision budget is surfaced.
    expect(screen.getByText(/revision 2 of 3/i)).toBeInTheDocument();
    // The notes box is PREFILLED with the reviewer's changes (VERDICT stripped),
    // so the human doesn't retype what the reviewer already said.
    const box = screen.getByLabelText("feedback") as HTMLTextAreaElement;
    expect(box.value).toBe("Split the function and add a guard clause.");
    expect(screen.getByText(/Prefilled from the reviewer/)).toBeInTheDocument();
    // Primary action is enabled (prefilled) and sends the reviewer's changes.
    const sendBack = screen.getByRole("button", { name: /Send back to revise/ });
    expect(sendBack).toBeEnabled();
    fireEvent.click(sendBack);
    await waitFor(() =>
      expect(approve).toHaveBeenCalledWith("r1", false, "Split the function and add a guard clause."),
    );
    // Override exists but is the secondary, honestly labeled.
    // After deciding, the dock collapses (the optimistic gate-clear resets it) —
    // reopen it to see the still-pending mocked gate's secondary action.
    fireEvent.click(await screen.findByRole("button", { name: "Review" }, { timeout: 4000 }));
    expect(
      await screen.findByRole("button", { name: "Approve anyway" }, { timeout: 4000 }),
    ).toBeInTheDocument();
  });

  it("a sealed run leads with the verdict — the stage opens only from the rail", async () => {
    getRun.mockResolvedValue(snap({ status: "completed", commit_sha: "deadbeef" }));
    runDetail.mockResolvedValue(detail());
    renderWb();
    // After-action first: once sealed, no agent stage section until a chip is clicked.
    await waitFor(() => expect(document.querySelector("[data-work-agent]")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: /Deliver/ }));
    expect(document.querySelector("[data-work-agent]")).not.toBeNull();
  });

  it("terminal run: selecting Drift shows what was delivered — the diff", async () => {
    getRun.mockResolvedValue(snap({ status: "completed", commit_sha: "deadbeef" }));
    runDetail.mockResolvedValue(detail());
    renderWb();
    // The diff belongs to the agent that delivered it (#63): one panel, no dropdowns.
    fireEvent.click(await screen.findByRole("button", { name: /Deliver/ }));
    // The stage is an exclusive accordion — open the diff section explicitly.
    fireEvent.click(await screen.findByRole("button", { name: /What changed/ }));
    expect(await screen.findByText(/\+new/)).toBeInTheDocument();
  });

  it("a settled run closes with the verdict band and Drift's delivery report", async () => {
    getRun.mockResolvedValue(snap({ status: "completed", commit_sha: "deadbeef" }));
    runDetail.mockResolvedValue(
      detail({
        decisions: [
          {
            kind: "receipt",
            content: JSON.stringify({
              action: "deliver", reasons: [], reviewer_verdict: "APPROVE", tests_passed: true,
              oracle_verified: true, validation_strength: "suite", unsatisfied_claims: [],
              human_override: false, oracle_vouched_by: "", oracle_residual: "",
              tests_mutation_caught: true,
            }),
            created_at: null,
          },
        ],
      }),
    );
    renderWb();
    // Redundancy audit 2026-08-22: the hero's claims-only verdict sentence retired — the hero
    // states the STATUS, the receipt-derived VerdictCard states the proof. "Nothing was checked"
    // survives as the band's honest no-claims line below.
    expect(await screen.findByText("Delivered.")).toBeInTheDocument();
    // The band explains WHY it delivered, and never claims more than was checked.
    const verdict = await screen.findByRole("region", { name: "Why this delivered" });
    expect(
      within(verdict).getByText(/No claims were recorded for this run/),
    ).toBeInTheDocument();
    // No tabs anywhere — the work belongs to the agent that did it.
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Deliver/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Delivery report/ }));
    expect(await screen.findByText("Delivered the hero.")).toBeInTheDocument();
    expect(runReport).toHaveBeenCalledWith("r1");
  });

  it("durable-only run (live 404): falls back to the record instead of polling 'Running' forever", async () => {
    // A seeded row, or any finished run after an API restart evicts its session:
    // getRun 404s but the durable record exists — the page must become the record.
    getRun.mockRejectedValue(new Error("404 Not Found: unknown run"));
    runDetail.mockResolvedValue(detail());
    renderWb();
    // The hero settles on the durable verdict, never a stuck spinner — and states
    // it ONCE, as the status sentence (the redundant chip is gone for settled runs).
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/^Delivered/));
    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(screen.queryByText("Working")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel run" })).not.toBeInTheDocument();
    // The durable record renders — Mercury's panel carries what was delivered.
    fireEvent.click(await screen.findByRole("button", { name: /Deliver/ }));
    fireEvent.click(await screen.findByRole("button", { name: /What changed/ }));
    expect(await screen.findByText(/\+new/)).toBeInTheDocument();
  });

  it("no live session AND no durable record → an honest not-found page", async () => {
    getRun.mockRejectedValue(new Error("404 Not Found: unknown run"));
    runDetail.mockRejectedValue(new Error("404 Not Found: unknown run"));
    renderWb();
    expect(
      await screen.findByText(
        "This run isn't active and no record of it exists.",
        {},
        { timeout: 4000 }, // the detail query retries once (1s backoff) before erroring
      ),
    ).toBeInTheDocument();
  });

  it("the RECORD footer carries the audit facts: commit, files, quality, patch", async () => {
    getRun.mockResolvedValue(snap({ status: "completed", commit_sha: "deadbeef" }));
    runDetail.mockResolvedValue(
      detail({
        decisions: [
          { kind: "quality", content: JSON.stringify({ composite: 84, dimensions: [] }), created_at: null },
        ],
      }),
    );
    renderWb();
    await screen.findByText("84/100 advisory");
    expect(screen.getByText("deadbeef")).toBeInTheDocument();
    expect(screen.getByText("1 file +1 −1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /download patch/ })).toBeInTheDocument();
  });

  it("a missing report is an honest 404, never synthesized", async () => {
    getRun.mockResolvedValue(snap({ status: "completed" }));
    runDetail.mockResolvedValue(detail());
    runReport.mockRejectedValue(new Error("404 Not Found: no report recorded"));
    renderWb();
    fireEvent.click(await screen.findByRole("button", { name: /Deliver/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Delivery report/ }));
    expect(await screen.findByText("No report was recorded for this run.")).toBeInTheDocument();
  });

  it("incomplete run: shows the Incomplete badge and the honest reason", async () => {
    getRun.mockResolvedValue(
      snap({
        status: "incomplete",
        termination_reason: "reached the iteration limit without meeting acceptance",
      }),
    );
    runDetail.mockResolvedValue(
      detail({
        status: "INCOMPLETE", commit_sha: "", approvals: [],
        termination_reason: "reached the iteration limit without meeting acceptance",
      }),
    );
    renderWb();
    // The hero states the honest ending, not a success.
    expect(await screen.findByText("Ended without delivering.")).toBeInTheDocument();
    expect(screen.queryByText("Completed")).not.toBeInTheDocument();
    // Redundancy audit 2026-08-22: the hero's reason line retired (it rendered up to 4× per
    // page); the record ProofRow in the verdict band is the one render of the stored reason.
    const record = screen.getByText("What the record keeps").closest("section")!;
    expect(within(record).getByText(/reached the iteration limit/)).toBeInTheDocument();
  });

  });

describe("cancel run is reachable in every non-terminal state (#116)", () => {
  /* The stop control used to render ONLY inside the running hero, so it vanished the moment the run
     paused for a decision — and a thrashing run spends its life paused. Confirmed live twice on
     2026-08-24: `cancel run` was unreachable while parked at a write gate and reappeared only after
     answering one, which spends another model turn. The exit was gated behind the thing you were
     trying to stop. Measured cost of the first occurrence: 31 minutes and 1.29M tokens on a run that
     never executed a single validation. */

  it("is offered while the run is WORKING", async () => {
    getRun.mockResolvedValue(snap({ status: "running" }));
    renderWb();
    expect(await screen.findByRole("button", { name: /cancel run/i })).toBeTruthy();
  });

  it("is STILL offered while the run is paused at a write gate", async () => {
    getRun.mockResolvedValue(
      snap({
        status: "awaiting_approval",
        pending_interrupt: {
          id: "w1",
          value: { action: "write_file", summary: "Coder wants to write src/x.py", path: "src/x.py" },
        },
      }),
    );
    renderWb();
    // POSITIVE CONTROL: prove the run really is parked on a decision before asserting anything
    // about the exit. Without this the test passes in the RUNNING state and proves nothing — which
    // is exactly what the first version of it did.
    expect(await screen.findByRole("button", { name: "Review" })).toBeTruthy();
    // The way out must be present while the run is PARKED, not only while it is working. That
    // ordering is the whole bug: reaching the exit by answering the gate spends another model turn
    // on a run you have already decided to abandon.
    expect(await screen.findByRole("button", { name: /cancel run/i })).toBeTruthy();
  });

  it("is NOT offered once the run has settled", async () => {
    getRun.mockResolvedValue(snap({ status: "completed", approved: true, commit_sha: "abc1234" }));
    runDetail.mockResolvedValue(detail({ status: "APPROVED" }));
    renderWb();
    await screen.findByText(/Build the hero/i);
    expect(screen.queryByRole("button", { name: /cancel run/i })).toBeNull();
  });
});

describe("a parked run names WHY it is asking (#108)", () => {
  /* The engine records a real cause at the pause (`_record_pause_diagnosis`, 2026-08-23 — verified
     live: `park_cause: "under_specified"` where it was previously null). The gate panel still showed
     only what the gate could not find: "no checks were attempted / the reviewer's verdict couldn't be
     read / the run ended before the security scan could run". None of those name the cause, and an
     operator reading them has no move. Confirmed live on run 20260823-213141-35ce0e: the diagnosis
     was recorded and the page still showed the absence list. The vocabulary already existed
     (`plain.ts::stopReason`, `PARK_CAUSE`); nothing was rendering it here. */

  const parked = () =>
    snap({
      status: "awaiting_approval",
      pending_interrupt: {
        id: "g1",
        value: {
          action: "deliver",
          summary: "approve delivery?",
          gate_decision: {
            action: "require_human",
            reasons: ["validation_not_attempted"],
            tests_passed: null,
            reviewer_verdict: "UNKNOWN",
          },
        },
      },
    });

  it("shows the recorded cause, not only the list of absences", async () => {
    getRun.mockResolvedValue(parked());
    runDetail.mockResolvedValue(
      detail({
        status: "AWAITING_APPROVAL",
        diagnosis: {
          outcome: "honest_park",
          park_cause: "under_specified",
          plan_unworkable_reason:
            "under_specified: no material acceptance claim is checkable as written",
        },
      } as Partial<RunDetail>),
    );
    renderWb();
    fireEvent.click(await screen.findByRole("button", { name: "Review" }));
    // The plain sentence for the cause, not the raw token and not the absence list.
    expect(await screen.findByText(/too under-specified to start safely/i)).toBeTruthy();
  });

  it("says nothing when the engine recorded no cause — absence is not invented", async () => {
    getRun.mockResolvedValue(parked());
    runDetail.mockResolvedValue(detail({ status: "AWAITING_APPROVAL", diagnosis: null }));
    renderWb();
    fireEvent.click(await screen.findByRole("button", { name: "Review" }));
    await screen.findByRole("alertdialog", { name: "approval required" });
    expect(screen.queryByText(/why the run stopped/i)).toBeNull();
  });
});
