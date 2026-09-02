import { useQuery } from "@tanstack/react-query";
import { Bot, CircleDollarSign, GaugeCircle, ShieldCheck } from "lucide-react";

import { api, type RunMode } from "../../api/client";

/** When a human is asked to approve, by mode. Pure function of the selected
 *  mode — recomputes live as the user toggles ModeSelect above this card. */
const APPROVAL: Record<RunMode, string> = {
  guided: "You'll approve delivery (and each write gate).",
  autonomous:
    "May auto-deliver; parks for you if validation fails, the reviewer blocks, or security findings appear.",
  high_assurance: "You'll always approve delivery, even when evidence is clear.",
};

/** The agents any run activates (fixed by the graph: plan→PM, implement/fix→Coder,
 *  review→Reviewer). */
const AGENTS = ["PM", "Coder", "Reviewer"];

/** Pre-run summary on the backlog run sheet: which agents activate, when the
 *  human approves (by mode), and — now that cost-modes (#7) landed — a per-tier
 *  cost projection. The estimate is honest by construction: it prices this
 *  project's historical average per-role token load at the SELECTED mode's models
 *  (conditioned on the tier, not a blended average), and shows nothing until
 *  there's run history to project from. */
export function RunPreviewCard({
  mode,
  projectId,
  costMode,
}: {
  mode: RunMode;
  projectId: string;
  costMode: string;
}) {
  const { data: est } = useQuery({
    queryKey: ["estimate", projectId, costMode],
    queryFn: () => api.estimate(projectId, costMode),
  });
  return (
    <div className="flex w-full flex-col gap-2 rounded-lg bg-card p-3 ring-1 ring-white/12">
      <div className="flex items-center gap-2 font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
        <GaugeCircle className="size-3.5" />
        Run preview
      </div>

      {/* Agents that activate — fixed by the graph. */}
      <div className="flex items-center gap-1.5">
        <Bot className="size-3.5 shrink-0 text-muted-foreground/70" />
        <div className="flex flex-wrap gap-1">
          {AGENTS.map((a) => (
            <span
              key={a}
              className="rounded bg-foreground/[0.06] px-1.5 py-0.5 font-mono text-[11px] text-foreground/90"
            >
              {a}
            </span>
          ))}
        </div>
      </div>

      {/* Approval posture: pure function of the selected mode. */}
      <div className="flex items-start gap-1.5 border-t border-border/40 pt-2">
        <ShieldCheck className="mt-0.5 size-3.5 shrink-0 text-primary/80" />
        <p className="text-[11px] leading-relaxed text-muted-foreground">{APPROVAL[mode]}</p>
      </div>

      {/* Conditioned cost projection (#7): per-tier, from run history. */}
      <div className="flex items-start gap-1.5 border-t border-border/40 pt-2">
        <CircleDollarSign className="mt-0.5 size-3.5 shrink-0 text-muted-foreground/70" />
        {est?.available && est.projected_usd !== undefined ? (
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            <span className="capitalize text-foreground/90">{est.cost_mode}</span> · projected{" "}
            <span className="font-mono text-foreground/90">
              {est.projected_usd > 0 ? `~$${est.projected_usd.toFixed(4)}` : "$0 (local)"}
            </span>{" "}
            per run, from {est.runs_metered} past run{est.runs_metered === 1 ? "" : "s"}. Actual
            varies with task complexity and revisions.
          </p>
        ) : (
          <p className="text-[11px] leading-relaxed text-muted-foreground/60">
            No cost projection yet — needs run history for this project. Local models are free.
          </p>
        )}
      </div>
    </div>
  );
}
