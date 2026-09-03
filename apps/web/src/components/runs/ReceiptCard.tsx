import { Badge } from "@/components/ui/badge";
import { AmberCallout } from "@/components/ui/AmberCallout";
import { cn } from "@/lib/utils";

import type { GatePayload, OutcomeVerdict, RunDetail } from "../../api/client";
import {
  actionPlain,
  VALIDATION_STRENGTH,
  claimVerdict,
  CRITIC_VERDICT,
  gateReason,
  humanizeVouch,
  mutationPlain,
  normalizeCriticVerdict,
  reviewerVerdict,
  SENTENCES,
} from "../../lib/plain";

// Re-exported so callers (and this file's own tests) keep one import site for the receipt's
// vocabulary — the translation itself lives in lib/plain.ts, shared with the run diagnosis card.
export { humanizeVouch };
import { parseCriticVerdict, parseReceipt } from "../../lib/runs";
import { ConsoleLabel, EmptyNote } from "../overview/bits";

/* One renderer, two data sources, three mounts (the live gate, the run evidence
   tab, the durable history page). The receipt is the ADR-0071 priced residual +
   the ADR-0079 claim ledger + the gate verdict — everything a human's approval
   put on record. */

export interface ReceiptClaimRow {
  id: string;
  text: string;
  verdict: string;
  oracleRef: string;
}

export interface ReceiptData {
  action: string;
  reasons: string[];
  reviewerVerdict: string;
  testsPassed: boolean | null;
  oracleVerified: boolean | null; // null = the record predates the field
  validationStrength: string;
  unsatisfiedClaims: string[];
  humanOverride: boolean;
  oracleVouchedBy: string;
  oracleResidual: string;
  testsMutationCaught: boolean | null;
  claims: ReceiptClaimRow[];
  critic?: OutcomeVerdict | null;
}

/** Receipt from a LIVE gate interrupt payload (the run is parked right now). */
export function receiptFromGate(gate: GatePayload | undefined): ReceiptData | undefined {
  const gd = gate?.gate_decision;
  if (!gate || !gd) return undefined;
  const verdicts = new Map(
    (gate.claim_dispositions ?? []).map((d) => [d.claim_id, d] as const),
  );
  return {
    action: gd.action,
    reasons: gd.reasons,
    reviewerVerdict: gd.reviewer_verdict,
    testsPassed: gd.tests_passed,
    oracleVerified: typeof gd.oracle_verified === "boolean" ? gd.oracle_verified : null,
    validationStrength: gd.validation_strength ?? "unknown",
    unsatisfiedClaims: gd.unsatisfied_claims ?? [],
    humanOverride: gd.human_override === true,
    oracleVouchedBy: gate.oracle_vouched_by ?? gd.oracle_vouched_by ?? "",
    oracleResidual: gate.oracle_residual ?? gd.oracle_residual ?? "",
    testsMutationCaught:
      typeof gd.tests_mutation_caught === "boolean" ? gd.tests_mutation_caught : null,
    claims: (gate.claims ?? []).map((c) => {
      const d = verdicts.get(c.id);
      return {
        id: c.id,
        text: c.text,
        // A claim the gate never evaluated is honestly unevaluable, never satisfied.
        verdict: d?.verdict ?? "unevaluable",
        oracleRef: d?.oracle_ref ?? "",
      };
    }),
    critic: gate.outcome_verdict ?? null,
  };
}

/** Receipt from the DURABLE record (receipt/gate_decision rows + the claim ledger). */
export function receiptFromDetail(detail: RunDetail | undefined): ReceiptData | undefined {
  const parsed = parseReceipt(detail);
  if (!parsed) return undefined;
  return {
    ...parsed,
    claims: (detail?.claims ?? []).map((r) => ({
      id: r.claim_id,
      text: r.text,
      verdict: r.verdict,
      oracleRef: r.oracle_ref,
    })),
    critic: parseCriticVerdict(detail) ?? null,
  };
}

const CLAIM_TONE_CLS: Record<string, string> = {
  success: "border-transparent bg-success/15 text-success",
  destructive: "border-transparent bg-destructive/15 text-destructive",
  muted: "border-border/60 text-muted-foreground",
};

/** The delivery receipt: what the gate decided, what the evidence was worth, and
 *  exactly what an approval accepted on record. `compact` embeds inside an
 *  existing card (the live GatePanel / RunDetailPanel); full renders standalone. */
