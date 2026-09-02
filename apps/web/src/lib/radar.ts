/* The proof radar's data layer — pure, discrete, and honest about what each source can know.
 *
 * DISCRETE RINGS ONLY: an axis is proven, weak, or not-checked. A radar showing "security: 0.7"
 * would manufacture precision the gate refuses to manufacture, so there are no decimals anywhere.
 * `breach` is the puncture channel: a failed check renders as a destructive marker and feeds the
 * verdict headline — "failed" must never masquerade as "not-checked".
 *
 * Three sources with three honesty levels:
 *   - the OPEN GATE (GatePayload): everything live — six axes;
 *   - the DURABLE RECEIPT (run detail): everything recorded — six axes;
 *   - the LIST ROW (HistoryRun + diagnosis): four axes. Review and Proof-depth are receipt-only,
 *     so trend surfaces render FOUR spokes and say so — a six-spoke ghost with two permanently
 *     dashed spokes is manufactured symmetry.
 * An axis a given source cannot answer is OMITTED (`value: null`) and the polygon SKIPS that
 * vertex — never ring-0, which would read as a real "not-checked". */

import type { GatePayload, HistoryRun } from "../api/client";
import type { LedgerClaim } from "./ledger";
import type { ParsedReceipt } from "./runs";
import { runOutcome } from "./validation";

export type Ring = "proven" | "weak" | "not-checked";

export interface AxisValue {
  axis: AxisId;
  label: string;
  /** null = this source cannot answer — the spoke renders dashed, the polygon skips the vertex. */
  value: Ring | null;
  /** The puncture channel: renders destructive and feeds the verdict headline. */
  breach: boolean;
  /** One plain sentence per axis — the facts must exist as text, not only as geometry. */
  note: string;
}

export type AxisId = "checks" | "claims" | "review" | "security" | "depth" | "integrity";

export const AXIS_LABEL: Record<AxisId, string> = {
  checks: "checks",
  claims: "claims",
  review: "review",
  security: "security",
  depth: "proof depth",
  integrity: "integrity",
};

/** The four axes every durable list row can answer — the trend/overview spoke set. */
export const DURABLE_AXES: AxisId[] = ["checks", "claims", "security", "integrity"];
export const ALL_AXES: AxisId[] = ["checks", "claims", "review", "security", "depth", "integrity"];

const ax = (axis: AxisId, value: Ring | null, breach: boolean, note: string): AxisValue => ({
  axis,
  label: AXIS_LABEL[axis],
  value,
  breach,
  note,
});

function checksAxis(testsPassed: boolean | null | undefined, unverified: boolean): AxisValue {
  /* Semantics are strictly "the checks that ran, passed" — what a pass was WORTH is the depth
   * axis, which is honestly receipt-only. tests_passed is TRI-STATE: null is "never reached",
   * not a failure (lib/validation.ts:1 records the regression from treating it truthily). */
  if (testsPassed === false) return ax("checks", "not-checked", true, "the automated checks failed");
  if (testsPassed === true && unverified)
    return ax("checks", "weak", false, "delivered without a passing validation run");
  if (testsPassed === true) return ax("checks", "proven", false, "the automated checks passed");
  return ax("checks", "not-checked", false, "no validation ran");
}

function claimsAxis(claims: LedgerClaim[], failedTokens: boolean): AxisValue {
  const material = claims.filter((c) => c.material);
  const failed = material.some((c) => c.verdict === "failed") || failedTokens;
  if (failed) return ax("claims", "not-checked", true, "an acceptance claim failed its check");
  if (material.length === 0) return ax("claims", "not-checked", false, "no acceptance claims bound");
  if (material.every((c) => c.verdict === "satisfied"))
    return ax("claims", "proven", false, "every acceptance claim verified");
  return ax("claims", "weak", false, "some claims have no way to be checked");
}

function reviewAxis(verdict: string | undefined, reasons: string[]): AxisValue {
  const stale = reasons.includes("reviewer_stale");
  if (stale)
    return ax("review", "not-checked", true, "the code changed after the reviewer approved it");
  if (verdict === "APPROVE") return ax("review", "proven", false, "independent review approved");
  if (verdict === "REQUEST_CHANGES" || verdict === "BLOCK" || verdict === "CONFLICT")
    return ax("review", "not-checked", true, "the independent reviewer objected");
  return ax("review", "not-checked", false, "no reviewer verdict");
}

function securityAxis(reasons: string[], unavailableCause?: string | null): AxisValue {
  if (reasons.includes("security_findings"))
    return ax("security", "not-checked", true, "the security scan found something");
  if (reasons.includes("security_stale"))
    return ax("security", "not-checked", true, "the code changed after the security scan");
  if (reasons.includes("security_not_attempted") || reasons.includes("security_unverified"))
    return ax("security", "not-checked", true, "this version was never scanned");
  if (unavailableCause)
    return ax("security", "not-checked", false, "the scanner was unavailable");
  return ax("security", "proven", false, "security scan clean for this code");
}

