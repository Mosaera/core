/* The verdict band (#63): the page's closing argument, rendered only once a run
   concludes. Delivered → "Why this delivered": every claim beside the check it
   stands on, then how strong that proof actually is. Stopped → "Why this run
   stopped": the unmet requirement and what the record keeps.

   The honesty rule is NOT re-implemented here — claimSegments owns it. A claim
   whose check didn't run and pass can never render as PROVEN, and a stopped run
   never speaks delivered language. */

import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { RunDiagnosis } from "../../../api/client";
import type { PmPrefillState } from "../../../lib/backlog";
import type { LedgerClaim, LedgerRow } from "../../../lib/ledger";
import { honestyBadge } from "../../../lib/ledger";
import {
  claimVerdict,
  mutationPlain,
  oracleKind,
  provenancePill,
  reviewerVerdict,
  SENTENCES,
  stopReason,
  VALIDATION_STRENGTH,
} from "../../../lib/plain";
import { parkedRunPrefill, type ParsedReceipt } from "../../../lib/runs";
import { claimSegments, type SegmentTone } from "../hero/ClaimBar";
import { Block } from "./blocks";
import { VerdictCard } from "../VerdictCard";
import { radarFromReceipt } from "../../../lib/radar";
import { verdictFromRecord } from "../../../lib/verdict";
import { TONE_BADGE } from "../../StatusBadge";

const PILL: Record<SegmentTone, { text: string; cls: string }> = {
  verified: { text: "PROVEN", cls: TONE_BADGE.success },
  attention: { text: "FAILED", cls: TONE_BADGE.destructive },
  unchecked: { text: "NOT CHECKED", cls: TONE_BADGE.amber },
  preference: { text: "PREFERENCE", cls: TONE_BADGE.neutral },
};

/** The heading names the outcome for what it actually was — a crash is not an
 *  honest park, and a person declining is not the engine parking. One statement
 *  of the verdict per page: the hero says it once, this heading says why. */
const WHY_HEADING: Record<string, string> = {
  "NOT APPROVED": "Why this was declined",
  ERROR: "Why this crashed",
  CANCELLED: "Why this was cancelled",
  INCOMPLETE: "Why this parked",
};

const GLYPH: Record<SegmentTone, { char: string; cls: string }> = {
  verified: { char: "✓", cls: TONE_BADGE.success },
  attention: { char: "✗", cls: TONE_BADGE.destructive },
  unchecked: { char: "○", cls: TONE_BADGE.amber },
  preference: { char: "·", cls: TONE_BADGE.neutral },
};

function ClaimRow({ claim, tone }: { claim: LedgerClaim; tone: SegmentTone }) {
  const g = GLYPH[tone];
  const pill = PILL[tone];
  return (
    <li className="flex items-start gap-3 border-t border-border/40 py-2.5 first:border-t-0">
      <span
        aria-hidden
        className={cn("mt-0.5 flex size-[19px] shrink-0 items-center justify-center rounded-full text-[11px] font-extrabold", g.cls)}
      >
        {g.char}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[13px] font-medium">{claim.text}</span>
        <span className="mt-0.5 block text-[11.5px] leading-relaxed text-muted-foreground">
          {oracleKind(claim.oracleKind)}
          {claim.oracleRef && <> · <span className="font-mono">{claim.oracleRef}</span></>}
          {claim.verdict && <> — {claimVerdict(claim.verdict).label}</>}
          {" · "}
          <span className="font-mono text-[10.5px]">{provenancePill(claim.provenance, claim.material)}</span>
        </span>
      </span>
      <span className={cn("shrink-0 rounded-full px-2.5 py-[3px] font-mono text-[10px] font-semibold", pill.cls)}>
        {pill.text}
      </span>
    </li>
  );
}

function ProofRow({ ok, text, sub }: { ok: boolean; text: string; sub?: string }) {
  return (
    <li className="flex items-start gap-3 border-t border-border/40 py-2.5 text-[12.5px] first:border-t-0">
      <span aria-hidden className={cn("font-extrabold", ok ? "text-success" : "text-muted-foreground")}>
        {ok ? "✓" : "○"}
      </span>
      <span className="min-w-0">
        <span className="block">{text}</span>
        {sub && <span className="mt-0.5 block text-[11.5px] text-muted-foreground">{sub}</span>}
      </span>
    </li>
  );
}