export function ReceiptCard({
  receipt,
  compact = false,
}: {
  receipt: ReceiptData | undefined;
  compact?: boolean;
}) {
  if (!receipt) {
    return compact ? null : (
      <section className="rounded-lg bg-card p-4 ring-1 ring-white/12">
        <ConsoleLabel>Receipt</ConsoleLabel>
        <EmptyNote>No receipt recorded for this run.</EmptyNote>
      </section>
    );
  }
  // "shallow" is NEVER green (ADR-0034): a green syntax check is not a green suite.
  const strengthGood = receipt.validationStrength === "suite" && receipt.testsPassed === true;
  const mutation = mutationPlain(receipt.testsMutationCaught);
  const body = (
    <div className={cn("flex min-w-0 flex-col", compact ? "gap-2" : "gap-3")}>
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge
          className="border-white/15 font-mono text-[10px] uppercase text-foreground/75"
          title={receipt.action || undefined}
        >
          {receipt.action ? actionPlain(receipt.action) : "—"}
        </Badge>
        <Badge className="border-white/15 font-mono text-[10px] uppercase text-foreground/75">
          reviewer: {reviewerVerdict(receipt.reviewerVerdict || "UNKNOWN")}
        </Badge>
        <Badge
          className={cn(
            "font-mono text-[10px] uppercase",
            strengthGood
              ? "border-transparent bg-success/15 text-success"
              : "border-white/15 text-foreground/75",
          )}
        >
          checks: {receipt.validationStrength === "suite" ? "full test suite" : receipt.validationStrength}
        </Badge>
        <Badge
          className={cn(
            "font-mono text-[10px] uppercase",
            mutation.tone === "success"
              ? "border-transparent bg-success/15 text-success"
              : mutation.tone === "amber"
                ? "border-transparent bg-primary/15 text-primary"
                : "border-white/15 text-foreground/75",
          )}
        >
          {mutation.label}
        </Badge>
        {receipt.humanOverride && (
          <Badge className="border-transparent bg-primary/15 font-mono text-[10px] uppercase text-primary">
            human override
          </Badge>
        )}
      </div>

      {receipt.validationStrength !== "suite" && VALIDATION_STRENGTH[receipt.validationStrength] && (
        /* Non-suite only: for a full suite the "checks" chip already says it (one fact, one
           render); for shallow/none this sentence is the warning the chip alone can't carry. */
        <p className="font-mono text-[11px] text-muted-foreground">
          {VALIDATION_STRENGTH[receipt.validationStrength]}
        </p>
      )}

      {receipt.reasons.length > 0 && (
        <ul className="flex flex-col gap-0.5 pl-4 font-mono text-[11px] text-muted-foreground">
          {receipt.reasons.map((reason) => (
            <li key={reason} className="list-disc">
              {gateReason(reason)}
            </li>
          ))}
        </ul>
      )}
      {receipt.humanOverride && receipt.reasons.length > 0 && (
        <p className="text-xs leading-relaxed text-muted-foreground">
          A person chose to deliver despite the warnings above — it's on record.
        </p>
      )}

      {receipt.oracleVouchedBy && (
        <p className="font-mono text-[11px] text-foreground/80">
          {humanizeVouch(receipt.oracleVouchedBy)}
        </p>
      )}

      {receipt.oracleResidual && (
        <AmberCallout title={SENTENCES.knownGapTitle} note={SENTENCES.knownGapNote}>
          {receipt.oracleResidual}
        </AmberCallout>
      )}

      {receipt.claims.length > 0 && (
        <div className="flex flex-col gap-1">
          <ConsoleLabel>Acceptance claims</ConsoleLabel>
          <ul className="flex flex-col gap-1">
            {receipt.claims.map((c) => {
              const meta = claimVerdict(c.verdict);
              return (
                <li key={c.id} className="flex flex-wrap items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-xs text-foreground/90">
                    {c.text}
                  </span>
                  <Badge className={cn("font-mono text-[10px]", CLAIM_TONE_CLS[meta.tone])}>
                    {meta.label}
                  </Badge>
                  {c.oracleRef && (
                    <span className="max-w-[16rem] truncate font-mono text-[10px] text-muted-foreground/70">
                      {c.oracleRef}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {receipt.critic?.vetoed && (
        <div className="rounded-md border-l-2 border-destructive/50 bg-destructive/5 p-3">
          <ConsoleLabel className="text-destructive/80">Independent reviewer veto</ConsoleLabel>
          {receipt.critic.reason && (
            <p className="mt-1 text-[11px] leading-relaxed text-foreground/90">
              {receipt.critic.reason}
            </p>
          )}
          {(receipt.critic.rows ?? []).length > 0 && (
            <ul className="mt-1 flex flex-col gap-0.5">
              {(receipt.critic.rows ?? []).map((r, i) => (
                <li key={i} className="font-mono text-[11px] text-muted-foreground">
                  {[r.claim, r.verdict ? CRITIC_VERDICT[normalizeCriticVerdict(r.verdict)] : "", r.note]
                    .filter(Boolean)
                    .join(" · ")}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
  if (compact) return body;
  return (
    <section className="flex min-w-0 flex-col gap-3 rounded-lg bg-card p-4 ring-1 ring-white/12">
      <ConsoleLabel>Receipt</ConsoleLabel>
      {body}
    </section>
  );
}
