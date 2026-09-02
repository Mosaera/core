// The delivery/escalation GATE contract — the payload a human decides on, and everything it
// carries. Split out of `client.ts` on 2026-08-07: the hardened size ratchet (#81) caught that
// file growing past its recorded 1199 lines, and its grandfather note had said "split the request
// map from the type declarations" since the guard was extended to TS. This is the first slice.
//
// Re-exported from `client.ts`, so every existing importer is unchanged.

/** Structured evidence check computed by the delivery gate before anyone
 *  approves (mosaera_policies.gate). Approving over non-empty reasons is an
 *  explicit, recorded human override. */
export interface GateDecision {
  action: string;
  reasons: string[];
  tests_passed: boolean | null;
  reviewer_verdict: string;
  human_override?: boolean;
  /** An independent oracle vouched for correctness this run (ADR-0044). */
  oracle_verified?: boolean;
  /** What a green tests_passed was WORTH (ADR-0034): "suite" | "shallow" | "unknown"… */
  validation_strength?: string;
  /** Ids of acceptance claims whose bound oracle evaluated and FAILED (ADR-0079). */
  unsatisfied_claims?: string[];
  /** WHY the oracle vouched (#60) — "structural_claims:<ids>" or "no_vouch:<guards>". */
  oracle_vouched_by?: string;
  /** The priced-residual receipt (ADR-0071 amendment); "" when no residual was named. */
  oracle_residual?: string;
  /** Mutation-check tri-state: true = caught, false = a mutant survived, null = not measured. */
  tests_mutation_caught?: boolean | null;
}

/** One structured acceptance claim riding the gate payload (ADR-0079, serialized Claim). */
export interface Claim {
  id: string;
  text: string;
  provenance?: string;
  oracle_kind?: string;
  material?: boolean;
}

/** A claim's evaluated verdict at the gate (ADR-0079 Wave 2). */
export interface ClaimDisposition {
  claim_id: string;
  verdict: "satisfied" | "failed" | "unbound" | "unevaluable";
  /** What the verdict stands on (a test id, a structural predicate…). */
  oracle_ref?: string;
}

/** The held-out critic's judgement of the delivered outcome (#61, ADR-0065). */
export interface OutcomeVerdict {
  vetoed?: boolean;
  reason?: string;
  rows?: { claim?: string; verdict?: string; note?: string }[];
}

/** One durable claim-ledger row (run_claims, ADR-0079) as served by run_detail. */
export interface RunClaimRow {
  claim_id: string;
  text: string;
  verdict: string;
  oracle_ref: string;
  material?: boolean;
  provenance?: string;
  oracle_kind?: string;
}

/** One answer the operator may give, and what it will cause. `id` is the `option_id` the
 *  API validates against — sending one this gate did not offer is a 400, never a silent
 *  approval (ADR-0082 §5). */
export interface GateOutcome {
  id: string;
  label: string;
  consequence: string;
  /** "approve" | "send_back" | "end_run" — what the ENGINE will do, not what the button says. */
  effect: string;
  recommended?: boolean;
  /** True when this answer overrides blocking evidence; rendered as an override, never as the
   *  recommendation. */
  override?: boolean;
}

export interface GatePayload {
  action?: string;
  summary?: string;
  plan?: string;
  diff?: string;
  path?: string;
  content?: string;
  test_output?: string;
  findings?: string;
  review?: string;
  tests_passed?: boolean | null;
  iteration?: number;
  /** Revision budget: "send back to revise" loops until this cap. */
  max_iterations?: number;
  gate_decision?: GateDecision;
  /** Budget-park (action === "budget"): the crossed spend ceiling. */
  breach?: string; // usd | tokens | tool_calls
  spent?: number;
  cap?: number;
  raised_before?: number; // times this budget was already raised (honest budget prompt)
  elapsed_s?: number;
  calls?: number;
  /** Honest live-gate signals (emitted by graph.py gate_node). */
  stalled?: boolean; // the run stopped converging before finishing (thrash)
  stall_reason?: string; // why it couldn't complete (shown before you decide)
  /** An HONEST early conclusion (#56/#81): the run diagnosed that it could not converge and
   *  stopped BELOW the iteration cap, rather than thrashing into one. Distinct from `stalled`
   *  and — until this was rendered — invisible to the human deciding at the gate. */
  give_up_reason?: string;
  /** ESCALATION GATE (ADR-0087, #65): the delivered acceptance tests blocking this run that the
   *  coder is forbidden to edit, so re-planning cannot help. Present only when the run parked on
   *  an oracle conflict and the amendment knob is on. Authorizing one lets the PROCTOR — never the
   *  coder — rewrite it once; without this the run could only be concluded. */
  amendable?: {
    paths: string[];
    tests: string[];
    criterion?: string;
    /** Who owns each blocking bar, from the contract registry (ADR-0087 §1-§4). Absent for a
     *  path with no registered contract — that means the owner is genuinely UNKNOWN, and the
     *  UI must show nothing rather than attribute the bar to whoever last touched the file. */
    contracts?: Record<
      string,
      { owner_item_id?: number | null; version?: number; amended_before?: boolean }
    >;
  };
  /** Why the amendment is NOT offered, when something specific suppressed it (F65). An offer that
   *  silently vanishes is indistinguishable from a control that was never built. */
  amendable_withheld?: string;
  /** Why an amendment the operator DID authorize was refused, per path (F71). Granting an
   *  authorization and getting nothing back, with no reason, is the same defect one step later. */
  amendment_refusals?: Record<string, string>;
  /** What the lint/type stage actually did: clean | findings | unavailable |
   *  not_applicable | disabled (#80). Informational — nothing gates on it.
   *  "unavailable" means a tool produced no verdict, which is NOT a clean bill of
   *  health, and "not_applicable" means there was no python to check. Both used to be
   *  indistinguishable from "linted clean". */
  hygiene_status?: string;
  /** Which tools produced no verdict, when hygiene_status is "unavailable". */
  hygiene_unavailable?: string[];
  /** What each answer will ACTUALLY do (ADR-0082 §1, F61), computed by the engine from run
   *  state — never authored by a model. An answer that cannot function is NOT in this list:
   *  at the iteration cap there is no `send_back`, because denying there ends the run and
   *  discards the notes. Absent on gates that do not declare outcomes yet (write/edit gates),
   *  where the panel falls back to its legacy buttons. */
  outcomes?: GateOutcome[];
  validation_unverified?: boolean; // delivered without a passing validation run
  /** Per-claim evidence at the live gate (ADR-0079 Wave 2). */
  claims?: Claim[];
  claim_dispositions?: ClaimDisposition[];
  /** WHY the oracle vouched (#60) — always set when the gate ran. */
  oracle_vouched_by?: string;
  /** The priced-residual receipt (ADR-0071 amendment); "" when none was named. */
  oracle_residual?: string;
  /** The held-out critic's verdict (#61) — reason + rows behind a veto. */
  outcome_verdict?: OutcomeVerdict | null;
}
