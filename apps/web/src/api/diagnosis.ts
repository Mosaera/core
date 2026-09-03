/* The run-diagnosis mirror, split out of client.ts (ADR-0113 — that file is at its grandfathered
   line ratchet; `api/delivery.ts` set the precedent). Re-exported from client.ts, so call sites
   keep importing `RunDiagnosis` from there unchanged.

   This is the structured record of HOW a run ended (#75, migration 0022) — the same outcome bucket
   and park cause the benchmark computes, so a live failure and a bench failure are comparable. */

/** How a run ended, structured (#75, migration 0022) — the SAME outcome bucket and park cause the
 *  benchmark computes, so a live failure and a bench failure are directly comparable.
 *  Null/absent = a pre-0022 row, a run still in flight, or a terminal path that never reached it.
 *  Render null honestly; never infer it from `status` or `termination_reason`. */
export interface RunDiagnosis {
  /** clean_deliver | honest_park | thrash_park | false_ship | crash. A LIVE run never reports
   *  false_ship: it has no hidden grader, so it cannot know a delivery was wrong. */
  outcome?: string;
  /** give_up | plan_unworkable | stalled:<kind> | iteration_limit | rode_to_cap | parked | "" */
  park_cause?: string;
  gate_reasons?: string[];
  /** Why the oracle vouched, or which guard said no (#60). */
  vouch?: string;
  /** WHICH term of the oracle AND refused: independence | mutation | structural. The API has
   *  recorded this on every run since #60 and the SPA never declared it, so an `oracle_unverified`
   *  park rendered one generic sentence over three situations with different remedies (#121). */
  oracle_blocked_by?: string[];
  unsatisfied_claims?: string[];
  iteration?: number;
  max_iterations?: number | null;
  stalled?: boolean;
  tests_modified?: boolean;
  /** Why the scanner produced no verdict (run_diagnosis.py writes it; typed late — the API
   *  always sent it, the mirror just never declared it). */
  security_unavailable_cause?: string | null;
  coder_escalated?: boolean;
  /** The out-of-band stop channels. `blocked_reason`/`escalate_reason` are here because a park on
   *  2026-08-05 was declined by Layer 2 for a reason nothing recorded, and these were the only
   *  candidates left — the run's final state was gone, so the cause is unrecoverable. */
  stall_reason?: string;
  give_up_reason?: string;
  plan_unworkable_reason?: string;
  blocked_reason?: string;
  escalate_reason?: string;
}
