import { describe, expect, it } from "vitest";

import type { GatePayload } from "../api/client";
import { deriveLedger } from "../lib/ledger";
import type { RunDetail } from "../api/client";
import { deriveHeroVariant } from "../components/runs/hero/heroState";
import { claimSegments } from "../components/runs/hero/ClaimBar";

function detail(over: Partial<RunDetail> = {}): RunDetail {
  return {
    id: "r1", task: "t", status: "APPROVED", tests_passed: true, iterations: 1,
    commit_sha: "c", source: "s", branch: "b", project_id: null, item_id: null,
    created_at: null, decisions: [], test_results: [], repo_changes: [], approvals: [],
    ...over,
  };
}

const RECEIPT_ROW = {
  kind: "receipt",
  content: JSON.stringify({ action: "deliver", reasons: [], reviewer_verdict: "APPROVE",
    tests_passed: true, oracle_verified: true, validation_strength: "suite",
    unsatisfied_claims: [], human_override: false, oracle_vouched_by: "",
    oracle_residual: "", tests_mutation_caught: true }),
  created_at: null,
};

const GATE: GatePayload = { action: "deliver", gate_decision: {
  action: "require_human", reasons: [], tests_passed: true, reviewer_verdict: "APPROVE" } };

const base = { phase: "implement", startedAt: 1, terminationReason: null };

describe("deriveHeroVariant precedence", () => {
  it("a live parked gate always wins — the decision IS the page", () => {
    const rows = deriveLedger({ detail: detail({ decisions: [RECEIPT_ROW] }) });
    const v = deriveHeroVariant({ status: "awaiting_approval", gate: GATE, rows, ...base });
    expect(v.kind).toBe("needs-you");
    expect(v.kind === "needs-you" && v.flavor).toBe("delivery");
  });

  it("a budget park is the budget flavor", () => {
    const v = deriveHeroVariant({
      status: "awaiting_approval", gate: { action: "budget" }, rows: [], ...base,
    });
    expect(v.kind === "needs-you" && v.flavor).toBe("budget");
  });

  it("delivered → verdict hero with the honesty badge", () => {
    const rows = deriveLedger({ detail: detail({ decisions: [RECEIPT_ROW] }) });
    const v = deriveHeroVariant({ status: "completed", gate: null, rows, ...base });
    expect(v.kind).toBe("delivered");
    expect(v.kind === "delivered" && v.badge.kind).toBe("no-claims"); // no claims bound — honest
  });

  it("terminated → honest failure with the reason", () => {
    const rows = deriveLedger({
      detail: detail({ status: "INCOMPLETE", termination_reason: "iteration cap" }),
    });
    const v = deriveHeroVariant({ status: "incomplete", gate: null, rows, ...base });
    expect(v.kind === "terminated" && v.status).toBe("INCOMPLETE");
    expect(v.kind === "terminated" && v.reason).toBe("iteration cap");
    expect(v.kind === "terminated" && v.reasonIsFull).toBe(false);
  });

  it("terminated prefers the FULL diagnosis stop reason over the capped string", () => {
    const long = "x".repeat(120);
    const rows = deriveLedger({
      detail: detail({ status: "INCOMPLETE", termination_reason: "capped at eighty" }),
    });
    const v = deriveHeroVariant({
      status: "incomplete", gate: null, rows, ...base,
      diagnosis: { stall_reason: long },
    });
    expect(v.kind === "terminated" && v.reason).toBe(long);
    // Full text — the hero must NOT append its 80-char cap marker to it.
    expect(v.kind === "terminated" && v.reasonIsFull).toBe(true);
  });

  it("nothing settled → running with phase + start", () => {
    const v = deriveHeroVariant({ status: "running", gate: null, rows: [], ...base });
    expect(v).toEqual({ kind: "running", phase: "implement", startedAt: 1 });
  });
});

describe("claimSegments — the honesty rule", () => {
  const claim = (over: object) => ({
    id: "c", text: "t", provenance: "ENTAILED", oracleKind: "acceptance_test",
    material: true, verdict: "", oracleRef: "", ...over,
  });
  it("only a passed check is green; no verdict is NEVER green; preference is hollow", () => {
    const tones = claimSegments([
      claim({ id: "a", verdict: "satisfied" }),
      claim({ id: "b", verdict: "failed" }),
      claim({ id: "c", verdict: "unbound" }),
      claim({ id: "d", verdict: "unevaluable" }),
      claim({ id: "e", verdict: "" }), // pre-run
      claim({ id: "f", verdict: "satisfied", material: false }), // preference beats verdict
    ]).map((s) => s.tone);
    expect(tones).toEqual([
      "verified", "attention", "unchecked", "unchecked", "unchecked", "preference",
    ]);
  });
});
