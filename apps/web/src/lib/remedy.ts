/* What the operator can DO about a park — the half #108 left out.
 *
 * #108 fixed the RECORDING of why a run stopped; the screen still showed a diagnosis with no next
 * step, which for a newcomer is the same dead end. `plain.ts` says what HAPPENED; this file says
 * what to do about it. Split out rather than appended there because that file is the copy deck for
 * run *state* and was two dozen lines from the god-file ceiling — and because these two answer
 * genuinely different questions.
 *
 * Total over `mosaera_policies.gate.GateReason`, guarded from PYTHON
 * (`packages/core/tests/test_gate_reason_coverage.py`) for the reason `plain.ts` records: a TS
 * enumeration of a Python vocabulary is a second origin by construction, and the TS-side test that
 * was supposed to catch exactly this listed the same stale tokens and passed. */

export interface Remedy {
  /** One sentence, imperative, addressed to the operator. */
  text: string;
  /** The GENERAL_KNOBS field that unblocks this, when one does. */
  knob?: string;
}

export const GATE_REMEDY: Record<string, Remedy> = {
  validation_failed: { text: "Read the failing output on the run, then send it back to revise." },
  validation_unavailable: {
    text:
      "Nothing here could be checked offline. Give the project a test command in its setup so a " +
      "run has something to prove itself against.",
  },
  validation_not_attempted: {
    text: "The run stopped before validation — the cause is under \u201cHow it ended\u201d, not here.",
  },
  tests_tampered: {
    text:
      "Review the diff. If the test genuinely had to change, put that in the item's acceptance " +
      "and re-run — never approve past this without reading it.",
  },
  content_destroyed: {
    text:
      "Review the diff. If the file really should go, say so in the item's acceptance so a " +
      "deletion is what was asked for.",
  },
  reviewer_requested_changes: {
    text: "Send it back to revise, or approve over the objection — the override is on record.",
  },
  reviewer_blocked: { text: "Read the reviewer's reasoning, then revise the item or end the run." },
  reviewer_conflict: { text: "The reviewers disagreed — read both verdicts and decide yourself." },
  reviewer_unknown: {
    text:
      "The verdict came back unreadable, which is usually the reviewer's model. Re-run, or pick a " +
      "stronger reviewer model in Settings \u2192 Models.",
  },
  security_findings: { text: "Read the findings and fix them, or approve over them on record." },
  security_unverified: { text: "The scan could not read this change — re-run to try again." },
  security_not_attempted: {
    text: "The run ended before the scan. Fix what stopped it, then re-run.",
  },
  security_stale: { text: "The code moved after the scan — re-run so the scan sees this version." },
  reviewer_stale: { text: "The code moved after the review — re-run so the review sees it." },
  oracle_unverified: {
    text:
      "Nothing independent could vouch for the work. Turn the Proctor on so it writes the " +
      "acceptance test, or give the project a test command in its setup.",
    knob: "tester_enabled",
  },
  critic_vetoed: { text: "Read the veto — it names what the delivered work did not support." },
  unsatisfied_claim: { text: "Open the claims list and see which promise went unchecked." },
  claim_behavioral_failed: {
    text: "The change did not do something the item asked for — send it back to revise.",
  },
  claim_structural_failed: {
    text: "The code is not shaped the way the item asked. Revise, or relax the item's wording.",
  },
  claim_integrity_failed: {
    text: "A promise not to touch the tests was broken — review the diff before anything else.",
  },
  impact_unassessed: {
    text: "Nothing checked who depended on the changed behaviour. Revise, or accept on record.",
  },
  removal_unproven: {
    text: "Nothing proved the removed thing is unused. Revise, or accept the risk on record.",
  },
  iteration_limit: {
    text: "The run used every revision it was allowed. Raise the revision limit, or re-scope the item.",
    knob: "max_iterations",
  },
};

/** Which term of the oracle refused, in remedies. `oracle_unverified` is one token over three very
 *  different situations, and the run already RECORDS which (`diagnosis.oracle_blocked_by`) — it
 *  was simply never rendered. A generic sentence here would send an operator to flip the Proctor
 *  when the Proctor was already on and the sabotage check is what said no. */
export const ORACLE_LEG_REMEDY: Record<string, Remedy> = {
  independence: GATE_REMEDY.oracle_unverified,
  mutation: {
    text:
      "The tests did not notice when we deliberately broke the code, so passing them proves " +
      "nothing. The tests need a real assertion about behaviour.",
  },
  structural: {
    text: "The delivered code does not have the shape the item asked for — send it back to revise.",
  },
};

/** The remedy for one reason, specialised by which oracle leg refused when we know it.
 *  `null` for a reason with no remedy on file — the caller renders nothing rather than a guess. */
export function gateRemedy(token: string, blockedBy: string[] = []): Remedy | null {
  if (token === "oracle_unverified") {
    for (const leg of blockedBy) {
      const specific = ORACLE_LEG_REMEDY[leg];
      if (specific) return specific;
    }
  }
  return GATE_REMEDY[token] ?? null;
}

