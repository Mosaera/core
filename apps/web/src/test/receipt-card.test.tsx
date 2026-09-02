import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RunDetail } from "../api/client";
import {
  humanizeVouch,
  ReceiptCard,
  receiptFromDetail,
  receiptFromGate,
} from "../components/runs/ReceiptCard";

function detail(over: Partial<RunDetail> = {}): RunDetail {
  return {
    id: "r1", task: "t", status: "NOT APPROVED", tests_passed: true, iterations: 1,
    commit_sha: "", source: "s", branch: "b", project_id: null, item_id: null,
    created_at: null, decisions: [], test_results: [], repo_changes: [], approvals: [],
    ...over,
  };
}

const RECEIPT_ROW = {
  kind: "receipt",
  content: JSON.stringify({
    action: "require_human",
    reasons: ["oracle_unverified"],
    reviewer_verdict: "APPROVE",
    tests_passed: true,
    oracle_verified: false,
    validation_strength: "suite",
    unsatisfied_claims: [],
    human_override: false,
    oracle_vouched_by: "structural_claims:c1",
    oracle_residual: "shape: proven · UNPROVEN: a mutation of the changed code survives",
    tests_mutation_caught: false,
  }),
  created_at: null,
};

describe("receiptFromDetail", () => {
  it("joins the durable receipt row with the claim ledger", () => {
    const r = receiptFromDetail(
      detail({
        decisions: [RECEIPT_ROW],
        claims: [
          { claim_id: "c1", text: "keeps API", verdict: "satisfied", oracle_ref: "extract(a)" },
        ],
      }),
    )!;
    expect(r.action).toBe("require_human");
    expect(r.claims).toEqual([
      { id: "c1", text: "keeps API", verdict: "satisfied", oracleRef: "extract(a)" },
    ]);
    expect(r.oracleResidual).toContain("UNPROVEN");
  });

  it("returns undefined when nothing was recorded", () => {
    expect(receiptFromDetail(detail())).toBeUndefined();
    expect(receiptFromDetail(undefined)).toBeUndefined();
  });
});

describe("receiptFromGate", () => {
  it("normalizes the live payload; a dispositionless claim is unevaluable", () => {
    const r = receiptFromGate({
      action: "deliver",
      gate_decision: { action: "deliver", reasons: [], tests_passed: true, reviewer_verdict: "APPROVE" },
      claims: [{ id: "c1", text: "x" }],
      claim_dispositions: [],
    })!;
    expect(r.claims[0].verdict).toBe("unevaluable"); // never silently satisfied
    expect(r.testsMutationCaught).toBeNull(); // absent field stays honestly null
  });

  it("returns undefined without a gate_decision", () => {
    expect(receiptFromGate({ action: "deliver" })).toBeUndefined();
    expect(receiptFromGate(undefined)).toBeUndefined();
  });
});

describe("humanizeVouch", () => {
  it("reads structural vouches and no-vouch guards as sentences", () => {
    expect(humanizeVouch("structural_claims:c1,c2")).toBe(
      "The code's structure was independently verified to match the request (c1, c2).",
    );
    expect(humanizeVouch("no_vouch:not_behavior_preserving;tests_modified")).toBe(
      "No independent verification — not behavior preserving, tests modified",
    );
  });
});

describe("ReceiptCard rendering", () => {
  it("renders the full receipt: badges, residual, claims, critic veto", () => {
    render(
      <ReceiptCard
        receipt={
          receiptFromDetail(
            detail({
              decisions: [
                RECEIPT_ROW,
                { kind: "critic", content: JSON.stringify({ vetoed: true, reason: "spec unmet" }), created_at: null },
              ],
              claims: [
                { claim_id: "c1", text: "keeps API", verdict: "satisfied", oracle_ref: "extract(a)" },
                { claim_id: "c2", text: "no dead code", verdict: "failed", oracle_ref: "" },
              ],
            }),
          )!
        }
      />,
    );
    expect(screen.getByText("Known gap — accepted on record")).toBeInTheDocument();
    expect(screen.getByText(/Approving accepts this gap, on record/)).toBeInTheDocument();
    // sabotage missed = amber priced gap, not a red failure
    expect(screen.getByText(/sabotage missed/)).toBeInTheDocument();
    expect(screen.getByText("keeps API")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText("Independent reviewer veto")).toBeInTheDocument();
    expect(screen.getByText(/spec unmet/)).toBeInTheDocument();
  });

  it("shallow validation is never rendered green", () => {
    render(
      <ReceiptCard
        receipt={{
          action: "require_human", reasons: ["oracle_unverified"], reviewerVerdict: "UNKNOWN",
          testsPassed: true, oracleVerified: null, validationStrength: "shallow",
          unsatisfiedClaims: [], humanOverride: false, oracleVouchedBy: "",
          oracleResidual: "", testsMutationCaught: null, claims: [],
        }}
      />,
    );
    const badge = screen.getByText(/checks: shallow/);
    expect(badge.className).not.toContain("text-success");
    expect(screen.getByText(/behaviour wasn't tested/)).toBeInTheDocument();
  });

  it("standalone empty state is an honest EmptyNote", () => {
    render(<ReceiptCard receipt={undefined} />);
    expect(screen.getByText("No receipt recorded for this run.")).toBeInTheDocument();
  });
});
