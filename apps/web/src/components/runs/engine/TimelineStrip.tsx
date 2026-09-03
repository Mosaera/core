/* The timeline strip (#63): the run's moments on one quiet line under the band.
   Deliberately subtle — the band carries the story, this carries the clock.
   Human moments are larger amber dots, detours amber-ringed, the live moment
   pulses, a dead run ends in a red stop. Hovering a dot reveals its label over
   a blurred backdrop; clicking selects the owning agent. */

import { cn } from "@/lib/utils";

import type { AgentId } from "../../../lib/engine";
import type { TimelineMoment } from "../../../lib/engineTimeline";

const DOT: Record<TimelineMoment["kind"], string> = {
  moment: "size-[9px] border-success/60",
  human: "size-[14px] border-amber-500",
  detour: "size-[11px] border-amber-500/80 bg-amber-500/20",
  now: "size-[13px] border-amber-500 bg-amber-500/25 animate-pulse",
  stop: "size-[13px] border-destructive bg-destructive/25",
};

const CAPTION_TONE = {
  live: "text-amber-600 dark:text-amber-400",
  ok: "text-success",
  stop: "text-destructive",
} as const;

const clock = (ts: number) =>
  new Date(ts).toLocaleTimeString(undefined, { hour12: false, hour: "2-digit", minute: "2-digit" });

export function TimelineStrip({
  moments,
  caption,
  onSelect,
}: {
  moments: TimelineMoment[];
  caption: { text: string; tone: "live" | "ok" | "stop" };
  onSelect: (id: AgentId) => void;
}) {
  if (moments.length === 0) return null;
  const first = moments[0].ts;
  const last = moments[moments.length - 1].ts;
  const span = Math.max(1, last - first);
  // Fill to the newest moment; a live run's track continues past it, unfilled.
  const fill = caption.tone === "live" ? 92 : 100;

  return (
    <div className="flex items-center gap-4 border-t border-border/60 py-3.5">
      <span className="font-mono text-[9.5px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/70">
        Timeline
      </span>
      <div className="relative h-6 flex-1" data-testid="timeline-track">
        <span className="absolute inset-x-0 top-[11px] h-0.5 rounded-full bg-foreground/10" />
        <span
          className={cn(
            "absolute left-0 top-[11px] h-0.5 rounded-full",
            caption.tone === "stop" ? "bg-destructive/40" : "bg-success/50",
          )}
          style={{ width: `${fill}%` }}
        />
        {moments.map((m, i) => (
          <button
            key={`${m.ts}-${i}`}
            type="button"
            onClick={() => onSelect(m.agent)}
            data-moment={m.kind}
            title={`${m.label} · ${clock(m.ts)}`}
            style={{ left: `${((m.ts - first) / span) * 96 + 2}%` }}
            // Explicit reset — index.css skips Preflight (see EngineBand).
            className="group absolute top-1/2 -translate-x-1/2 -translate-y-1/2 cursor-pointer border-0 bg-transparent p-0"
          >
            <span
              className={cn(
                "block rounded-full border-[2.5px] bg-background transition-transform group-hover:scale-125",
                DOT[m.kind],
              )}
            />
            <span className="pointer-events-none absolute bottom-5 left-1/2 hidden -translate-x-1/2 whitespace-nowrap rounded-md border border-foreground/15 bg-card/75 px-2.5 py-1 text-[10.5px] shadow-lg backdrop-blur-md group-hover:block">
              {m.label} · <span className="font-mono text-muted-foreground">{clock(m.ts)}</span>
            </span>
          </button>
        ))}
      </div>
      <span className={cn("whitespace-nowrap font-mono text-[10.5px] font-semibold", CAPTION_TONE[caption.tone])}>
        {caption.text}
      </span>
    </div>
  );
}
