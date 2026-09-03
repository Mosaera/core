import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/** THE badge tone system (coherence pass, 2026-08-13). Four semantic tones, one alpha
 *  ramp — replaces the ten-plus per-file bg/text tone triplets that had drifted across
 *  alphas 10, 15, 60 and 70. Domain files keep their own status→tone dictionaries
 *  (that mapping is domain knowledge); the CLASS STRINGS come only from here. */
export type Tone = "success" | "amber" | "destructive" | "neutral";

export const TONE_BADGE: Record<Tone, string> = {
  success: "border-transparent bg-success/15 text-success",
  amber: "border-transparent bg-primary/15 text-primary",
  destructive: "border-transparent bg-destructive/15 text-destructive",
  neutral: "border-border/60 bg-transparent text-muted-foreground",
};

/** The overview/backlog meta tables (`STATUS_BADGE`, `ITEM_BADGE`, `OUTCOME_META`) speak a
 *  severity vocabulary (green/amber/red); this maps it onto the tones. */
export function severityBadge(severity: string): string {
  const tone: Record<string, Tone> = {
    green: "success",
    amber: "amber",
    red: "destructive",
    neutral: "neutral",
  };
  return TONE_BADGE[tone[severity] ?? "neutral"];
}

/** Run/verdict statuses → tone + display label (the one vocabulary both the runs list
 *  and the gate speak). Unknown statuses render neutral with a lowercased label. */
const RUN_STATUS: Record<string, { tone: Tone; label: string }> = {
  running: { tone: "success", label: "running" },
  awaiting_approval: { tone: "amber", label: "awaiting approval" },
  completed: { tone: "success", label: "completed" },
  incomplete: { tone: "amber", label: "incomplete" },
  cancelling: { tone: "amber", label: "cancelling" },
  cancelled: { tone: "neutral", label: "cancelled" },
  error: { tone: "destructive", label: "error" },
  APPROVED: { tone: "success", label: "approved" },
  "NOT APPROVED": { tone: "destructive", label: "not approved" },
  RUNNING: { tone: "success", label: "running" },
  INCOMPLETE: { tone: "amber", label: "incomplete" },
  CANCELLED: { tone: "neutral", label: "cancelled" },
  ERROR: { tone: "destructive", label: "error" },
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const s = RUN_STATUS[status] ?? { tone: "neutral" as Tone, label: status.toLowerCase() };
  return (
    <Badge
      variant="outline"
      data-tone={s.tone}
      className={cn("font-mono text-[10px] uppercase", TONE_BADGE[s.tone], className)}
    >
      {s.label}
    </Badge>
  );
}
