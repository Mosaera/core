/* The engine band (#63): the run's agent team, evenly spread full-width, with
   edges measured from the live avatar positions and routed by edgeRouter. The
   band IS the run — nodes and edges render the derived state, never a fixed
   diagram: a loop lane exists only because that loop actually ran.

   Exactly one edge animates (the one the run is traversing) and only while live;
   sealed runs and prefers-reduced-motion render fully static. */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { AgentAvatar } from "@/components/AgentAvatar";
import { cn } from "@/lib/utils";

import type { AgentId, AgentState, EngineEdge } from "../../../lib/engine";
import { routeEdges, type EdgeLayout, type NodeBox } from "./edgeRouter";

const RING: Record<AgentState["status"], string> = {
  done: "border-success/55",
  current: "border-amber-500",
  dead: "border-destructive/70",
  pending: "border-border opacity-45",
  // Present but switched off: dimmer than pending and dashed, so "will never run" reads
  // differently from "not yet reached" at a glance.
  disabled: "border-dashed border-border opacity-25",
};

const EDGE_STROKE = {
  traversed: "stroke-success/45",
  current: "stroke-amber-500/70",
  unreached: "stroke-foreground/10 [stroke-dasharray:4_5]",
  dead: "stroke-destructive/60",
} as const;

const ARROW_FILL = {
  traversed: "fill-foreground/25",
  current: "fill-amber-500/80",
  unreached: "fill-foreground/15",
  dead: "fill-destructive/70",
} as const;

function StatusMark({ status }: { status: AgentState["status"] }) {
  if (status === "done")
    return (
      <span
        aria-hidden
        className="absolute -bottom-px -right-px flex size-[19px] items-center justify-center rounded-full border-[2.5px] border-background bg-success text-[11px] font-extrabold leading-none text-background"
      >
        ✓
      </span>
    );
  if (status === "dead")
    return (
      <span
        aria-hidden
        className="absolute -bottom-px -right-px flex size-[19px] items-center justify-center rounded-full border-[2.5px] border-background bg-destructive text-[11px] font-extrabold leading-none text-white"
      >
        ✕
      </span>
    );
  if (status === "current")
    return (
      <span
        aria-hidden
        data-live-dot
        className="absolute bottom-0 right-0 size-[15px] animate-pulse rounded-full border-[2.5px] border-background bg-amber-500"
      />
    );
  return null;
}

function AgentNode({
  agent,
  selected,
  onSelect,
  nodeRef,
}: {
  agent: AgentState;
  selected: boolean;
  onSelect: () => void;
  nodeRef: (el: HTMLSpanElement | null) => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      data-agent={agent.id}
      data-status={agent.status}
      aria-pressed={selected}
      // Explicit reset: index.css skips Tailwind Preflight, so the legacy stylesheet
      // would otherwise paint every <button> grey with a square border.
      className="flex w-[110px] shrink-0 cursor-pointer flex-col items-center gap-2 border-0 bg-transparent p-0 text-center"
    >
      <span
        ref={nodeRef}
        data-node={agent.id}
        className={cn(
          "relative flex size-[66px] items-center justify-center rounded-full border-2 bg-muted transition-colors",
          RING[agent.status],
          agent.id === "you" && "border-dashed",
          selected && "ring-[3px] ring-foreground/20",
        )}
      >
        {agent.id === "you" ? (
          <span className="font-mono text-[11px] font-semibold tracking-wide text-amber-500">
            YOU
          </span>
        ) : (
          <AgentAvatar actor={agent.name} size={62} />
        )}
        <StatusMark status={agent.status} />
      </span>
      <span className="text-[13.5px] font-semibold leading-none">{agent.name}</span>
      <span
        className={cn(
          "-mt-1 text-[11px] leading-tight",
          agent.status === "current"
            ? "text-amber-600 dark:text-amber-400"
            : agent.status === "dead"
              ? "text-destructive"
              : "text-muted-foreground",
        )}
      >
        {agent.caption}
      </span>
    </button>
  );
}