function depthAxis(strength: string | undefined, mutation: boolean | null | undefined): AxisValue {
  if (strength === "suite" && mutation === true)
    return ax("depth", "proven", false, "a real suite ran and caught a sabotage check");
  if (strength === "suite" && mutation === false)
    /* A survived mutant is RECORDED, amber, not a breach: it blocks nothing and is honestly on
     * the receipt as a priced residual — the opposite of hidden. */
    return ax("depth", "weak", false, "a real suite ran; one sabotage check survived");
  if (strength === "suite") return ax("depth", "weak", false, "a real suite ran; depth unmeasured");
  if (strength === "shallow")
    return ax("depth", "weak", false, "only a syntax-level check ran");
  return ax("depth", "not-checked", false, "proof depth unknown");
}

function integrityAxis(tampered: boolean, reasons: string[], sealed: boolean | null): AxisValue {
  const tamper =
    tampered ||
    reasons.includes("tests_tampered") ||
    reasons.includes("content_destroyed") ||
    reasons.includes("claim_integrity_failed");
  if (tamper) return ax("integrity", "not-checked", true, "a protected test or file was modified");
  if (sealed === false) return ax("integrity", "weak", false, "no sealed receipt on record");
  // sealed === null means this source cannot see the seal — say only what it knows.
  return ax(
    "integrity",
    "proven",
    false,
    sealed === true ? "no tampering; record sealed" : "no tampering detected",
  );
}

const CLAIM_FAIL_TOKENS = [
  "unsatisfied_claim",
  "claim_behavioral_failed",
  "claim_structural_failed",
  "claim_integrity_failed",
];

/** The open gate — six axes, everything live. */
export function radarFromGate(gate: GatePayload, claims: LedgerClaim[]): AxisValue[] {
  const gd = gate.gate_decision;
  const reasons = gd?.reasons ?? [];
  return [
    checksAxis(gd?.tests_passed, gate.validation_unverified === true),
    claimsAxis(claims, reasons.some((r) => CLAIM_FAIL_TOKENS.includes(r))),
    reviewAxis(gd?.reviewer_verdict, reasons),
    securityAxis(reasons),
    depthAxis(gd?.validation_strength, gd?.tests_mutation_caught),
    integrityAxis(false, reasons, null),
  ];
}

/** A settled run's durable receipt — six axes. */
export function radarFromReceipt(
  receipt: ParsedReceipt,
  claims: LedgerClaim[],
  opts?: { testsModified?: boolean; sealed?: boolean },
): AxisValue[] {
  const reasons = receipt.reasons;
  return [
    checksAxis(receipt.testsPassed, false),
    claimsAxis(claims, reasons.some((r) => CLAIM_FAIL_TOKENS.includes(r))),
    reviewAxis(receipt.reviewerVerdict, reasons),
    securityAxis(reasons),
    depthAxis(receipt.validationStrength, receipt.testsMutationCaught),
    integrityAxis(opts?.testsModified === true, reasons, opts?.sealed ?? null),
  ];
}

/** A durable LIST ROW — the four axes it can honestly answer; review and depth are omitted. */
export function radarFromRow(run: HistoryRun): AxisValue[] {
  const d = run.diagnosis;
  const reasons = d?.gate_reasons ?? [];
  const outcome = runOutcome(run);
  const checks =
    outcome === "passed"
      ? ax("checks", "proven", false, "the automated checks passed")
      : outcome === "validation-failed"
        ? ax("checks", "not-checked", true, "the automated checks failed")
        : outcome === "validation-unverified"
          ? ax("checks", "weak", false, "delivered without a passing validation run")
          : ax("checks", "not-checked", false, "no validation ran");
  const unsat = d?.unsatisfied_claims ?? [];
  const claims =
    unsat.length > 0 || reasons.some((r) => CLAIM_FAIL_TOKENS.includes(r))
      ? ax("claims", "not-checked", true, "an acceptance claim failed its check")
      : d?.outcome === "clean_deliver"
        ? ax("claims", "proven", false, "delivered with claims clean")
        : ax("claims", null, false, "per-claim record lives on the run page");
  return [
    checks,
    claims,
    ax("review", null, false, "recorded per-run only"),
    securityAxis(reasons, d?.security_unavailable_cause),
    ax("depth", null, false, "recorded per-run only"),
    integrityAxis(d?.tests_modified === true, reasons, run.receipt_id ? true : false),
  ];
}

/** The last-`n` SETTLED runs' shapes, newest first — literally their discrete shapes, never an
 *  average. The ghost answers "how did recent runs prove out", not a manufactured score. */
export function radarTrend(runs: HistoryRun[], n = 5): AxisValue[][] {
  return runs
    .filter((r) => r.status !== "RUNNING" && r.status !== "CANCELLED")
    .slice(0, n)
    .map((r) => radarFromRow(r));
}

/** Ghosts for a RUN page: the SAME ITEM's prior settled attempts — "is this attempt better than
 *  the last one", never a global blur (a ghost of unrelated items answers nothing). */
export function priorAttemptShapes(
  runs: HistoryRun[],
  current: { id: string; item_id: number | null },
  n = 5,
): AxisValue[][] {
  if (current.item_id == null) return [];
  const priors = runs.filter((r) => r.item_id === current.item_id && r.id !== current.id);
  return radarTrend(priors, n);
}
