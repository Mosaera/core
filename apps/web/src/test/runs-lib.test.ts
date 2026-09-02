import { describe, expect, it } from "vitest";

import type { HistoryRun, RunDetail } from "../api/client";
import {
  diagnoseValidationPrefill,
  explainRunPrefill,
  parkedRunPrefill,
  latestRun,
  taskBody,
  taskTitle,
  parseCriticVerdict,
  parseGateDecision,
  parseReceipt,
  historyRunHref,
  parseValidationPlan,
  slugifyTask,
  validationVerdict,
} from "../lib/runs";

function run(over: Partial<HistoryRun> = {}): HistoryRun {
  return {
    id: "r1", task: "Build the hero", status: "APPROVED", tests_passed: true, iterations: 1,
    commit_sha: "abc", source: "s", branch: "b", project_id: "p1", item_id: null,
    created_at: "2026-07-02T10:00:00Z", ...over,
  };
}

function detail(over: Partial<RunDetail> = {}): RunDetail {
  return {
    ...run(), decisions: [], test_results: [], repo_changes: [], approvals: [], ...over,
  };
}

/* `groupProjectRuns` / `runsSummary` were deleted with the item consolidation (de-firehose
 * phase 2) — their semantics live on, item-counted, in item-runs-lib.test.ts. */
describe("latestRun", () => {
  it("latestRun is the first element (API newest-first)", () => {
    expect(latestRun([run({ id: "new" }), run({ id: "old" })])?.id).toBe("new");
    expect(latestRun([])).toBeUndefined();
  });
});

describe("validationVerdict", () => {
  it("RUNNING runs are pending regardless of detail", () => {
    const v = validationVerdict(detail(), run({ status: "RUNNING" }));
    expect(v.kind).toBe("pending");
    expect(v.label).toBe("Validation pending");
    expect(v.helper).toBe("The run is still executing.");
  });

  it("settled run with no detail yet is a loading pending", () => {
    const v = validationVerdict(undefined, run());
    expect(v).toEqual({ kind: "pending", label: "Loading validation record…" });
  });

  it("empty test_results proves the test node never ran — no evidence", () => {
    const v = validationVerdict(detail({ test_results: [] }), run({ tests_passed: false }));
    expect(v.kind).toBe("no-evidence");
    expect(v.label).toBe("No validation evidence recorded");
    expect(v.helper).toBe("This run has no stored validation output.");
  });

  it("pytest exit-code-5 output means no test suite (both regex branches)", () => {
    for (const output of ["[exit code 5]\ncollected 0 items", "no tests ran in 0.12s"]) {
      const v = validationVerdict(
        detail({ test_results: [{ passed: false, output, created_at: null }] }),
        run({ tests_passed: false }),
      );
      expect(v.kind).toBe("no-tests");
      expect(v.label).toBe("No test suite detected");
    }
  });

  it("failed verdict; the approved helper appears only for APPROVED runs", () => {
    const failing = detail({
      tests_passed: false,
      test_results: [{ passed: false, output: "[exit code 1]\n1 failed", created_at: null }],
    });
    const approved = validationVerdict(failing, run({ tests_passed: false }));
    expect(approved.kind).toBe("failed");
    expect(approved.label).toBe("Validation failed");
    expect(approved.helper).toBe(
      "The agent completed and was approved, but validation did not pass. Review the run output before merging.",
    );
    const denied = validationVerdict(
      { ...failing, status: "NOT APPROVED" },
      run({ status: "NOT APPROVED", tests_passed: false }),
    );
    expect(denied.kind).toBe("failed");
    expect(denied.helper).toBeUndefined();
  });

  it("passing validation is Tests pass", () => {
    const v = validationVerdict(
      detail({ test_results: [{ passed: true, output: "[exit code 0]\n3 passed", created_at: null }] }),
      run(),
    );
    expect(v).toEqual({ kind: "pass", label: "Tests pass" });
  });

  it("planner-unavailable wins and carries the plan reason", () => {
    const plan = {
      project_type: "javascript",
      reason: "JavaScript project (package.json): no Node offline.",
      steps: [],
      results: [],
    };
    const v = validationVerdict(
      detail({
        validation_status: "unavailable",
        test_results: [],
        decisions: [{ kind: "validation_plan", content: JSON.stringify(plan), created_at: null }],
      }),
      run({ tests_passed: false }),
    );
    expect(v.kind).toBe("unavailable");
    expect(v.label).toBe("Validation unavailable");
    expect(v.helper).toBe("JavaScript project (package.json): no Node offline.");
  });

  it("unavailable without a parseable plan uses the generic helper", () => {
    const v = validationVerdict(
      detail({ validation_status: "unavailable", test_results: [] }),
      run(),
    );
    expect(v.kind).toBe("unavailable");
    expect(v.helper).toMatch(/no way to validate this project/);
  });

  it("multi-step evidence: any failing row means failed, all passing means pass", () => {
    const rows = [
      { passed: true, output: "[step py-compile: exit code 0]\nok", created_at: null },
      { passed: false, output: "[step html-check: exit code 1]\nbad", created_at: null },
    ];
    expect(
      validationVerdict(
        detail({ validation_status: "failed", tests_passed: false, test_results: rows }),
        run({ tests_passed: false }),
      ).kind,
    ).toBe("failed");
    const green = rows.map((r) => ({ ...r, passed: true }));
    expect(
      validationVerdict(
        detail({ validation_status: "pass", test_results: green }),
        run(),
      ).kind,
    ).toBe("pass");
  });

  it("the exit-5 regex is legacy-only: a planner row with status failed stays failed", () => {
    const v = validationVerdict(
      detail({
        validation_status: "failed",
        tests_passed: false,
        test_results: [
          { passed: false, output: "[step pytest: exit code 5]\nno tests ran", created_at: null },
        ],
      }),
      run({ tests_passed: false }),
    );
    expect(v.kind).toBe("failed");
  });

  it("parseValidationPlan tolerates garbage content", () => {
    expect(
      parseValidationPlan(
        detail({ decisions: [{ kind: "validation_plan", content: "{not json", created_at: null }] }),
      ),
    ).toBeUndefined();
    expect(parseValidationPlan(detail())).toBeUndefined();
  });
});