/** Measured SVG layer: forward wires along the row, send-back lanes above it. */
function Edges({ layout, animate }: { layout: EdgeLayout; animate: boolean }) {
  return (
    <svg
      aria-hidden
      className="pointer-events-none absolute inset-0 size-full overflow-visible"
      data-testid="engine-edges"
    >
      {layout.forward.map((e) => (
        <g key={`f-${e.from}-${e.to}`} data-edge={`${e.from}->${e.to}`} data-state={e.state}>
          <path
            d={`M${e.x1} ${e.y} H${e.x2}`}
            className={cn("fill-none [stroke-width:1.6]", EDGE_STROKE[e.state])}
          />
          {animate && e.state === "current" && (
            <circle r="2.4" className="fill-amber-500">
              <animateMotion dur="1.6s" repeatCount="indefinite" path={`M${e.x1} ${e.y} H${e.x2}`} />
            </circle>
          )}
        </g>
      ))}
      {layout.back.map((e) => (
        <g key={`b-${e.from}-${e.to}`} data-edge={`${e.from}->${e.to}`} data-state={e.state}>
          <path d={e.path} className={cn("fill-none [stroke-width:1.6]", EDGE_STROKE[e.state])} />
          <path d={e.arrow} className={ARROW_FILL[e.state]} />
          {animate && e.state === "current" && (
            <circle r="2.4" className="fill-amber-500">
              <animateMotion dur="2.2s" repeatCount="indefinite" path={e.path} />
            </circle>
          )}
        </g>
      ))}
    </svg>
  );
}

export function EngineBand({
  agents,
  edges,
  selected,
  onSelect,
  live = false,
}: {
  agents: AgentState[];
  edges: EngineEdge[];
  selected: AgentId;
  onSelect: (id: AgentId) => void;
  live?: boolean;
}) {
  const rowRef = useRef<HTMLDivElement | null>(null);
  const nodeEls = useRef(new Map<AgentId, HTMLSpanElement>());
  const [layout, setLayout] = useState<EdgeLayout>({ forward: [], back: [], laneHeight: 0 });

  const measure = useCallback(() => {
    const row = rowRef.current;
    if (!row) return;
    const rr = row.getBoundingClientRect();
    const boxes: NodeBox[] = [];
    for (const a of agents) {
      const el = nodeEls.current.get(a.id);
      if (!el) continue;
      const b = el.getBoundingClientRect();
      if (b.width === 0) continue; // jsdom / not yet laid out
      boxes.push({
        id: a.id,
        cx: b.left - rr.left + b.width / 2,
        cy: b.top - rr.top + b.height / 2,
        r: b.width / 2,
        top: b.top - rr.top,
      });
    }
    setLayout(routeEdges(boxes, edges));
  }, [agents, edges]);

  useLayoutEffect(measure, [measure]);
  useEffect(() => {
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    if (rowRef.current) ro.observe(rowRef.current);
    return () => ro.disconnect();
  }, [measure]);

  const reduced =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  return (
    // overflow-x-auto also clips vertically, so the selection/pulse ring needs
    // real headroom of its own — never zero, even when there are no lanes.
    <nav aria-label="Run agents" className="overflow-x-auto">
      <div
        className="relative min-w-[860px] pb-1"
        style={{ paddingTop: (layout.laneHeight || 0) + 10 }}
      >
        <div ref={rowRef} className="relative flex items-start justify-between">
          <Edges layout={layout} animate={live && !reduced} />
          {agents.map((a) => (
            <AgentNode
              key={a.id}
              agent={a}
              selected={selected === a.id}
              onSelect={() => onSelect(a.id)}
              nodeRef={(el) => {
                if (el) nodeEls.current.set(a.id, el);
                else nodeEls.current.delete(a.id);
              }}
            />
          ))}
        </div>
        {layout.back.map((e) => (
          <span
            key={`badge-${e.from}-${e.to}`}
            data-badge={`${e.from}->${e.to}`}
            style={{ left: e.badge.x, top: e.badge.y + (layout.laneHeight ? layout.laneHeight + 8 : 0) }}
            className={cn(
              "pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded-full border px-2.5 py-[3px] font-mono text-[10px] font-semibold backdrop-blur-sm",
              e.state === "dead"
                ? "border-destructive/40 bg-destructive/10 text-destructive"
                : e.state === "current"
                  ? "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400"
                  : "border-border bg-card/80 text-muted-foreground",
            )}
          >
            {e.badge.label}
          </span>
        ))}
      </div>
    </nav>
  );
}
