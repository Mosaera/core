/* The gate's evidence drawers — the dossier, extracted from GatePanel (which sits one line from
 * the 500-line ceiling). Everything here is DRILL-DOWN by design: per ADR-0082 §1, the summary
 * layer above (VerdictCard + callouts + outcomes) must already contain every fact that could
 * change which option is chosen; these drawers are how the human verifies, not how they learn.
 * The stale-scan guard stays here on the scan line AND feeds the verdict via the radar's security
 * axis — belt and braces, per the ADR-0108 lesson (a stale clean must vouch to no one). */

import type { GatePayload, GateDecision } from "../../api/client";
import { DiffView } from "../DiffView";
import { FindingsList } from "../FindingsList";
import { ConsoleLabel } from "../overview/bits";
import { ReceiptCard, type ReceiptData } from "./ReceiptCard";

export function GateEvidence({
  gate,
  decision,
  receipt,
  isWrite,
  staleScan,
  requestChanges,
}: {
  gate: GatePayload;
  decision: GateDecision | undefined;
  receipt: ReceiptData | undefined;
  isWrite: boolean;
  staleScan: boolean;
  requestChanges: boolean;
}) {
  return (
    <>
      {gate.content !== undefined && (
        <Evidence label={gate.path ? `file · ${gate.path}` : "content"}>
          <pre className="whitespace-pre-wrap">{gate.content || "(empty file)"}</pre>
        </Evidence>
      )}
      {gate.plan && (
        <Evidence label="plan">
          <pre className="whitespace-pre-wrap">{gate.plan}</pre>
        </Evidence>
      )}
      {gate.diff && (
        <details className="group/ev" open={isWrite || undefined}>
          <summary className="flex cursor-pointer list-none items-center gap-2 rounded-md bg-muted/30 px-2.5 py-1.5 hover:bg-muted/50 [&::-webkit-details-marker]:hidden">
            <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
              diff
            </span>
            <span className="ml-auto font-mono text-[10px] text-muted-foreground/60 transition-transform group-open/ev:rotate-180">
              ▾
            </span>
          </summary>
          <div className="mt-1">
            <DiffView diff={gate.diff} />
          </div>
        </details>
      )}
      {/* A clean scan is one quiet line; findings get the full list.
          UNLESS the gate refused that clean, in which case it must not read as a green tick. This
          line was rendered purely from `gate.findings` — the scan TEXT — with no reference to
          `decision.reasons`, so a run parked *because* its clean describes a tree that no longer
          exists still showed the human holding the override button an unqualified green "clean",
          with the contradiction only inside a <details> that is folded by default. That is the
          ADR-0108 defect moved one layer out: the stale verdict stops vouching to the gate and
          carries on vouching to the person. Red team, 2026-08-21. */}
      {gate.findings !== undefined &&
        (String(gate.findings).trim() === "" ||
        String(gate.findings).trim() === "No security findings." ? (
          staleScan ? (
            <p className="font-mono text-[11.5px] text-primary">
              security scan — clean, but not for this code (
              {decision?.reasons.includes("security_stale")
                ? "the tree changed after the scan ran"
                : "this version was never scanned"}
              )
            </p>
          ) : (
            <p className="font-mono text-[11.5px] text-muted-foreground">
              security scan — <span className="text-success">clean</span>
            </p>
          )
        ) : (
          <div className="flex flex-col gap-1">
            <ConsoleLabel>security scan</ConsoleLabel>
            <FindingsList text={String(gate.findings)} />
          </div>
        ))}
      {/* The receipt (#63): the same normalized card as the evidence tab and the
          durable history page — the residual a human accepts must be visible
          exactly where they accept it. */}
      {receipt && (
        /* The badge row that lived here (Checks passed / failed / security found problems) is the
         * VerdictCard's job now — one derived headline instead of a third sibling derivation. */
        <Evidence label="verdict details (receipt)">
          <ReceiptCard receipt={receipt} compact />
        </Evidence>
      )}

      {gate.review && !requestChanges && (
        <Evidence label="reviewer">
          <pre className="whitespace-pre-wrap">{gate.review}</pre>
        </Evidence>
      )}

    </>
  );
}

export function Evidence({ label, children }: { label: string; children: React.ReactNode }) {
  // Folded by default (operator cut, 2026-08-13): the gate states the DECISION; the
  // dossier opens on demand instead of arriving as a wall.
  return (
    <details className="group/ev">
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-md bg-muted/30 px-2.5 py-1.5 hover:bg-muted/50 [&::-webkit-details-marker]:hidden">
        <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          {label}
        </span>
        <span className="ml-auto font-mono text-[10px] text-muted-foreground/60 transition-transform group-open/ev:rotate-180">
          ▾
        </span>
      </summary>
      <div className="mt-1 max-h-56 overflow-y-auto rounded-md bg-background p-2 font-mono text-[11px] leading-relaxed text-foreground/80 [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin]">
        {children}
      </div>
    </details>
  );
}
