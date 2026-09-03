import { RotateCcw, ShieldQuestion } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { TONE_BADGE } from "../StatusBadge";

import type { GatePayload } from "../../api/client";
import { ConsoleLabel } from "../overview/bits";
import { AmberCallout } from "../ui/AmberCallout";
import { receiptFromGate } from "./ReceiptCard";
import { GateEvidence } from "./GateEvidence";
import { VerdictCard } from "./VerdictCard";
import { claimsFromGate, verdictFromGate } from "../../lib/verdict";
import { radarFromGate } from "../../lib/radar";

/** The hero moment, in the new design system: a human weighs a gated action on
 *  real evidence and approves or denies it. Ported from the legacy
 *  ApprovalPanel; the gate-decision signals stay honest (MR !45/!48). */
export function GatePanel({
  gate,
  busy,
  onDecide,
  variant = "card",
  autoAllowTests = false,
  onAutoAllowTests,
}: {
  gate: GatePayload;
  busy: boolean;
  onDecide: (
    approve: boolean,
    feedback: string,
    authorizeTests?: string[],
    optionId?: string,
  ) => void;
  /** "hero" strips the card chrome (the DecisionHero owns the frame); decision
   *  semantics are identical in both variants. */
  variant?: "card" | "hero";
  /** Write gates only: offer + reflect "allow the remaining test-file writes". The
   *  Assayer's tests/ scope stays enforced server-side (ADR-0013) — this only spares
   *  the operator N identical clicks; it never widens what may be written. */
  autoAllowTests?: boolean;
  onAutoAllowTests?: (on: boolean) => void;
}) {
  const action = gate.action ?? "action";
  const decision = gate.gate_decision;
  const receipt = receiptFromGate(gate);
  const requestChanges = Boolean(decision?.reasons.includes("reviewer_requested_changes"));
  // When the reviewer requested changes, they already said what to change —
  // seed the notes so "send back" carries the reviewer's asks to the coder
  // without the human retyping them. Editable; the parent keys this panel per
  // gate so a new gate re-seeds. (VERDICT line stripped.)
  const seeded = requestChanges ? reviewerChanges(gate.review) : "";
  const [feedback, setFeedback] = useState(seeded);
  // The gate's OWN account of what each answer does. Empty for gates that have not been given
  // outcomes yet, which is why the legacy branch below still exists.
  const outcomes = gate.outcomes ?? [];
  const flagged = Boolean(decision && decision.reasons.length > 0);
  // The gate refused the security evidence — so whatever the scan TEXT says, it does not describe
  // the code under this button. Every reason here is class `not_run` (ADR-0107/0108).
  const staleScan = Boolean(
    decision?.reasons.some((r) =>
      ["security_stale", "security_not_attempted", "security_unverified"].includes(r),
    ),
  );
  // A per-file write/edit/delete gate is not a delivery decision, and must not borrow its verbs.
  const isWrite = action === "write_file" || action === "edit_file" || action === "delete_file";
  // ESCALATION GATE (ADR-0087, #65). The run is blocked by a DELIVERED acceptance test the coder
  // may not edit, so re-planning cannot help — before this the only honest move was to conclude
  // the run. Ticking a test authorizes the PROCTOR (never the coder) to rewrite it once. Nothing
  // is pre-ticked: an amendment is a requirement change, and it should take a deliberate act.
  const amendable = gate.amendable;
  const [authorized, setAuthorized] = useState<string[]>([]);
  const toggleAuthorized = (nodeId: string) =>
    setAuthorized((prev) =>
      prev.includes(nodeId) ? prev.filter((t) => t !== nodeId) : [...prev, nodeId],
    );
  // Revision budget: "send back to revise" loops to planning until the cap,
  // after which the run finalizes without delivering.
  const iteration = gate.iteration ?? 0;
  const maxIter = gate.max_iterations;
  const budgetNote =
    maxIter != null
      ? iteration + 1 >= maxIter
        ? `Final revision — after this the run ends without delivering.`
        : `Sending it back starts revision ${Math.min(iteration + 1, maxIter)} of ${maxIter}.`
      : "";
  // The old validationTone/validationLabel badge block lived here — a third sibling headline
  // derivation. deriveVerdict is the one derivation now; validation_unverified feeds it.
  const verdict = decision ? verdictFromGate(gate, claimsFromGate(gate)) : null;
  const axes = decision ? radarFromGate(gate, claimsFromGate(gate)) : [];

  return (
    <section
      role="alertdialog"
      aria-label="approval required"
      className={
        variant === "hero"
          ? "flex flex-col gap-3"
          : "flex flex-col gap-3 rounded-lg bg-card p-4 ring-1 ring-primary/40"
      }
    >
      {/* Redundancy audit 2026-08-22: both live mounts are variant="hero", and both containers
          already announce the pause (RunHero's "Needs your decision" chip; the dock bar's
          "needs you · The run is paused — {action}") — this row made it a triple render. The
          container owns "you must decide"; hero keeps only a non-deliver ACTION word (the one
          fact RunHero's chip doesn't carry). The card variant keeps the full row: standalone,
          nothing above it speaks. */}
      {variant === "hero" ? (
        action !== "deliver" && (
          <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
            {action}
          </p>
        )
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <Badge className={cn("font-mono text-[10px] uppercase", TONE_BADGE.amber)}>
            <ShieldQuestion className="size-3" />
            Needs your decision
          </Badge>
          <p className="text-base font-medium">
            The run is paused until you decide
            {action !== "deliver" && <span className="text-muted-foreground"> · {action}</span>}
          </p>
        </div>
      )}

      {verdict && (
        /* The executive layer (ADR-0082): what shipping now would stand on, derived — never
         * authored. Chips carry every remaining reason; the drawers below are verification. */
        <VerdictCard verdict={verdict} axes={axes} />
      )}

      {/* Two DIFFERENT honest outcomes, both of which the human must see before approving:
        * `stalled` — the run thrashed and was cut off. `give_up_reason` — it DIAGNOSED that it
        * could not converge and concluded early, below the cap. Gating this block on `stalled`
        * alone meant every honest early conclusion (#56, and far more of them after #81) showed
        * the approver nothing at all. */}
      {(gate.stalled || gate.give_up_reason) && (
        <AmberCallout
          title={
            gate.stalled ? "Couldn't fully complete this" : "Stopped early — it couldn't converge"
          }
        >
          {gate.give_up_reason ||
            gate.stall_reason ||
            "The run stopped making progress before finishing — weigh this before you approve."}
        </AmberCallout>
      )}

      {gate.summary && <p className="text-sm leading-relaxed text-muted-foreground">{gate.summary}</p>}

      {requestChanges && gate.review && (
        <div className="rounded-md border-l-2 border-primary/50 bg-primary/5 p-3">
          <ConsoleLabel className="text-primary/80">Reviewer requested changes</ConsoleLabel>
          <pre className="mt-1 whitespace-pre-wrap font-mono text-[12px] leading-relaxed text-foreground/90">
            {gate.review}
          </pre>
        </div>
      )}

      <GateEvidence
        gate={gate}
        decision={decision}
        receipt={receipt}
        isWrite={isWrite}
        staleScan={staleScan}
        requestChanges={requestChanges}
      />

      {gate.hygiene_status === "unavailable" || gate.hygiene_status === "not_applicable" ? (
        // #80: "the linter did not run" and "the linter found nothing" were the same empty state
        // for the whole life of this field — declared, populated, and read by nobody.
        <AmberCallout
          title={
            gate.hygiene_status === "not_applicable"
              ? "No lint or type check applied"
              : "Lint and type checks did not fully run"
          }
        >
          {gate.hygiene_status === "not_applicable"
            ? "This change touched no Python, so the lint/type gate had nothing to check — that is not the same as passing it."
            : `${(gate.hygiene_unavailable ?? []).join(", ") || "Some tools"} produced no verdict, so those checks did NOT run on this change.`}
        </AmberCallout>
      ) : null}

      {gate.amendment_refusals && Object.keys(gate.amendment_refusals).length > 0 ? (
        // F71: the operator authorized an amendment and the Assayer's write was refused. Naming
        // the rule that bit is the difference between a control and a silence.
        <AmberCallout title="Your authorized amendment was refused">
          <ul className="flex flex-col gap-1">
            {Object.entries(gate.amendment_refusals).map(([path, why]) => (
              <li key={path}>
                <code className="font-mono text-[12px]">{path}</code> — {why}
              </li>
            ))}
          </ul>
        </AmberCallout>
      ) : null}

      {gate.amendable_withheld ? (
        // F65: an offer that never appears and a control that does not exist look identical from
        // here. When the amendment is suppressed BECAUSE of something, say which something.
        <AmberCallout title="Amending a test is not available on this run">
          {gate.amendable_withheld}
        </AmberCallout>
      ) : null}

      {amendable?.tests?.length ? (
        <div className="flex flex-col gap-2 rounded-md border border-primary/40 bg-primary/5 p-3">
          <ConsoleLabel>blocked by a delivered test</ConsoleLabel>
          <p className="text-[13px] text-muted-foreground">
            The coder cannot edit these — they were delivered as the acceptance bar — so sending it
            back will hit the same wall. If this item CHANGES the behaviour one of them asserts,
            authorize amending it and the tester will rewrite that test once.
          </p>
          {amendable.criterion && (
            <p className="text-[13px] text-foreground">
              <span className="text-muted-foreground">This item asks for: </span>
              {amendable.criterion}
            </p>
          )}
          <div className="flex flex-col gap-1.5">
            {amendable.tests.map((nodeId) => (
              <label key={nodeId} className="flex items-start gap-2 text-[13px]">
                <input
                  type="checkbox"
                  checked={authorized.includes(nodeId)}
                  onChange={() => toggleAuthorized(nodeId)}
                  disabled={busy}
                  className="mt-0.5"
                />
                <code className="font-mono text-[12px]">{nodeId}</code>
              </label>
            ))}
          </div>
          {authorized.length > 0 && (
            <p className="text-[12px] text-muted-foreground/80">
              Say what changed in the notes below — it goes to the tester as the reason, and is
              recorded with the amendment.
            </p>
          )}
        </div>
      ) : null}

      {/* Actions named for what they do: "send back to revise" loops the run
          to planning with your notes (until the cap); "approve" delivers.
          Each option now carries its own consequence, so nothing depends on the reader
          inferring what a verb means from the reasons above. */}
      <div className="flex flex-col gap-2">
        {budgetNote && <p className="text-[13px] text-muted-foreground">{budgetNote}</p>}
        {requestChanges && seeded && (
          <p className="text-[12px] text-muted-foreground/70">
            Prefilled from the reviewer’s requested changes — edit before sending if needed.
          </p>
        )}
        <textarea
          placeholder={
            // A static placeholder that contradicts the computed options is the same defect
            // class as F61 itself, one layer down — caught on the first live run of the fix:
            // the gate correctly withheld "send back" at the cap while this box still promised
            // one. When no available answer can carry notes anywhere, say so.
            outcomes.length > 0 && !outcomes.some((o) => o.effect === "send_back")
              ? "Notes (recorded on the receipt — no revision follows from here)"
              : requestChanges
                ? "What should change? (sent to the coder when you send it back)"
                : "Notes for the coder (required to send back to revise)"
          }
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          aria-label="feedback"
          rows={requestChanges ? 4 : 2}
          className="w-full rounded-md border border-border bg-background p-2.5 text-sm text-foreground placeholder:text-muted-foreground/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
        />
        {outcomes.length > 0 ? (
          // The engine computed which answers are actually AVAILABLE and what each will do
          // (ADR-0082 §1). An answer that cannot function is simply absent: at the iteration cap
          // there is no "send back", because denying there ends the run and discards these notes
          // — which is what F61 cost ~1.1M tokens of correct work. Each button states its own
          // consequence, so the label can never be the only thing the operator has to go on.
          <div className="flex flex-col gap-1.5">
            {outcomes.map((o) => (
              <Button
                key={o.id}
                size="sm"
                variant={o.recommended ? "default" : "outline"}
                className={cn(
                  "h-auto justify-start whitespace-normal py-2 text-left",
                  o.override && "border-destructive/40 text-destructive hover:bg-destructive/10",
                )}
                // `amend_tests` promises "the Assayer re-authors X and the run continues" — but the
                // CLICK authorizes nothing; the checkbox list above does. With none ticked the
                // amendment is empty, the oracle conflict stands, and the run ENDS: F61's shape
                // inside the machinery built to fix it (red team 2026-08-21, executed). Disabled
                // until at least one test is authorized, mirroring the send-back-needs-notes rule
                // beside it, so the button cannot mean anything other than its label.
                disabled={
                  busy ||
                  (o.effect === "send_back" && !feedback.trim()) ||
                  (o.id === "amend_tests" && authorized.length === 0)
                }
                onClick={() => onDecide(o.effect === "approve", feedback, authorized, o.id)}
              >
                <span className="flex flex-col gap-0.5">
                  <span className="flex items-center gap-1.5 text-[13px] font-medium">
                    {o.label}
                    {o.recommended && (
                      <span className="rounded bg-primary/15 px-1 text-[10px] uppercase tracking-wide">
                        recommended
                      </span>
                    )}
                  </span>
                  <span className="text-[12px] font-normal opacity-80">{o.consequence}</span>
                </span>
              </Button>
            ))}
          </div>
        ) : (
          // Gates that do not declare outcomes: the write/edit/delete gates, and any delivery
          // gate resumed from a checkpoint written before outcomes existed. Kind-correct verbs —
          // this panel used to offer "Approve & deliver" on a single-file write, which is not
          // remotely what that button does. The flagged/override labelling is PRESERVED here on
          // purpose: an old payload must not silently lose it just because the new path usually
          // supersedes this one.
          <div className="flex flex-wrap items-center gap-2">
            {flagged && !isWrite ? (
              <>
                <Button
                  size="sm"
                  disabled={busy || !feedback.trim()}
                  onClick={() => onDecide(false, feedback, authorized)}
                >
                  <RotateCcw data-icon="inline-start" />
                  Send back to revise
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="border-destructive/40 text-destructive hover:bg-destructive/10"
                  disabled={busy}
                  onClick={() => onDecide(true, feedback, authorized)}
                >
                  Approve anyway
                </Button>
              </>
            ) : (
              <>
                <Button
                  size="sm"
                  disabled={busy}
                  onClick={() => onDecide(true, feedback, authorized)}
                >
                  {isWrite ? "Allow this change" : "Approve & deliver"}
                </Button>
                {isWrite && onAutoAllowTests && (gate.path ?? "").startsWith("tests/") && (
                  <label className="flex items-center gap-2 font-mono text-[11.5px] text-muted-foreground">
                    <input
                      type="checkbox"
                      checked={autoAllowTests}
                      onChange={(e) => onAutoAllowTests(e.target.checked)}
                      disabled={busy}
                    />
                    allow the remaining test-file writes this run
                  </label>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-muted-foreground"
                  disabled={busy || !feedback.trim()}
                  onClick={() => onDecide(false, feedback, authorized)}
                >
                  <RotateCcw data-icon="inline-start" />
                  {isWrite ? "Reject it" : "Send back"}
                </Button>
              </>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

/** The reviewer's actionable change list — the review text with the machine
 *  VERDICT line(s) stripped, so it reads as instructions for the coder. */
function reviewerChanges(review: string | undefined): string {
  if (!review) return "";
  return review
    .split("\n")
    .filter((line) => !/^\s*verdict\s*[:*\-\s]/i.test(line))
    .join("\n")
    .trim();
}

