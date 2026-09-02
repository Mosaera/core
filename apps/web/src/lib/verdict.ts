/* THE one verdict derivation — what the headline of a trust surface says, and why.
 *
 * Three sibling headline derivations used to coexist (GatePanel's ad-hoc validation label,
 * VerdictBand's WHY_HEADING, TerminatedHero reading TERMINATED directly), which is the firehose's
 * root cause one level up: every surface said something slightly different about the same run.
 * `deriveHeroVariant` stays the layer ABOVE this one — it picks which surface the page is; this
 * picks the words.
 *
 * Composed from the record, never asserted — and never a model call. The dominant reason comes
 * from the gate's deterministic tokens (total plain-English deck in `GATE_REASON`); the
 * model-authored stop channels are the FALLBACK when no gate reason exists, never the headline
 * over one.
 */

import type { GatePayload, RunDiagnosis } from "../api/client";
import type { LedgerClaim } from "./ledger";
import { GATE_REASON, TERMINATED, stopReason, type Tone } from "./plain";

/* MIRROR of `mosaera_policies.gate.REASON_CLASS` — a second origin, guarded two ways:
 * (1) keys ≡ GATE_REASON keys (verdict-lib.test.ts), so a new token cannot land unclassified;
 * (2) `packages/core/tests/test_gate_reason_classification.py` AST-parses this map and compares
 *     every class against the Python source of truth. A drifted class here makes the HEADLINE
 *     wrong, which on a gate is an honesty bug of the first order — hence both locks. */
export const VERDICT_REASON_CLASS: Record<string, ReasonClass> = {
  validation_failed: "shortfall",
  validation_unavailable: "objection",
  validation_not_attempted: "not_run",
  reviewer_requested_changes: "objection",
  reviewer_blocked: "objection",
  reviewer_unknown: "incidental",
  reviewer_conflict: "objection",
  security_findings: "objection",
  security_unverified: "objection",
  security_not_attempted: "not_run",
  security_stale: "not_run",
  reviewer_stale: "not_run",
  tests_tampered: "tamper",
  content_destroyed: "tamper",
  oracle_unverified: "shortfall",
  critic_vetoed: "objection",
  unsatisfied_claim: "objection",
  claim_behavioral_failed: "shortfall",
  claim_structural_failed: "objection",
  removal_unproven: "objection",
  impact_unassessed: "objection",
  claim_integrity_failed: "tamper",
  iteration_limit: "incidental",
};

export type ReasonClass = "objection" | "shortfall" | "incidental" | "tamper" | "not_run";

/* Severity ladder for picking the DOMINANT reason. Tamper first (an integrity violation is never
 * out-ranked), then not_run (the check did not measure THIS code — the ADR-0108 class), then a
 * real objection, then a missed bar, then bookkeeping. Within a class, first in the server's
 * emission order wins — that order is documented load-bearing in gate.py. */
const LADDER: ReasonClass[] = ["tamper", "not_run", "objection", "shortfall", "incidental"];

export type VerdictState = "proven" | "delivered-unproven" | "not-proven";

export interface Verdict {
  state: VerdictState;
  tone: Tone;
  headline: string;
  /** ONE dominant reason (deterministic token + its plain sentence), or null when none exists. */
  reason: { token: string; text: string } | null;
  /** Every OTHER gate reason — ADR-0082 §1 requires these in the summary layer too. */
  secondary: { token: string; text: string }[];
}

export const VERDICT_HEADLINE: Record<VerdictState, string> = {
  proven: "Proven",
  /* NOT "Unverified" — that word already means two other things here (the validation-unverified
   * run outcome, and per-claim unverified counts). A third meaning on a trust surface collides. */
  "delivered-unproven": "Delivered — not fully proven",
  "not-proven": "Not proven",
};

function classOf(token: string): ReasonClass {
  return VERDICT_REASON_CLASS[token] ?? "objection"; // unknown token: treat as a real problem
}

export function dominantReason(reasons: string[]): string | null {
  for (const cls of LADDER) {
    const hit = reasons.find((r) => classOf(r) === cls);
    if (hit) return hit;
  }
  return null;
}

export interface VerdictInput {
  delivered: boolean;
  /** Open-gate surface: prospective wording, `not-proven` while reasons stand. */
  atGate: boolean;
  claims: LedgerClaim[];
  reasons: string[];
  humanOverride: boolean;
  testsModified?: boolean;
  validationUnverified?: boolean;
  validationStrength?: string;
  diagnosis?: RunDiagnosis | null;
  status?: string;
}

