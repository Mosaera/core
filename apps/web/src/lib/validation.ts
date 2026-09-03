/* !! Every run-state label MUST derive from `runOutcome` here — never from `tests_passed`
   directly. That flag is TRI-STATE and a truthy check renders null ("no test phase was ever
   reached") as a red failure. Two components did exactly that until 2026-08-06. The gate's
   presentation is part of the trust boundary: issue #69.

   The single list-level validation vocabulary. Overview, Changes, and the
   merge-readiness card all derive their run labels from `runOutcome` — never
   from `tests_passed` directly — so "validation unavailable" and a timed-out
   "errored" run are never fabricated into "tests failed". Stays consistent
   with the fetched-detail verdict (lib/runs.ts `validationVerdict`) and the
   card badge (lib/changes.ts `runCardBadge`). Unit-tested in
   validation-lib.test.ts. */

import type { HistoryRun } from "../api/client";

export type RunOutcome =
  | "running"
  | "cancelled"
  | "errored"
  | "incomplete"
  | "not-approved"
  | "validation-failed"
  | "validation-unavailable"
  | "validation-unverified"
  | "passed";

/** Honest outcome from `HistoryRun` fields alone (the coarser granularity the
 *  dashboard/cards have — no decisions/test_results). ERROR and CANCELLED are
 *  run-status facts, kept distinct from validation: a timeout is not a test
 *  failure. `unavailable` needs a human but is not a failure. */
export function runOutcome(run: HistoryRun): RunOutcome {
  if (run.status === "RUNNING") return "running";
  if (run.status === "CANCELLED") return "cancelled";
  if (run.status === "ERROR") return "errored";
  // A run that ended WITHOUT delivering (ADR-0006) is a park, not a failure. It had no branch
  // here and fell through to "validation-failed" — so run 20260806-205850-033b61, which the
  // intake gate refused at 0 tokens for an under-specified item, was reported as failed
  // validation despite never having run a test.
  if (run.status === "INCOMPLETE") return "incomplete";
  if (run.status === "NOT APPROVED") return "not-approved";
  if (run.validation_status === "unavailable") return "validation-unavailable";
  if (run.validation_status === "unverified") return "validation-unverified";
  // `tests_passed` is TRI-STATE: null means no test phase was ever reached, which is not a
  // failure. Only an explicit false is.
  if (run.validation_status == null && run.tests_passed == null) return "validation-unavailable";
  const passed =
    run.validation_status === "pass" ||
    (run.validation_status == null && run.tests_passed === true); // legacy pre-planner rows
  return passed ? "passed" : "validation-failed";
}

/** Why an INCOMPLETE run stopped, from the structured diagnosis (migration 0022, populated for
 *  abnormal exits since F50) falling back to the 80-char reason column. Null when neither exists —
 *  render the absence honestly rather than inventing a cause. */
export function parkReason(run: HistoryRun): string | null {
  const cause = run.diagnosis?.park_cause?.trim();
  if (cause) return cause.replace(/_/g, " ");
  const reason = (run.termination_reason ?? "").trim();
  if (!reason) return null;
  return reason.split(":")[0].replace(/_/g, " ");
}

export interface OutcomeMeta {
  label: string;
  severity: "green" | "amber" | "red";
  /** true = needs a human's eyes (drives Overview attention + activity tone). */
  attention: boolean;
}

export const OUTCOME_META: Record<RunOutcome, OutcomeMeta> = {
  running: { label: "Running", severity: "green", attention: false },
  passed: { label: "Validation passed", severity: "green", attention: false },
  cancelled: { label: "Cancelled", severity: "amber", attention: false },
  incomplete: { label: "Parked", severity: "amber", attention: true },
  "validation-unavailable": { label: "Validation unavailable", severity: "amber", attention: true },
  "validation-unverified": { label: "Delivered unverified", severity: "amber", attention: true },
  "not-approved": { label: "Not approved", severity: "amber", attention: true },
  "validation-failed": { label: "Validation failed", severity: "red", attention: true },
  errored: { label: "Errored", severity: "red", attention: true },
};
