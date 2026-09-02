import { AlertTriangle } from "lucide-react";

import { pmTurnFailure } from "@/lib/plain";

/** A PM turn that did not complete, shown where the reply would have been.
 *
 *  Deliberately NOT a fourth `PmMessage` variant. `PmMessage`'s job is "who said this", and this
 *  is nobody's words — it is the engine reporting that a turn failed. Before this existed the
 *  server wrote an apology as a `pm` row, so a failure arrived wearing Quincy's avatar and name
 *  and the operator had to read the sentence carefully to notice nothing had been answered.
 *
 *  It also must not pass through `PmMarkdown`: a cause token has no markdown, and routing engine
 *  text through the model-reply renderer is how the hazard class slice 0 closed gets reopened.
 *
 *  The absence of the avatar and the name row is the discriminator that survives a scroll-back
 *  three days later — before any word is read.
 *
 *  Amber, not destructive red: nothing broke that the operator caused and nothing was lost.
 *  `role="note"`, not `role="alert"`: this row persists, and an alert that re-announces itself
 *  every time the transcript scrolls into view would be wrong. Genuine HTTP failures keep the
 *  `role="alert"` line in PmChatPanel. */
export function PmTurnFailure({ cause, timestamp }: { cause: string; timestamp?: string }) {
  return (
    <div
      role="note"
      data-turn-failure={cause}
      title={timestamp}
      className="my-1 flex flex-col gap-1 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2"
    >
      <div className="flex items-center gap-1.5">
        <AlertTriangle className="size-3.5 shrink-0 text-amber-500/80" aria-hidden />
        <span className="font-mono text-[10px] uppercase tracking-wide text-amber-500/80">
          Turn didn't complete
        </span>
        {/* The raw token beside the reading — RunDiagnosisCard's charter: the record is exact,
            the sentence is a reading and is labeled as such. */}
        <span className="font-mono text-[10px] text-muted-foreground/60">{cause}</span>
      </div>
      <p className="text-[13px] leading-relaxed text-foreground/80">{pmTurnFailure(cause)}</p>
    </div>
  );
}
