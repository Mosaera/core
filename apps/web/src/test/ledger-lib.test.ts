import { describe, expect, it } from "vitest";

import type {
  BacklogItem,
  GatePayload,
  RunDetail,
  TranscriptEvent,
} from "../api/client";
import { deriveLedger, honestyBadge, type LedgerRow } from "../lib/ledger";

function detail(over: Partial<RunDetail> = {}): RunDetail {
  return {
    id: "r1", task: "Add tagging", status: "APPROVED", tests_passed: true, iterations: 1,
    commit_sha: "abc", source: "s", branch: "b", project_id: "p1", item_id: 14,
    created_at: "2026-08-03T09:00:00Z", decisions: [], test_results: [], repo_changes: [],
    approvals: [], ...over,
  };
}

function item(over: Partial<BacklogItem> = {}): BacklogItem {
  return {
    id: 14, project_id: "p1", title: "Add tagging", description: "Add tagging to the journal app.",
    acceptance: "tags persist across restart", status: "in_review", position: 0,
    iteration: null, locked: false, lock_reason: "", branch: "", mr_url: "", created_at: "t",
    ...over,
  } as BacklogItem;
}

function claimRow(over: Partial<RunDetail["claims"] extends (infer T)[] | undefined ? T : never> = {}) {
  return {
    claim_id: "14-c1", text: "tags persist", verdict: "satisfied",
    oracle_ref: "test_tags_persist", material: true, provenance: "ENTAILED",
    oracle_kind: "acceptance_test", ...over,
  };
}

const RECEIPT_ROW = {
  kind: "receipt",
  content: JSON.stringify({
    action: "deliver", reasons: [], reviewer_verdict: "APPROVE", tests_passed: true,
    oracle_verified: true, validation_strength: "suite", unsatisfied_claims: [],
    human_override: false, oracle_vouched_by: "", oracle_residual: "",
    tests_mutation_caught: true,
  }),
  created_at: null,
};

function kinds(rows: LedgerRow[]): string[] {
  return rows.map((r) => r.kind);
}

describe("deriveLedger — structural order", () => {
  it("a delivered run yields brief → decomposition → run-start → delivered → seal", () => {
    const rows = deriveLedger({
      detail: detail({
        claims: [claimRow()],
        decisions: [RECEIPT_ROW],
        finished_at: "2026-08-03T12:00:00Z",
        engine_version: "0.6.0",
        receipt_id: "f".repeat(64),
      }),
      item: item(),
    });
    // No interrupt/approval evidence → no gate row (a clean autonomous ship).
    expect(kinds(rows)).toEqual([
      "brief", "decomposition", "run-start", "review", "delivered", "seal",
    ]);
    const seal = rows.at(-1)!;
    expect(seal.kind === "seal" && seal.engineVersion).toBe("0.6.0");
  });

  it("an ad-hoc run (no item) still yields a brief from the task", () => {
    const rows = deriveLedger({ detail: detail() });
    const brief = rows.find((r) => r.kind === "brief")!;
    expect(brief.kind === "brief" && brief.title).toBe("Add tagging");
  });

  it("a legacy pre-claims run has no decomposition and no gate/review noise", () => {
    const rows = deriveLedger({ detail: detail({ status: "NOT APPROVED" }) });
    expect(kinds(rows)).toEqual(["brief", "run-start", "terminated", "seal"]);
  });
});

