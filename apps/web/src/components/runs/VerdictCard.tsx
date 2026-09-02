/* The executive layer of a run: ONE derived verdict, ONE dominant reason, the proof radar, and
 * every remaining gate reason as chips. Derivation is `lib/verdict.ts` — deterministic tokens,
 * never a model's prose over one (ADR-0082: the gate cannot be persuaded, so its headline must
 * not be authorable).
 *
 * ADR-0107: the clarification slot renders ABOVE the headline. A tidy verdict never visually
 * supersedes an open ask.
 * ADR-0082 §1: the chips + notes ARE the summary layer — every reason's sentence is findable
 * without opening any disclosure. Evidence demotes; facts that pick options do not. */

import { cn } from "../../lib/utils";
import type { AxisValue } from "../../lib/radar";
import type { Verdict } from "../../lib/verdict";
import { Badge } from "../ui/badge";
import { TONE_BADGE } from "../StatusBadge";
import { ProofRadar } from "./ProofRadar";

const HEADLINE_TONE: Record<string, string> = {
  success: "text-success",
  amber: "text-primary",
  destructive: "text-destructive",
  muted: "text-muted-foreground",
};

export function VerdictCard({
  verdict,
  axes,
  ghosts,
  above,
  subhead,
  compact = false,
}: {
  verdict: Verdict;
  axes: AxisValue[];
  ghosts?: AxisValue[][];
  /** The unsuppressible slot — open clarifications/asks render here, above the headline. */
  above?: React.ReactNode;
  /** The ending KIND ("Why this crashed" / "Why this was declined") — the honesty distinction the
   *  old per-status heading carried: a crash is not an honest park, and a person declining is not
   *  the engine parking. The verdict word alone must not flatten that. */
  subhead?: string;
  compact?: boolean;
}) {
  return (
    <section
      aria-label="verdict"
      className="flex flex-col gap-3 rounded-lg bg-card p-4 ring-1 ring-white/12"
    >
      {above}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h3 className={cn("text-xl font-semibold tracking-tight", HEADLINE_TONE[verdict.tone])}>
            {verdict.headline}
          </h3>
          {subhead && (
            <p className="mt-0.5 font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
              {subhead}
            </p>
          )}
          {verdict.reason && (
            <p className="mt-1.5 max-w-prose text-sm text-muted-foreground">{verdict.reason.text}</p>
          )}
          {verdict.secondary.length > 0 && (
            /* ADR-0082 §1: every remaining reason, in the summary layer, never behind a drawer. */
            <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="other gate reasons">
              {verdict.secondary.map((r) => (
                <li key={r.token}>
                  <Badge className={cn("font-mono text-[10px]", TONE_BADGE.neutral)}>{r.text}</Badge>
                </li>
              ))}
            </ul>
          )}
          {!compact && axes.length > 0 && (
            <ul className="mt-3 flex flex-col gap-1" aria-label="proof axes">
              {axes.map((a) => (
                <li key={a.axis} className="flex items-baseline gap-2 text-[12.5px]">
                  <span
                    className={cn(
                      "font-mono text-[10px] uppercase tracking-[0.1em]",
                      a.breach
                        ? "text-destructive"
                        : a.value === "proven"
                          ? "text-success"
                          : "text-muted-foreground",
                    )}
                  >
                    {a.label}
                  </span>
                  <span className="text-muted-foreground">{a.note}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        {axes.length > 0 && <ProofRadar axes={axes} ghosts={ghosts} size={compact ? 168 : 208} />}
      </div>
    </section>
  );
}
