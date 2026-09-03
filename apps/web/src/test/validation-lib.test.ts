import { describe, expect, it } from "vitest";

import type { HistoryRun } from "../api/client";
import { OUTCOME_META, parkReason, type RunOutcome, runOutcome } from "../lib/validation";

function run(over: Partial<HistoryRun> = {}): HistoryRun {
  return {
    id: "r1", task: "t", status: "APPROVED", tests_passed: true,
    iterations: 1, commit_sha: "abc", source: "s", branch: "b",
    project_id: "p1", item_id: null, validation_status: null, created_at: null, ...over,
  };
}

describe("runOutcome", () => {
  it("run-status facts win over validation and are kept distinct", () => {
    expect(runOutcome(run({ status: "RUNNING" }))).toBe("running");
    expect(runOutcome(run({ status: "CANCELLED" }))).toBe("cancelled");
    expect(runOutcome(run({ status: "ERROR" }))).toBe("errored"); // timeout, NOT a test failure
    expect(runOutcome(run({ status: "NOT APPROVED" }))).toBe("not-approved");
  });

  it("validation tri-state for approved runs", () => {
    expect(runOutcome(run({ validation_status: "pass" }))).toBe("passed");
    expect(runOutcome(run({ validation_status: "failed", tests_passed: false }))).toBe("validation-failed");
    // The lie the patch kills: unavailable is its own outcome, never a failure.
    expect(runOutcome(run({ validation_status: "unavailable", tests_passed: false }))).toBe(
      "validation-unavailable",
    );
    // Deliver-with-caveat (P3): unverified is its own honest outcome, not "passed".
    expect(runOutcome(run({ validation_status: "unverified", tests_passed: true }))).toBe(
      "validation-unverified",
    );
  });

  it("legacy pre-planner rows (null validation_status) fall back to tests_passed", () => {
    expect(runOutcome(run({ validation_status: null, tests_passed: true }))).toBe("passed");
    expect(runOutcome(run({ validation_status: null, tests_passed: false }))).toBe("validation-failed");
  });
});

describe("OUTCOME_META", () => {
  it("unavailable is amber+attention but never red (not a failure)", () => {
    expect(OUTCOME_META["validation-unavailable"]).toMatchObject({ severity: "amber", attention: true });
  });
  it("passed/running/cancelled don't demand attention; failures/errors do", () => {
    expect(OUTCOME_META.passed.attention).toBe(false);
    expect(OUTCOME_META.running.attention).toBe(false);
    expect(OUTCOME_META.cancelled.attention).toBe(false);
    expect(OUTCOME_META["validation-failed"]).toMatchObject({ severity: "red", attention: true });
    expect(OUTCOME_META.errored).toMatchObject({ severity: "red", attention: true });
  });
  it("covers every outcome", () => {
    const outcomes: RunOutcome[] = [
      "running", "cancelled", "errored", "incomplete", "not-approved",
      "validation-failed", "validation-unavailable", "validation-unverified", "passed",
    ];
    for (const o of outcomes) expect(OUTCOME_META[o]).toBeDefined();
  });

  it("a park is amber and needs eyes — never red", () => {
    expect(OUTCOME_META.incomplete).toMatchObject({ severity: "amber", attention: true });
  });
});

/* Regression fixtures taken from real rows on mosaera.rengifo.me, 2026-08-06. Each of these
   rendered a red "TESTS FAIL" in the backlog for a run that never reached a test phase. */
describe("a run that never ran a test is not a test failure", () => {
  it("the intake refusal is a PARK, not a validation failure", () => {
    // 20260806-205850-033b61 — the gate refused an under-specified item having spent 0 tokens.
    const refused = run({
      status: "INCOMPLETE",
      tests_passed: null,
      termination_reason: "under_specified: no material acceptance claim is checkable as written",
    });
    expect(runOutcome(refused)).toBe("incomplete");
    expect(OUTCOME_META[runOutcome(refused)].severity).not.toBe("red");
  });

  it("a run cancelled mid-design is cancelled, not failed", () => {
    // 20260806-210846-ce9246 — cancelled in `design`; no test phase existed to fail.
    expect(runOutcome(run({ status: "CANCELLED", tests_passed: null }))).toBe("cancelled");
  });

  it("null tests_passed with no validation_status is unavailable, not failed", () => {
    // The tri-state hole: `tests_passed ? "pass" : "fail"` read null as failure.
    expect(runOutcome(run({ validation_status: null, tests_passed: null }))).toBe(
      "validation-unavailable",
    );
  });

  it("an explicit false is still a failure — the fix must not swallow real ones", () => {
    expect(runOutcome(run({ validation_status: null, tests_passed: false }))).toBe(
      "validation-failed",
    );
  });
});

describe("parkReason", () => {
  it("prefers the structured diagnosis over the truncated reason column", () => {
    const r = run({
      status: "INCOMPLETE",
      termination_reason: "under_specified: no material acceptance claim is c",
      diagnosis: { outcome: "honest_park", park_cause: "under_specified" } as never,
    });
    expect(parkReason(r)).toBe("under specified");
  });

  it("falls back to the reason column when no diagnosis was recorded", () => {
    expect(parkReason(run({ status: "INCOMPLETE", termination_reason: "budget_exhausted: 750k" })))
      .toBe("budget exhausted");
  });

  it("returns null rather than inventing a cause", () => {
    expect(parkReason(run({ status: "INCOMPLETE" }))).toBeNull();
  });
});