describe("deriveLedger — the gate lifecycle", () => {
  const gate: GatePayload = {
    action: "deliver",
    gate_decision: {
      action: "require_human", reasons: ["oracle_unverified"], tests_passed: true,
      reviewer_verdict: "APPROVE",
    },
    oracle_residual: "shape: proven · UNPROVEN: a mutation survives",
  };

  it("a live parked gate is one interactive row carrying the payload", () => {
    const rows = deriveLedger({
      detail: detail({ status: "AWAITING_APPROVAL" }),
      live: { gate, status: "awaiting_approval", startedAt: null },
    });
    const g = rows.find((r) => r.kind === "gate")!;
    expect(g.kind === "gate" && g.interactive).toBe(true);
    expect(g.kind === "gate" && g.gate).toBe(gate);
    expect(g.kind === "gate" && g.receipt?.oracleResidual).toContain("UNPROVEN");
  });

  it("after the approval persists, the same slot re-derives as gate + operator-answer (no dup)", () => {
    const rows = deriveLedger({
      detail: detail({
        status: "APPROVED",
        decisions: [RECEIPT_ROW],
        approvals: [
          { action: "deliver", approved: true, feedback: "ship it", created_at: "2026-08-03T11:41:00Z" },
        ],
      }),
      // live still mounted but the run has settled — the payload must NOT re-render
      live: { gate, status: "completed", startedAt: null },
    });
    const gates = rows.filter((r) => r.kind === "gate");
    expect(gates).toHaveLength(1);
    expect(gates[0].kind === "gate" && gates[0].interactive).toBe(false);
    const answer = rows.find((r) => r.kind === "operator-answer")!;
    expect(answer.kind === "operator-answer" && answer.feedback).toBe("ship it");
  });

  it("interrupt events give past gates their honest park times", () => {
    const events: TranscriptEvent[] = [
      { seq: 1, type: "update", node: "plan", ts: 1000, data: null },
      { seq: 2, type: "interrupt", node: "gate", ts: 5000, data: null },
    ];
    const rows = deriveLedger({
      detail: detail({
        status: "APPROVED",
        approvals: [{ action: "deliver", approved: true, feedback: "", created_at: null }],
      }),
      events,
    });
    const g = rows.find((r) => r.kind === "gate")!;
    expect(g.ts).toBe(5000);
    const start = rows.find((r) => r.kind === "run-start")!;
    expect(start.ts).toBe(1000); // first event, not the clustered persist stamps
  });

  it("the failing validation step surfaces on the settling gate", () => {
    const rows = deriveLedger({
      detail: detail({
        status: "INCOMPLETE",
        test_results: [
          { passed: false, output: "[step pytest: exit code 1]\nAssertionError: [] != ['a']", created_at: null },
        ],
        approvals: [{ action: "deliver", approved: false, feedback: "", created_at: null }],
      }),
    });
    const g = rows.find((r) => r.kind === "gate")!;
    expect(g.kind === "gate" && g.failingStep?.name).toBe("pytest");
    expect(g.kind === "gate" && g.failingStep?.output).toContain("AssertionError");
  });
});

describe("deriveLedger — clarification exchange", () => {
  const record = {
    claim_text: "keep it tidy", why_unbindable: "not checkable",
    proposals: ["3-module layout"], status: "resolved" as const,
    asked_at: "2026-08-03T09:13:00Z", resolution: "3-module layout, functions ≤ 20 lines",
    resolved_at: "2026-08-03T09:14:00Z",
  };

  it("a resolved exchange renders read-only with the recorded answer", () => {
    const rows = deriveLedger({ detail: detail(), item: item({ clarification_record: record }) });
    const c = rows.find((r) => r.kind === "clarification")!;
    expect(c.kind === "clarification" && c.interactive).toBe(false);
    expect(c.kind === "clarification" && c.record.resolution).toContain("3-module layout");
  });

  it("an open ask on a live run is interactive", () => {
    const rows = deriveLedger({
      item: item({ clarification_record: { ...record, status: "open" } }),
      live: { gate: null, status: "running", startedAt: 100 },
    });
    const c = rows.find((r) => r.kind === "clarification")!;
    expect(c.kind === "clarification" && c.interactive).toBe(true);
  });
});

