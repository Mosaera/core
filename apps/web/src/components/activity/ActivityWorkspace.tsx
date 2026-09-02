import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { AgentAvatar } from "@/components/AgentAvatar";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { taskTitle } from "../../lib/runs";

import { api, type ActivityEvent, type Project } from "../../api/client";
import {
  ACTIVITY_FILTERS,
  describeEvent,
  runHeadline,
  type ActivityGroup,
  type ActivitySeverity,
  type DescribedEvent,
} from "../../lib/activity";
import { timeAgo } from "../../lib/overview";
import { historyRunHref } from "../../lib/runs";
import { EmptyNote } from "../overview/bits";
import { TONE_BADGE } from "../StatusBadge";

const DOT: Record<ActivitySeverity, string> = {
  green: "bg-success",
  amber: "bg-primary",
  red: "bg-destructive",
  muted: "bg-muted-foreground/40",
};

const PILL: Record<ActivitySeverity, string> = {
  green: TONE_BADGE.success,
  amber: TONE_BADGE.amber,
  red: TONE_BADGE.destructive,
  muted: TONE_BADGE.neutral,
};

// Content-sized, right-aligned metadata columns so status / count / time line up
// in tidy columns across every run row (mirrors the Changes list).
const ROW_COLS = "grid-cols-[1.25rem_minmax(0,1fr)_auto_auto_auto]";

type Described = ActivityEvent & { described: DescribedEvent };

/** The project's persisted audit trail — grouped by run so it reads as a
 *  scannable list of runs (collapsed by default), with search to jump straight
 *  to a specific event. Complements the Runs tab (one card per run); here every
 *  gate decision, node step, and MR event is its own row once expanded. */
export function ActivityWorkspace({ project }: { project: Project }) {
  const [filter, setFilter] = useState<"all" | ActivityGroup>("all");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());

  const { data, isLoading } = useQuery({
    queryKey: ["activity", project.id],
    queryFn: () => api.activity(project.id),
    refetchInterval: 5000,
  });

  const q = query.trim().toLowerCase();
  const searching = q.length > 0;

  const groups = useMemo(() => {
    const rows: Described[] = (data?.events ?? []).map((e) => ({
      ...e,
      described: describeEvent(e.event, e.detail),
    }));
    const matched = rows.filter(
      (e) =>
        (filter === "all" || e.described.group === filter) &&
        (!q ||
          `${e.task} ${e.described.actor} ${e.described.text} ${e.event} ${e.detail}`
            .toLowerCase()
            .includes(q)),
    );
    // Preserve newest-first order; group contiguous-or-not by run_id.
    const byRun: { runId: string; task: string; events: Described[] }[] = [];
    for (const e of matched) {
      let g = byRun.find((x) => x.runId === e.run_id);
      if (!g) {
        g = { runId: e.run_id, task: e.task, events: [] };
        byRun.push(g);
      }
      g.events.push(e);
    }
    return byRun;
  }, [data, filter, q]);

  function toggle(runId: string) {
    setOpen((prev) => {
      const next = new Set(prev);
      next.has(runId) ? next.delete(runId) : next.add(runId);
      return next;
    });
  }

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold tracking-tight">Activity</h1>
        <p className="max-w-2xl text-sm text-muted-foreground">
          The project's audit trail, grouped by run. Expand a run for its governed steps, or search
          to find a specific event.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-52 flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground/60" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search events…"
            aria-label="Search events"
            className="h-8 w-full rounded-md bg-card pl-8 pr-2 text-sm ring-1 ring-white/12 placeholder:text-muted-foreground/60 focus:outline-none focus:ring-primary/40"
          />
        </div>
        <div role="tablist" aria-label="Filter activity" className="flex flex-wrap gap-1">
          {ACTIVITY_FILTERS.map((f) => (
            <button
              key={f.id}
              role="tab"
              aria-selected={filter === f.id}
              onClick={() => setFilter(f.id)}
              className={cn(
                "rounded-md px-2.5 py-1 font-mono text-[11px] uppercase tracking-wide transition-colors",
                filter === f.id
                  ? "bg-primary/15 text-primary"
                  : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : groups.length === 0 ? (
        <EmptyNote>
          {searching ? "No events match your search." : "No activity recorded yet."}
        </EmptyNote>
      ) : (
        <ol className="flex flex-col">
          {groups.map((g) => {
            const head = runHeadline(g.events);
            const expanded = searching || open.has(g.runId);
            return (
              <li key={g.runId} className="border-b border-border/50 last:border-b-0">
                <button
                  onClick={() => toggle(g.runId)}
                  aria-expanded={expanded}
                  className={cn(
                    "grid w-full items-center gap-x-4 border-0 bg-transparent py-3 pr-1 text-left transition-colors hover:bg-muted/20",
                    ROW_COLS,
                  )}
                >
                  <ChevronRight
                    className={cn(
                      "size-3.5 shrink-0 text-muted-foreground/60 transition-transform",
                      expanded && "rotate-90",
                    )}
                  />
                  {/* The task's FIRST LINE is the item's title by construction (task_spec.py
                      weaves title + description + criteria); the whole paragraph as a row label
                      made six rows read as a wall (redundancy audit 2026-08-22). Search still
                      matches the full stored text — nothing became unfindable. */}
                  <span className="min-w-0 truncate text-sm font-medium">
                    {taskTitle(g.task)}
                    <span className="ml-2 font-mono text-[10px] font-normal text-muted-foreground/60">
                      {g.runId}
                    </span>
                  </span>
                  <span
                    className={cn(
                      "inline-block max-w-[9rem] justify-self-end truncate rounded-4xl px-2 py-0.5 font-mono text-[10px] uppercase leading-4",
                      PILL[head.severity],
                    )}
                  >
                    {head.label}
                  </span>
                  <span className="justify-self-end whitespace-nowrap font-mono text-[11px] text-muted-foreground/60">
                    {expanded ? "" : `${g.events.length} ${g.events.length === 1 ? "event" : "events"}`}
                  </span>
                  <span className="justify-self-end whitespace-nowrap font-mono text-[11px] text-muted-foreground/70">
                    {timeAgo(g.events[0].created_at ? new Date(g.events[0].created_at) : null)}
                  </span>
                </button>

                {expanded && (
                  <ol className="flex flex-col border-t border-border/50 py-1 pb-2">
                    {g.events.map((e, i) => (
                      <li key={i}>
                        <Link
                          to={historyRunHref(e.run_id, project.id)}
                          className="flex items-start gap-3 px-3 py-1.5 pl-9 transition-colors hover:bg-muted/30"
                        >
                          <span
                            className={cn("mt-1.5 size-1.5 shrink-0 rounded-full", DOT[e.described.severity])}
                            aria-hidden
                          />
                          {e.described.actor && (
                            <AgentAvatar actor={e.described.actor} size={20} className="mt-0.5" />
                          )}
                          <span className="min-w-0 flex-1 text-sm">
                            {e.described.actor && (
                              <span className="font-medium text-foreground">{e.described.actor} </span>
                            )}
                            <span className="text-foreground/80">{e.described.text}</span>
                          </span>
                          <span className="shrink-0 font-mono text-[11px] text-muted-foreground/70">
                            {timeAgo(e.created_at ? new Date(e.created_at) : null)}
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ol>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
