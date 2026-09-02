/* The steps rail (theater v2, 2026-08-13): the run as a checklist of stages, not a
   node graph. One chip per roster seat — done ✓ / working ● / pending dim / stopped ✕ —
   and each chip is ALSO the switcher: click any seat to view its record. */

import { cn } from "@/lib/utils";

import type { AgentId, AgentState } from "../../../lib/engine";

const STEP_LABEL: Record<AgentId, string> = {
  quincy: "Plan",
  architect: "Design",
  proctor: "Tests",
  forge: "Build",
  vera: "Checks",
  rook: "Review",
  critic: "Critic",
  you: "Gate",
  drift: "Deliver",
};

function Mark({ status }: { status: AgentState["status"] }) {
  // Fixed box + leading-none: the glyphs' own metrics differ, so they center
  // optically against the 13px label instead of riding the baseline.
  const box = "flex size-[14px] shrink-0 items-center justify-center leading-none";
  if (status === "done")
    return <span className={`${box} text-[12px] font-extrabold text-success`}>✓</span>;
  if (status === "current")
    return <span className={`${box} animate-pulse text-[9px] text-primary`}>●</span>;
  if (status === "dead")
    return <span className={`${box} text-[12px] font-extrabold text-destructive`}>✕</span>;
  return <span className={`${box} text-[9px] text-muted-foreground/40`}>○</span>;
}

export function StepsRail({
  agents,
  selected,
  onSelect,
}: {
  agents: AgentState[];
  selected: AgentId | null;
  onSelect: (id: AgentId) => void;
}) {
  return (
    <ol
      aria-label="Run stages"
      className="flex w-full flex-wrap items-center gap-1.5 border-b border-white/12 py-3.5 sm:justify-between"
    >
      {/* The Gate is not a STAGE — it is the human moment, told by the hero. Keeping it
          here made the marker jump to the end at every mid-run write approval. */}
      {agents
        .filter((a) => a.status !== "disabled" && a.id !== "you")
        .map((a) => (
          <li key={a.id}>
            <button
              type="button"
              data-step={a.id}
              data-status={a.status}
              aria-pressed={selected === a.id}
              onClick={() => onSelect(a.id)}
              className={cn(
                "flex cursor-pointer items-center gap-2 rounded-full border px-3.5 py-1.5 font-mono text-[13px] leading-none tracking-[0.04em] transition-colors",
                selected === a.id
                  ? "border-white/25 bg-white/10 text-foreground"
                  : "border-white/10 bg-white/4 text-muted-foreground hover:border-white/20 hover:bg-white/10 hover:text-foreground",
                // A completed stage keeps its green edge — the story reads at a glance.
                a.status === "done" && selected !== a.id && "border-success/25",
                a.status === "pending" && "opacity-60",
              )}
              title={`${a.name} — ${a.caption}`}
            >
              <Mark status={a.status} />
              {STEP_LABEL[a.id]}
            </button>
          </li>
        ))}
    </ol>
  );
}