describe("honestyBadge", () => {
  it("clean ONLY when delivered and every material claim satisfied", () => {
    const clean = deriveLedger({
      detail: detail({ claims: [claimRow()], decisions: [RECEIPT_ROW] }),
    });
    expect(honestyBadge(clean)).toEqual({ kind: "clean", count: 0 });
    const dirty = deriveLedger({
      detail: detail({
        claims: [claimRow(), claimRow({ claim_id: "c2", verdict: "unevaluable" })],
        decisions: [RECEIPT_ROW],
      }),
    });
    // unevaluable NEVER counts as verified.
    expect(honestyBadge(dirty)).toEqual({ kind: "unverified", count: 1 });
  });

  it("a delivery with zero bound claims is no-claims, never clean", () => {
    const rows = deriveLedger({ detail: detail({ decisions: [RECEIPT_ROW] }) });
    expect(honestyBadge(rows)).toEqual({ kind: "no-claims", count: 0 });
  });

  it("a non-delivery is 'nothing'", () => {
    const rows = deriveLedger({ detail: detail({ status: "INCOMPLETE" }) });
    expect(honestyBadge(rows)).toEqual({ kind: "nothing", count: 0 });
  });
});

describe("review counts use the backend's actual critic tokens", () => {
  it("INSUFFICIENT_EVIDENCE is counted (the old exact-match counted zero)", () => {
    const rows = deriveLedger({
      detail: detail({
        decisions: [
          RECEIPT_ROW,
          {
            kind: "critic",
            content: JSON.stringify({
              vetoed: false,
              rows: [
                { claim: "a", verdict: "SUPPORTED" },
                { claim: "b", verdict: "INSUFFICIENT_EVIDENCE" },
                { claim: "c", verdict: "DISCARDED" },
              ],
            }),
            created_at: null,
          },
        ],
      }),
    });
    const review = rows.find((r) => r.kind === "review")!;
    expect(review.kind === "review" && review.counts).toEqual({
      supported: 1,
      insufficient: 1,
      discarded: 1,
    });
  });
});

describe("row-attached artifacts (#63 redesign)", () => {
  it("rows carry their artifacts; absent decisions read as empty strings", () => {
    const rows = deriveLedger({
      detail: detail({
        claims: [claimRow()],
        decisions: [
          RECEIPT_ROW,
          { kind: "plan", content: "1. read\n2. extract", created_at: null },
          { kind: "design", content: "## Approach", created_at: null },
          { kind: "review", content: "VERDICT: APPROVE\nClean.", created_at: null },
          { kind: "scan", content: "1 low finding", created_at: null },
          { kind: "critic", content: JSON.stringify({ vetoed: false, rows: [] }), created_at: null },
        ],
        test_results: [
          { passed: true, output: "[step pytest: exit code 0]\n3 passed", created_at: null },
        ],
        repo_changes: [{ diff: "diff --git a/x b/x", commit_sha: "c", created_at: null }],
        approvals: [{ action: "deliver", approved: true, feedback: "", created_at: null }],
      }),
    });
    const decomp = rows.find((r) => r.kind === "decomposition")!;
    expect(decomp.kind === "decomposition" && decomp.planText).toContain("extract");
    expect(decomp.kind === "decomposition" && decomp.designText).toContain("Approach");
    const gate = rows.find((r) => r.kind === "gate")!;
    expect(gate.kind === "gate" && gate.validationOutput).toContain("3 passed");
    const review = rows.find((r) => r.kind === "review")!;
    expect(review.kind === "review" && review.reviewText).toContain("Clean.");
    const delivered = rows.find((r) => r.kind === "delivered")!;
    expect(delivered.kind === "delivered" && delivered.diff).toContain("diff --git");
    expect(delivered.kind === "delivered" && delivered.scanText).toBe("1 low finding");
    expect(delivered.kind === "delivered" && delivered.runId).toBe("r1");
  });

  it("unsourced artifacts are empty strings, never invented", () => {
    const rows = deriveLedger({ detail: detail({ claims: [claimRow()], decisions: [RECEIPT_ROW] }) });
    const decomp = rows.find((r) => r.kind === "decomposition")!;
    expect(decomp.kind === "decomposition" && decomp.planText).toBe("");
    const delivered = rows.find((r) => r.kind === "delivered")!;
    expect(delivered.kind === "delivered" && delivered.scanText).toBe("");
  });
});

