/* The stage figure (theater v2.2, 2026-08-13): the selected agent as an OPEN engraving
   printed into the page — the same stencil technique as the marketing site's HowItWorks
   plates. The artwork ships as a greyscale LUMINANCE mask (parchment clipped to black,
   linework bright), painted here with a flat ink colour and intersected with a fade
   toward the page edge, so only ink is ever drawn — there is no paper, no card, no
   rectangle. One artwork serves any theme; the ink colour is ours to pick. */

import { Loader2, Pause } from "lucide-react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

import type { AgentState } from "../../../lib/engine";
import { ACTOR_AVATARS } from "../runActors";

function fmtWorked(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  if (h > 0) return `${h}h ${m % 60}m`;
  return m > 0 ? `${m}m ${s % 60}s` : `${s}s`;
}

/** Ticks each second so a live worked-time counts up. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  return now;
}

/** The ONE in-progress indicator (owner cut, 2026-08-13): an animated spinner while the
 *  agent works, a pause mark while an interrupt waits on the operator — never a pill,
 *  never "working" over an open gate. */
function StatusMark({
  status,
  paused,
}: {
  status: AgentState["status"];
  paused: boolean;
}) {
  if (status === "current" && paused)
    return (
      <span className="flex items-center gap-1.5 font-mono text-[10.5px] text-primary" title="An approval is waiting on you">
        <Pause className="size-3.5" aria-hidden />
        paused
      </span>
    );
  if (status === "current")
    return (
      <span className="flex items-center gap-1.5 font-mono text-[10.5px] text-primary">
        <Loader2 className="size-3.5 animate-spin" aria-hidden />
        working
      </span>
    );
  if (status === "done")
    return <span className="font-mono text-[10.5px] text-success">✓ done</span>;
  if (status === "dead")
    return <span className="font-mono text-[10.5px] text-destructive">✕ stopped</span>;
  if (status === "disabled")
    return <span className="font-mono text-[10.5px] text-muted-foreground/60">off</span>;
  return <span className="font-mono text-[10.5px] text-muted-foreground/60">not started</span>;
}

/* Warm parchment ink on the near-black canvas — the marketing site's dark-mode plate
   colour, so the product and the site read as one printing. */
const INK = "#e6d0ab";
const FADE = "linear-gradient(to right, transparent 2%, rgba(0,0,0,0.4) 22%, #000 60%)";

// Preload every stencil once: a portrait's first mount (Justice at the gate) must
// never race the network — an unloaded mask paints nondeterministically in Chromium.
if (typeof window !== "undefined") {
  for (const src of Object.values(ACTOR_AVATARS)) new Image().src = src;
}

export function PortraitCard({
  agent,
  interruptOpen = false,
  workedSpan,
  className,
}: {
  agent: AgentState;
  /** Any open interrupt (write gate or park): the run is paused, not working. */
  interruptOpen?: boolean;
  /** First/last event ts of this agent's own work (engine.agentSpan). */
  workedSpan?: { first: number; last: number } | null;
  className?: string;
}) {
  const art = ACTOR_AVATARS[agent.name];
  const live = agent.status === "current";
  const now = useNow(live && !interruptOpen);
  const workedMs = workedSpan ? (live ? Math.max(now, workedSpan.last) : workedSpan.last) - workedSpan.first : null;
  return (
    <figure data-portrait={agent.id} className={cn("flex h-full min-h-0 flex-col gap-2", className)}>
      {art ? (
        <div
          aria-hidden
          className={cn(
            "min-h-0 w-full flex-1 transition-opacity",
            agent.status === "current" && "opacity-90",
            agent.status === "done" && "opacity-70",
            agent.status === "dead" && "opacity-60",
            agent.status === "pending" && "opacity-30",
            agent.status === "disabled" && "opacity-20",
          )}
          style={{
            // OUTER: the alpha fade toward the page edge. INNER: the luminance
            // stencil. One mask per element — no multi-layer composite, no race.
            WebkitMaskImage: FADE,
            maskImage: FADE,
          }}
        >
          <div
            className="size-full"
            style={{
              backgroundColor: INK,
              WebkitMaskImage: `url(${art})`,
              maskImage: `url(${art})`,
              maskMode: "luminance",
              WebkitMaskSize: "contain",
              maskSize: "contain",
              WebkitMaskRepeat: "no-repeat",
              maskRepeat: "no-repeat",
              WebkitMaskPosition: "center",
              maskPosition: "center",
            }}
          />
        </div>
      ) : (
        <div className="flex min-h-0 w-full flex-1 items-center justify-center font-mono text-4xl font-bold text-muted-foreground/30">
          {agent.name.replace(/^The /, "").charAt(0)}
        </div>
      )}
      <figcaption className="flex flex-col gap-1 px-1">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate font-mono text-[13px] font-semibold uppercase tracking-[0.08em]">
            {agent.name}
          </span>
          <StatusMark status={agent.status} paused={interruptOpen} />
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-[12px] leading-snug text-muted-foreground">{agent.role}</span>
          {workedMs != null && workedMs > 0 && (
            <span
              className="shrink-0 font-mono text-[10.5px] tabular-nums text-muted-foreground/70"
              title="Time this agent worked"
            >
              {fmtWorked(workedMs)}
            </span>
          )}
        </div>
        {agent.status !== "current" && (
          <span className="font-mono text-[11px] leading-snug text-muted-foreground/70">
            {agent.caption}
          </span>
        )}
      </figcaption>
    </figure>
  );
}
