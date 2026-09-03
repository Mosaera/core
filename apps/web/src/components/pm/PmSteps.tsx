import { useEffect, useState } from "react";

import { PulseDot } from "@/components/PulseDot";
import type { PmStep } from "@/api/pmStream";
import { fmtDuration } from "@/lib/duration";
import { pmStep, pmStepsSummary } from "@/lib/plain";

import { PmAvatar } from "./PmMessage";

/** Seconds since `startedAt`, ticking. Local to this file because it is one `setInterval` and a
 *  re-render; the run pages have their own, pause-aware, and merging the two is a cleanup rather
 *  than a thing to do while adding a feature. */
function useSeconds(startedAt: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [startedAt]);
  return Math.max(0, (now - startedAt) / 1000);
}

/** Quincy working: what he has checked, what he is checking now, and how long it has taken.
 *
 *  Replaces the old three-dot "thinking…" for a streamed turn. The difference is the point — the
 *  dots said only that something was happening, where this says WHAT, which is the whole
 *  complaint that started this work.
 *
 *  Only the current line is `aria-live`. Announcing the elapsed clock would read a new number
 *  every second, and announcing the completed steps would replay the whole list each time one
 *  was added. */
export function PmWorking({
  steps,
  prose,
  startedAt,
}: {
  steps: PmStep[];
  prose: string[];
  startedAt: number;
}) {
  const seconds = useSeconds(startedAt);
  const current = steps.length ? steps[steps.length - 1] : null;
  const label = current ? pmStep(current.tool, current.arg) : "Thinking";
  return (
    <div className="flex flex-col gap-2">
      {/* Anything he said on the way here reads as ordinary speech, because it is. */}
      {prose.map((line, i) => (
        <div key={i} className="flex items-start gap-2.5 animate-in fade-in duration-300">
          <PmAvatar />
          <p className="text-[15px] leading-relaxed text-foreground/90">{line}</p>
        </div>
      ))}
      <div className="flex items-center gap-2.5">
        <PmAvatar />
        <div className="flex items-center gap-2">
          <PulseDot />
          <span className="font-mono text-[11px] text-muted-foreground/80" role="status" aria-live="polite">
            {label}…
          </span>
          {/* `tabular-nums` so the clock does not reflow every second — which also keeps it out
              of the auto-scroll dependency list. */}
          <span className="font-mono text-[11px] tabular-nums text-muted-foreground/50" aria-hidden>
            {fmtDuration(seconds)}
          </span>
        </div>
      </div>
    </div>
  );
}

/** What a finished reply checked, folded away.
 *
 *  Native `<details>`: keyboard handling, expanded-state semantics and the disclosure triangle
 *  all come free, there is no `Collapsible` primitive in this codebase to reuse, and it works
 *  with no state of its own — so the same component renders a live turn and a reloaded one.
 *
 *  Closed by default. A couple of lookups per turn, expanded, would push the actual conversation
 *  off the screen within a few exchanges. */
export function PmStepsSummary({ steps, seconds = 0 }: { steps: PmStep[]; seconds?: number }) {
  if (!steps.length) return null;
  return (
    <details className="mt-1.5 group">
      <summary className="cursor-pointer select-none font-mono text-[11px] text-muted-foreground/60 hover:text-muted-foreground">
        {pmStepsSummary(steps.length, seconds)}
      </summary>
      <ul className="mt-1 flex flex-col gap-0.5 border-l border-border/50 pl-3">
        {steps.map((step, i) => (
          <li key={i} className="font-mono text-[11px] text-muted-foreground/70">
            {pmStep(step.tool, step.arg)}
          </li>
        ))}
      </ul>
    </details>
  );
}