describe("computeReceiptChecksum — honest null paths", () => {
  it("null when the seal inputs were never stamped", async () => {
    const { computeReceiptChecksum } = await import("../lib/ledger");
    expect(
      await computeReceiptChecksum({
        runId: "r1", commitSha: "c", engineVersion: null, receiptPayload: "{}",
      }),
    ).toBeNull();
    expect(
      await computeReceiptChecksum({
        runId: "r1", commitSha: "c", engineVersion: "0.6.0", receiptPayload: null,
      }),
    ).toBeNull();
  });
});

describe("the seal is honest", () => {
  it("null stamps stay null — never proxied", () => {
    const rows = deriveLedger({ detail: detail({ status: "NOT APPROVED" }) });
    const seal = rows.find((r) => r.kind === "seal")!;
    expect(seal.kind === "seal" && seal.engineVersion).toBeNull();
    expect(seal.kind === "seal" && seal.receiptId).toBeNull();
  });

  it("no seal row while the run is live", () => {
    const rows = deriveLedger({
      detail: detail({ status: "RUNNING" }),
      live: { gate: null, status: "running", startedAt: 1 },
    });
    expect(rows.some((r) => r.kind === "seal")).toBe(false);
  });
});

describe("NODE_TEXT — the shared per-node body whitelist (engine view widening)", () => {
  const ev = (node: string, update: Record<string, unknown>): TranscriptEvent => ({
    seq: 1,
    type: "update",
    node,
    ts: 100,
    data: { node, update },
  });

  it("surfaces design, authored tests, hygiene findings, critic verdict and gate reasons", async () => {
    const { transcriptItemsFromEvents } = await import("../lib/ledger");
    const items = transcriptItemsFromEvents([
      ev("design", { design: "normalize both sides" }),
      ev("author_tests", { authored_tests: ["tests/test_a.py", "tests/test_b.py"] }),
      ev("hygiene", { hygiene_findings: ["E501 line too long"] }),
      ev("critic", { outcome_verdict: { vetoed: false, reason: "evidence complete" } }),
      ev("gate", { gate_decision: { reasons: ["all claims verified", "tests green"] } }),
    ]);
    const bodies = items.filter((i) => i.kind === "body").map((i) => [i.node, i.body]);
    expect(bodies).toEqual([
      ["design", "normalize both sides"],
      ["author_tests", "tests/test_a.py\ntests/test_b.py"],
      ["hygiene", "E501 line too long"],
      ["critic", "no veto: evidence complete"],
      ["gate", "all claims verified\ntests green"],
    ]);
  });

  it("a vetoing critic reads as a veto, never softened", async () => {
    const { transcriptItemsFromEvents } = await import("../lib/ledger");
    const items = transcriptItemsFromEvents([
      ev("critic", { outcome_verdict: { vetoed: true, reason: "claim c2 unbound" } }),
    ]);
    expect(items.find((i) => i.kind === "body")?.body).toBe("vetoed: claim c2 unbound");
  });

  it("nodes with no recorded text stay silent — fix emits only its iteration", async () => {
    const { transcriptItemsFromEvents } = await import("../lib/ledger");
    const items = transcriptItemsFromEvents([
      ev("fix", { iteration: 3 }),
      ev("critic", { outcome_verdict: null }),
    ]);
    expect(items.filter((i) => i.kind === "body")).toHaveLength(0);
    // The phase (completion) lines still appear — silence is about bodies only.
    expect(items.filter((i) => i.kind === "phase")).toHaveLength(2);
  });
});