describe("PM prefills", () => {
  it("exact strings", () => {
    // summarizeRunsPrefill moved to item language (summarizeItemsPrefill) with the
    // consolidation; its exact-string pin lives beside it in item-runs-lib.test.ts.
    expect(explainRunPrefill(run())).toBe(
      'Explain the run "Build the hero" (r1). ' +
        "What did the agent do, what changed, and what was the outcome?",
    );
    expect(diagnoseValidationPrefill(run())).toBe(
      'The run "Build the hero" (r1) completed but its validation did not pass. ' +
        "Diagnose the likely cause and propose what to check or fix before merging.",
    );
    expect(diagnoseValidationPrefill(run())).not.toContain("failing tests");
  });
});

describe("parkedRunPrefill", () => {
  const diagnosis = {
    outcome: "thrash_park",
    park_cause: "stalled:plan",
    gate_reasons: ["tests_tampered", "validation_failed"],
    unsatisfied_claims: ["c1", "c2"],
    iteration: 1,
    max_iterations: 3,
    tests_modified: true,
    stall_reason:
      "No convergence — pre-existing/protected tests or their collection config were modified: tests/test_readme_examples.py",
  };

  it("carries the FULL uncapped reason, plain gate reasons and the ask", () => {
    const text = parkedRunPrefill(run({ status: "INCOMPLETE" }), diagnosis);
    expect(text).toContain('The run "Build the hero" (r1) stopped without delivering.');
    expect(text).toContain("Ground to a halt before stopping.");
    expect(text).toContain("re-planning in circles");
    // The full stop-channel text, past the 80-char DB cap — never the truncated string.
    expect(text).toContain("tests/test_readme_examples.py");
    // Plain English, not tokens.
    expect(text).toContain("the run modified the tests it was judged by");
    expect(text).not.toContain("tests_tampered");
    expect(text).toContain("2 claims were never verified.");
    expect(text).toContain("Propose how to unblock: re-scope, split, or drop");
  });

  it("degrades honestly without a diagnosis (pre-0022 rows)", () => {
    const text = parkedRunPrefill(run({ status: "CANCELLED" }), null);
    expect(text).toContain("Cancelled — nothing was delivered.");
    expect(text).not.toContain("Why it stopped:");
    expect(text).toContain("Propose how to unblock");
  });
});

describe("parseGateDecision", () => {
  const row = (content: string) => detail({ decisions: [{ kind: "gate_decision", content, created_at: null }] });

  it("returns undefined when there is no gate_decision row", () => {
    expect(parseGateDecision(detail())).toBeUndefined();
    expect(parseGateDecision(undefined)).toBeUndefined();
  });

  it("parses a clean auto-delivered decision", () => {
    const g = parseGateDecision(
      row("action=deliver; reasons=; verdict=APPROVE; tests_passed=True; human_override=False"),
    )!;
    expect(g.action).toBe("deliver");
    expect(g.reasons).toEqual([]);
    expect(g.verdict).toBe("APPROVE");
    expect(g.testsPassed).toBe(true);
    expect(g.humanOverride).toBe(false);
  });

  it("parses a human-override delivery over flagged signals", () => {
    const g = parseGateDecision(
      row(
        "action=require_human; reasons=validation_unavailable,reviewer_blocked; verdict=BLOCK; tests_passed=None; human_override=True",
      ),
    )!;
    expect(g.action).toBe("require_human");
    expect(g.reasons).toEqual(["validation_unavailable", "reviewer_blocked"]);
    expect(g.testsPassed).toBeNull();
    expect(g.humanOverride).toBe(true);
  });
});

