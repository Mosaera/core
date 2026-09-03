import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { AgentAvatar } from "@/components/AgentAvatar";
import { cn } from "@/lib/utils";

import { ConsoleLabel } from "./overview/bits";

// This widget predates the named personas and still labels its lanes by role.
// Map each lane to the persona that actually does that work, so the headshots
// here agree with the run timeline (Delivery → Drift, who has no art yet and so
// falls back to a monogram).
const LANE_PERSONA: Record<string, string> = {
  PM: "The Chart-Maker",
  Coder: "The Smith",
  Reviewer: "The Tribune",
  Delivery: "Mercury",
};

// Graph phase → which agent lane it belongs to + the activity label.
const PHASE: Record<string, { lane: string; label: string }> = {
  plan: { lane: "PM", label: "planning" },
  implement: { lane: "Coder", label: "coding" },
  capture: { lane: "Coder", label: "summarizing" },
  test: { lane: "Coder", label: "running tests" },
  scan: { lane: "Reviewer", label: "security scan" },
  review: { lane: "Reviewer", label: "reviewing" },
  gate: { lane: "Delivery", label: "awaiting approval" },
  deliver: { lane: "Delivery", label: "committing" },
};
const LANES = ["PM", "Coder", "Reviewer", "Delivery"];
const LANE_ORDER: Record<string, number> = { PM: 0, Coder: 1, Reviewer: 2, Delivery: 3 };

function fmt(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const m = Math.floor(s / 60);
  return m > 0 ? `${m}m ${s % 60}s` : `${s}s`;
}

/** The house working indicator (replaces the legacy CSS .spinner everywhere). */
export function Spinner({ className }: { className?: string }) {
  return <Loader2 aria-hidden className={cn("size-3.5 shrink-0 animate-spin text-primary", className)} />;
}

/** Ticks every second so elapsed timers update live; `since` is unix seconds. */
function useElapsed(since: number | null): number {
  const [, tick] = useState(0);
  useEffect(() => {
    if (since == null) return;
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [since]);
  return since == null ? 0 : Date.now() / 1000 - since;
}

export function AgentStatus({
  phase,
  startedAt,
  status,
  compact = false,
}: {
  phase: string;
  startedAt: number | null;
  status: string;
  compact?: boolean;
}) {
  const running = status === "running" || status === "awaiting_approval";
  const total = useElapsed(running ? startedAt : null);
  // Reset the per-phase timer whenever the phase changes.
  const [phaseStart, setPhaseStart] = useState<number | null>(startedAt);
  useEffect(() => {
    setPhaseStart(Date.now() / 1000);
  }, [phase]);
  const inPhase = useElapsed(running ? phaseStart : null);

  const active = PHASE[phase];
  const activeLane = active?.lane ?? "";

  if (compact) {
    if (!running) return null;
    return (
      <span className="mt-2 inline-flex items-center gap-1.5 font-mono text-[11.5px] text-primary">
        <Spinner className="size-3" />
        {activeLane || "starting"}
        {active ? ` · ${active.label}` : ""} · {fmt(inPhase)}
      </span>
    );
  }

  return (
    <div>
      <div className="mb-3 flex items-center">
        <ConsoleLabel>agents</ConsoleLabel>
        <div className="flex-1" />
        {running && (
          <span className="font-mono text-xs text-muted-foreground">elapsed {fmt(total)}</span>
        )}
      </div>
      {LANES.map((lane) => {
        let state: "idle" | "active" | "done" = "idle";
        if (running && lane === activeLane) state = "active";
        else if (activeLane && LANE_ORDER[lane] < (LANE_ORDER[activeLane] ?? -1)) state = "done";
        else if (!running && status !== "error") state = "done";
        return (
          <div
            key={lane}
            data-state={state}
            className={cn(
              "grid grid-cols-[22px_24px_90px_1fr_auto] items-center gap-2.5 border-t border-border py-2 text-[13px] first:border-t-0",
              state === "idle" && "opacity-40",
            )}
          >
            <span className="flex justify-center">
              {state === "active" ? (
                <Spinner />
              ) : (
                <span
                  className={cn(
                    "size-1.5 rounded-full",
                    state === "done" ? "bg-success" : "bg-muted-foreground/50",
                  )}
                />
              )}
            </span>
            <span className="flex justify-center">
              <AgentAvatar actor={LANE_PERSONA[lane] ?? lane} size={22} />
            </span>
            <span className={cn("font-semibold", state === "active" && "text-primary")}>{lane}</span>
            <span className="font-mono text-xs text-muted-foreground">
              {state === "active" ? (active?.label ?? "working") : state}
            </span>
            <span className="font-mono text-xs text-primary">
              {state === "active" ? fmt(inPhase) : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}