export function deriveVerdict(input: VerdictInput): Verdict {
  const reasons = input.reasons ?? [];
  const tampered = input.testsModified === true || reasons.some((r) => classOf(r) === "tamper");
  const notRun = reasons.some((r) => classOf(r) === "not_run");
  const material = input.claims.filter((c) => c.material);
  const allSatisfied = material.length > 0 && material.every((c) => c.verdict === "satisfied");

  const token = dominantReason(reasons);
  const reason = token ? { token, text: GATE_REASON[token] ?? token.replace(/_/g, " ") } : null;
  const secondary = reasons
    .filter((r) => r !== token)
    .map((r) => ({ token: r, text: GATE_REASON[r] ?? r.replace(/_/g, " ") }));

  /* PUNCTURE — bad news reaches the headline, always. Tamper forbids `proven` outright and takes
   * the headline even under a human override; any not_run reason forbids `proven` (the check ran,
   * but not on this code — the generalized `staleScan` rule). This is the UI half of the invariant
   * three red-team rounds enforced in the backend: stale evidence must never vouch. */
  if (input.delivered) {
    const unproven =
      tampered ||
      notRun ||
      !allSatisfied ||
      input.validationUnverified === true ||
      input.humanOverride ||
      (input.validationStrength !== undefined && input.validationStrength !== "suite");
    if (!unproven) {
      return { state: "proven", tone: "success", headline: VERDICT_HEADLINE.proven, reason, secondary };
    }
    return {
      state: "delivered-unproven",
      tone: tampered ? "destructive" : "amber",
      headline: VERDICT_HEADLINE["delivered-unproven"],
      reason,
      secondary,
    };
  }

  /* Nothing delivered (open gate, park, decline, crash, cancel). When the gate produced no
   * reasons, fall back to the stop channels (model-authored prose — honest as a BODY, never as
   * the headline over a deterministic token), then the terminal-status sentence. */
  let fallback = reason;
  if (!fallback) {
    const stop = stopReason(input.diagnosis ?? null);
    if (stop) fallback = { token: "", text: stop.text };
    else if (input.status && TERMINATED[input.status]) {
      fallback = { token: "", text: TERMINATED[input.status] };
    }
  }
  return {
    state: "not-proven",
    tone: tampered ? "destructive" : input.atGate ? "amber" : "muted",
    headline: VERDICT_HEADLINE["not-proven"],
    reason: fallback,
    secondary,
  };
}

/** Live-gate claims joined to their dispositions, in the ledger's shape — so the gate and the
 *  durable record run through the SAME verdict/radar derivations rather than a sibling one. */
export function claimsFromGate(gate: GatePayload): LedgerClaim[] {
  const dispositions = new Map(
    (gate.claim_dispositions ?? []).map((d) => [d.claim_id, d] as const),
  );
  return (gate.claims ?? []).map((c) => ({
    id: c.id,
    text: c.text,
    provenance: c.provenance ?? "",
    oracleKind: c.oracle_kind ?? "",
    material: c.material !== false,
    verdict: dispositions.get(c.id)?.verdict ?? "",
    oracleRef: dispositions.get(c.id)?.oracle_ref ?? "",
  }));
}

/** The open gate: prospective — "what would shipping now stand on". */
export function verdictFromGate(gate: GatePayload, claims: LedgerClaim[]): Verdict {
  const gd = gate.gate_decision;
  return deriveVerdict({
    delivered: false,
    atGate: true,
    claims,
    reasons: gd?.reasons ?? [],
    humanOverride: gd?.human_override === true,
    validationUnverified: gate.validation_unverified === true,
    validationStrength: gd?.validation_strength,
  });
}

/** A settled run, from the durable record (receipt preferred, diagnosis fallback). */
export function verdictFromRecord(input: {
  delivered: boolean;
  claims: LedgerClaim[];
  reasons: string[];
  humanOverride: boolean;
  validationStrength?: string;
  diagnosis?: RunDiagnosis | null;
  status?: string;
}): Verdict {
  return deriveVerdict({
    atGate: false,
    testsModified: input.diagnosis?.tests_modified === true,
    ...input,
  });
}
