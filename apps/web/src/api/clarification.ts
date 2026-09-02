// The CLARIFICATION contract — the ask an item carries, and how an operator answers it.
// Split out of `client.ts` on 2026-08-08 following the `gate.ts` precedent: the size ratchet (#81)
// caught that file growing past its recorded 1070 lines while ADR-0091 added the `proposal_kind`
// discriminator here. Re-exported from `client.ts`, so every existing importer is unchanged.

/** The intake-clarification request stored on an item (ADR-0080 §1). The `clarification`
 *  field carries it only while OPEN; `clarification_record` carries the full retained
 *  exchange regardless of status (#63 ledger). */
export interface ItemClarification {
  /** The material acceptance claim Quincy could not bind an oracle to. */
  claim_text: string;
  why_unbindable: string;
  /** Up to 3 resolution proposals (validated non-empty server-side). */
  proposals: string[];
  /** What the proposals ARE (ADR-0091). `acceptance` = each is a complete replacement acceptance
   *  text, so one click rewrites the bar. `direction` = guidance for a human (the ESCALATE arm's
   *  "amend the criteria so tests/x.py can pass"), which the server refuses by index. **Absent on
   *  pre-ADR-0091 rows — treat missing as `direction`, never `acceptance`.** */
  proposal_kind?: "acceptance" | "direction";
  /** Which intake axis raised it (ADR-0089): checkability | decidability | reachability. */
  axis?: string;
  status: "open" | "resolved" | "dismissed" | "affirmed";
  asked_at: string;
  /** The operator's recorded answer (accepted/edited acceptance text); "" on dismissal. */
  resolution?: string;
  resolved_at?: string;
}

/** How the operator answers a clarification (ADR-0080, ADR-0091). Named once because the shape had
 *  drifted into four inline copies, and a field added to three of them is a hole at the fourth.
 *  `accepted_proposal_index` is honoured only for a `proposal_kind === "acceptance"` ask;
 *  `edited_text` always is; `disposition` says the bar stands and the code is wrong. */
export interface ClarificationResolveBody {
  accepted_proposal_index?: number;
  edited_text?: string;
  rejected?: boolean;
  disposition?: "bar_stands_retry";
}
