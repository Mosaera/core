import { cn } from "@/lib/utils";

import type { LedgerClaim } from "../../../lib/ledger";

export type SegmentTone = "verified" | "attention" | "unchecked" | "preference";

/** Segment tone per claim — the honesty rule in one place: only a claim whose
 *  check ran and PASSED is green; failed/needs-you is amber; everything without
 *  a verdict (pre-run, unbound, unevaluable) is dim — never green; a preference
 *  is a hollow outline (recorded, can't gate). */
export function claimSegments(
  claims: LedgerClaim[],
): { id: string; text: string; tone: SegmentTone }[] {
  return claims.map((c) => ({
    id: c.id,
    text: c.text,
    tone: !c.material
      ? "preference"
      : c.verdict === "satisfied"
        ? "verified"
        : c.verdict === "failed"
          ? "attention"
          : "unchecked",
  }));
}

const SEGMENT_CLS: Record<SegmentTone, string> = {
  verified: "bg-success",
  attention: "bg-amber-500",
  unchecked: "bg-foreground/15",
  preference: "border border-border bg-transparent",
};

const TONE_WORD: Record<SegmentTone, string> = {
  verified: "verified",
  attention: "needs attention",
  unchecked: "not checked",
  preference: "preference",
};

/** The claim bar: one segment per claim, verdicts at a glance. `dim` renders the
 *  running state (everything muted while verdicts land). */
export function ClaimBar({ claims, dim = false }: { claims: LedgerClaim[]; dim?: boolean }) {
  const segments = claimSegments(claims);
  if (segments.length === 0) return null;
  const verified = segments.filter((s) => s.tone === "verified").length;
  const checkable = segments.filter((s) => s.tone !== "preference").length;
  return (
    <div className="flex items-center gap-3" aria-label="Claim verdicts">
      <div className={cn("flex h-2 flex-1 gap-1", dim && "opacity-40")}>
        {segments.map((s) => (
          <span
            key={s.id}
            title={`${s.id} · ${s.text} — ${TONE_WORD[s.tone]}`}
            aria-label={`${s.id}: ${TONE_WORD[s.tone]}`}
            className={cn(
              "min-w-2 flex-1 rounded-full",
              SEGMENT_CLS[dim ? "unchecked" : s.tone],
              s.tone === "preference" && "bg-transparent",
            )}
          />
        ))}
      </div>
      <span className="shrink-0 font-mono text-[12px] tabular-nums text-muted-foreground">
        {verified} of {checkable} verified
      </span>
    </div>
  );
}