/** How strong the proof is: the validation facts, each one earned or honestly absent. */
function proofRows(receipt: ParsedReceipt | undefined, testCount: number): { ok: boolean; text: string; sub?: string }[] {
  const rows: { ok: boolean; text: string; sub?: string }[] = [];
  const strength = receipt?.validationStrength ?? "unknown";
  rows.push({
    ok: strength === "suite",
    text: VALIDATION_STRENGTH[strength] ?? strength,
    sub: testCount > 0 ? `${testCount} check run${testCount === 1 ? "" : "s"} on record` : undefined,
  });
  const mut = mutationPlain(receipt?.testsMutationCaught);
  rows.push({ ok: mut.tone === "success", text: mut.label });
  rows.push({
    ok: true,
    text: "The checks ran in a throwaway sandbox with the network off",
    sub: "results can't be fetched or faked",
  });
  if (receipt?.reviewerVerdict)
    rows.push({
      ok: /APPROVE/i.test(receipt.reviewerVerdict),
      text: `Independent review: ${reviewerVerdict(receipt.reviewerVerdict)}`,
      sub: "a reviewer can reject or park — it can never green-light delivery",
    });
  if (receipt?.oracleResidual)
    rows.push({ ok: false, text: `Priced residual: ${receipt.oracleResidual}`, sub: "named, not hidden" });
  if (receipt?.humanOverride) rows.push({ ok: false, text: SENTENCES.gateOverrideNote });
  return rows;
}