describe("parseReceipt", () => {
  const receiptRow = (content: string) =>
    detail({ decisions: [{ kind: "receipt", content, created_at: null }] });

  it("prefers the JSON receipt row with every field", () => {
    const r = parseReceipt(
      receiptRow(
        JSON.stringify({
          action: "require_human", reasons: ["oracle_unverified"], reviewer_verdict: "APPROVE",
          tests_passed: true, oracle_verified: false, validation_strength: "suite",
          unsatisfied_claims: ["c1"], human_override: true,
          oracle_vouched_by: "structural_claims:c2",
          oracle_residual: "shape: proven · UNPROVEN: a mutation survives",
          tests_mutation_caught: false,
        }),
      ),
    )!;
    expect(r.action).toBe("require_human");
    expect(r.oracleVerified).toBe(false);
    expect(r.unsatisfiedClaims).toEqual(["c1"]);
    expect(r.oracleVouchedBy).toBe("structural_claims:c2");
    expect(r.oracleResidual).toContain("UNPROVEN");
    expect(r.testsMutationCaught).toBe(false);
    expect(r.humanOverride).toBe(true);
  });

  it("preserves null tri-states from the JSON row", () => {
    const r = parseReceipt(
      receiptRow(JSON.stringify({ action: "deliver", tests_passed: null, tests_mutation_caught: null })),
    )!;
    expect(r.testsPassed).toBeNull();
    expect(r.testsMutationCaught).toBeNull(); // never coerced into a verdict
  });

  it("falls back to the flat gate_decision string for older runs", () => {
    const r = parseReceipt(
      detail({
        decisions: [{
          kind: "gate_decision",
          content: "action=deliver; reasons=; verdict=APPROVE; tests_passed=True; validation_strength=suite; human_override=False",
          created_at: null,
        }],
      }),
    )!;
    expect(r.action).toBe("deliver");
    expect(r.validationStrength).toBe("suite");
    // Fields the flat contract never carried are honestly absent, not invented.
    expect(r.oracleVerified).toBeNull();
    expect(r.oracleResidual).toBe("");
    expect(r.testsMutationCaught).toBeNull();
  });

  it("malformed receipt JSON falls back to the flat string; nothing → undefined", () => {
    const r = parseReceipt(
      detail({
        decisions: [
          { kind: "receipt", content: "{not json", created_at: null },
          { kind: "gate_decision", content: "action=deliver; reasons=; verdict=APPROVE; tests_passed=True; human_override=False", created_at: null },
        ],
      }),
    )!;
    expect(r.action).toBe("deliver");
    expect(parseReceipt(detail())).toBeUndefined();
    expect(parseReceipt(undefined)).toBeUndefined();
  });
});

describe("parseCriticVerdict", () => {
  it("parses the critic decision row; malformed/absent → undefined", () => {
    const v = parseCriticVerdict(
      detail({
        decisions: [{ kind: "critic", content: JSON.stringify({ vetoed: true, reason: "spec unmet" }), created_at: null }],
      }),
    );
    expect(v?.vetoed).toBe(true);
    expect(parseCriticVerdict(detail())).toBeUndefined();
    expect(
      parseCriticVerdict(detail({ decisions: [{ kind: "critic", content: "??", created_at: null }] })),
    ).toBeUndefined();
  });
});

describe("slugifyTask + historyRunHref", () => {
  it("makes a url-safe slug, trimming and capping", () => {
    expect(slugifyTask("Add login backoff!")).toBe("add-login-backoff");
    expect(slugifyTask("  Fix   the/Bug  ")).toBe("fix-the-bug");
    expect(slugifyTask("!!!")).toBe("");
    expect(slugifyTask("x".repeat(80)).length).toBeLessThanOrEqual(50);
  });

  it("appends the slug tail only when a task is given; id stays authoritative", () => {
    expect(historyRunHref("r1", "p1")).toBe("/projects/p1/history/r1");
    expect(historyRunHref("r1", "p1", "Build the hero")).toBe(
      "/projects/p1/history/r1/build-the-hero",
    );
    expect(historyRunHref("r1", null, "Build the hero")).toBe("/history/r1/build-the-hero");
    expect(historyRunHref("r1", "p1", "!!!")).toBe("/projects/p1/history/r1"); // empty slug → no tail
  });
});

describe("taskTitle / taskBody — the description-as-identifier fix", () => {
  it("the first line is the title (the launcher puts the item title there by construction)", () => {
    const task = "Add a --sort flag\n\nThe list command should accept --sort.\n\nAcceptance criteria: ...";
    expect(taskTitle(task)).toBe("Add a --sort flag");
    expect(taskBody(task)).toContain("The list command should accept --sort.");
    expect(taskBody(task)).toContain("Acceptance criteria");
  });
  it("single-line tasks keep everything as the title with an empty body", () => {
    expect(taskTitle("Fix the bug")).toBe("Fix the bug");
    expect(taskBody("Fix the bug")).toBe("");
    expect(taskTitle(undefined)).toBe("Run");
  });
});