export function VerdictBand({
  rows,
  receipt,
  testCount = 0,
  footer,
  diagnosis,
  runId,
  task,
  pmProjectId,
  ghosts,
}: {
  rows: LedgerRow[];
  receipt?: ParsedReceipt;
  testCount?: number;
  /** The RECORD/seal strip (RecordFooter) — the band's closing line. */
  footer?: React.ReactNode;
  /** The structured "how it ended" record (#75); null/absent = pre-diagnosis row. */
  diagnosis?: RunDiagnosis | null;
  runId?: string;
  task?: string;
  /** Enables the Send-to-Quincy handoff; ad-hoc runs have no PM page. */
  pmProjectId?: string | null;
  /** The same item's prior settled attempts, as faint literal shapes behind the current one. */
  ghosts?: import("../../../lib/radar").AxisValue[][];
}) {
  const navigate = useNavigate();
  const badge = honestyBadge(rows);
  if (badge.kind === "in-progress") return null; // live runs get no verdict yet

  const decomposition = rows.find((r) => r.kind === "decomposition");
  const claims = decomposition?.kind === "decomposition" ? decomposition.claims : [];
  const segments = claimSegments(claims);
  const terminated = rows.find((r) => r.kind === "terminated");

  if (terminated?.kind === "terminated") {
    const unmet = claims.filter((c) => c.material && c.verdict !== "satisfied");
    const reason = stopReason(diagnosis);
    const gates = diagnosis?.gate_reasons ?? [];
    return (
      <section
        aria-label={WHY_HEADING[terminated.status] ?? "Why this stopped"}
        data-verdict="stopped"
        className="flex flex-col items-stretch gap-4 border-t border-border pt-7"
      >
        <VerdictCard
          verdict={verdictFromRecord({
            delivered: false,
            claims,
            /* The receipt is the richer source; diagnosis.gate_reasons is the fallback. Seen on
             * the live instance: a pre-redesign run whose diagnosis carried no gate_reasons
             * rendered a reason-less card while its receipt held four — the card must read the
             * best record available, not the first one tried. */
            reasons: receipt?.reasons?.length ? receipt.reasons : gates,
            humanOverride: false,
            validationStrength: receipt?.validationStrength,
            /* NO `status` fallback here: the HERO states the terminal sentence
             * ("Ended without delivering.") — repeating it in the card was the double-verdict
             * this redesign exists to end. `stopReason` prose still flows through `diagnosis`. */
            diagnosis,
          })}
          axes={
            receipt
              ? radarFromReceipt(receipt, claims, {
                  testsModified: diagnosis?.tests_modified === true,
                })
              : []
          }
          subhead={WHY_HEADING[terminated.status] ?? "Why this stopped"}
          ghosts={ghosts}
          compact
        />
        {/* The stop paragraph that lived here restated the hero's status sentence and the card's
            reason (redundancy audit 2026-08-22) — the card + record ProofRow own the story now. */}
        <div className="grid gap-x-8 gap-y-7 lg:grid-cols-2">
          <Block title="What was not proven">
            {unmet.length > 0 ? (
              <ul>
                {unmet.map((c) => {
                  const tone = segments.find((s) => s.id === c.id)?.tone ?? "unchecked";
                  return <ClaimRow key={c.id} claim={c} tone={tone} />;
                })}
              </ul>
            ) : (
              <p className="py-1 text-[12.5px] text-muted-foreground">
                No claims were bound before the run stopped.
              </p>
            )}
          </Block>
          <Block title="What the record keeps">
            <ul>
              {/* The FULL stop reason from the diagnosis when it exists — the ledger
                  string is capped at 80 chars by the DB column, never the record. */}
              <ProofRow
                ok={false}
                text={reason?.text || terminated.reason || "The run ended before delivering."}
                sub={reason ? reason.label.toLowerCase() : "the recorded reason"}
              />
              {/* The per-reason listing that lived here is the VerdictCard's job now (dominant
                  reason + chips) — repeating it made the same sentence appear twice on one page. */}
              <ProofRow
                ok={false}
                text="Nothing was committed and nothing was sealed"
                sub={`the run is recorded as ${terminated.status.toLowerCase()} — never dressed as “completed”`}
              />
              <ProofRow ok text="Every attempt, check run and verdict is preserved" sub="replayable from the record below" />
            </ul>
          </Block>
        </div>
        {/* The one next step: hand the park to Quincy — prefilled, reviewed, sent by YOU. */}
        {pmProjectId && runId && (
          <div className="flex items-center gap-3">
            <Button
              onClick={() =>
                navigate(`/projects/${pmProjectId}/pm`, {
                  state: {
                    pmPrefill: parkedRunPrefill(
                      { id: runId, task: task ?? "", status: terminated.status },
                      diagnosis,
                    ),
                  } satisfies PmPrefillState,
                })
              }
            >
              Send to Quincy
            </Button>
            <span className="text-[12px] text-muted-foreground">
              opens the PM chat with this park's facts prefilled — you review and send
            </span>
          </div>
        )}
        {footer}
      </section>
    );
  }

  return (
    <section
      aria-label="Why this delivered"
      data-verdict="delivered"
      className="flex flex-col items-stretch gap-4 border-t border-border pt-7"
    >
      {/* ONE derived headline for the whole page (lib/verdict.ts) — this replaced the static
        * "Why this delivered" h3 + intro; the section's aria-label keeps that name as the
        * region contract the tests pin. */}
      <VerdictCard
        verdict={verdictFromRecord({
          delivered: true,
          claims,
          reasons: receipt?.reasons ?? [],
          humanOverride: receipt?.humanOverride === true,
          validationStrength: receipt?.validationStrength,
          diagnosis,
        })}
        axes={receipt ? radarFromReceipt(receipt, claims, { testsModified: diagnosis?.tests_modified === true }) : []}
        ghosts={ghosts}
        compact
      />
      <p className="-mt-2 max-w-[88ch] text-[13px] text-muted-foreground">
        The gate is deterministic: it counted the evidence below — it cannot be persuaded. The agents
        proposed, the checks proved, you decided.
      </p>
      <div className="grid gap-x-8 gap-y-7 lg:grid-cols-[1.35fr_1fr]">
        {/* The header badges ("N proven / N not checked") were a column-sum of the pill column
            directly beneath + the hero ClaimBar's aggregate (redundancy audit 2026-08-22). */}
        <Block title="What was claimed — and how each claim was checked">
          {claims.length > 0 ? (
            <ul>
              {claims.map((c) => (
                <ClaimRow key={c.id} claim={c} tone={segments.find((s) => s.id === c.id)?.tone ?? "unchecked"} />
              ))}
            </ul>
          ) : (
            <p className="py-1 text-[12.5px] text-muted-foreground">
              No claims were recorded for this run — nothing was checked against a stated promise.
            </p>
          )}
        </Block>
        <Block title="How strong the proof is">
          <ul>
            {proofRows(receipt, testCount).map((r, i) => (
              <ProofRow key={i} {...r} />
            ))}
          </ul>
        </Block>
      </div>
      {footer}
    </section>
  );
}
