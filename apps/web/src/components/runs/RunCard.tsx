import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { ActiveRun, BacklogItem, HistoryRun } from "../../api/client";
import { runCardBadge } from "../../lib/changes";
import { taskTitle } from "../../lib/runs";
import { historyRunHref, liveRunHref } from "../../lib/runs";
import { AgentStatus } from "../AgentStatus";
import { severityBadge } from "../StatusBadge";

function shortDate(at: string | null): string | null {
  if (!at) return null;
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** One run on the execution board. Selecting a card drives the detail panel;
 *  the badge carries the generic safe wording — validation is refined only by
 *  the panel's fetched evidence, never by this card. */
export function RunCard({
  run,
  backlogItem,
  activeRun,
  latest,
  selected,
  muted = false,
  hideTask = false,
  hideBadge = false,
  onSelect,
  onCancel,
}: {
  run: HistoryRun;
  backlogItem?: BacklogItem;
  activeRun?: ActiveRun;
  latest: boolean;
  selected: boolean;
  /** Historical presentation on merged projects. */
  muted?: boolean;
  /** ItemCard context: the item header directly above already names this work — repeating the
   *  title here was the one duplication the consolidation ADDED (owner caught it in the
   *  after-screenshots). The meta row and termination line stay. The item header also owns
   *  `#id · title`, so ItemCard omits `backlogItem` — one identity render per group. */
  hideTask?: boolean;
  /** Latest-attempt card under an item header: the header's outcome badge ("Parked") and this
   *  card's status badge ("Incomplete") are one fact in two vocabularies — the header owns it.
   *  Prior-attempt rows keep their badges (the only render there). */
  hideBadge?: boolean;
  onSelect: (run: HistoryRun) => void;
  onCancel: (runId: string) => void;
}) {
  const badge = runCardBadge(run);
  const live = run.status === "RUNNING" && activeRun && activeRun.run_id === run.id;
  const created = shortDate(run.created_at);
  const needsEyes = badge.tone === "red";

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`Select run ${taskTitle(run.task)}`}
      aria-pressed={selected}
      onClick={() => onSelect(run)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(run);
        }
      }}
      className={cn(
        "flex cursor-pointer flex-col gap-2 rounded-lg bg-card p-3 text-left ring-1 transition-[box-shadow,background-color] hover:bg-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
        selected
          ? "ring-primary/50 hover:ring-primary/60"
          : needsEyes && !muted
            ? "ring-destructive/30 hover:ring-destructive/50"
            : "ring-white/12 hover:ring-foreground/20",
        muted && "opacity-75",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        {!hideTask && (
          <span className="min-w-0 flex-1 truncate text-sm font-medium leading-snug">
            {taskTitle(run.task)}
          </span>
        )}
        <span className="flex shrink-0 items-center gap-1.5">
          {latest && (
            <Badge className={cn("font-mono text-[10px] uppercase", severityBadge("neutral"))}>
              Latest
            </Badge>
          )}
          {!hideBadge && (
            <Badge className={cn("font-mono text-[10px] uppercase", severityBadge(badge.tone))}>
              {badge.label}
            </Badge>
          )}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[10px] text-muted-foreground">
        <Link
          to={historyRunHref(run.id, run.project_id)}
          onClick={(e) => e.stopPropagation()}
          className="hover:text-foreground"
        >
          {run.id}
        </Link>
        {created && <span className="text-muted-foreground/60">{created}</span>}
        {run.commit_sha && (
          <span className="text-muted-foreground/60">{run.commit_sha.slice(0, 8)}</span>
        )}
        {run.branch && <span className="truncate text-muted-foreground/60">{run.branch}</span>}
        {backlogItem && (
          <span className="truncate text-muted-foreground/80">
            #{backlogItem.id} · {backlogItem.title}
          </span>
        )}
      </div>

      {/* Honest non-delivery: an incomplete run says WHY it didn't deliver (ADR-0006), so the
          amber badge isn't a mystery. Recorded by the API — surfaced, never recomputed here. */}
      {run.status === "INCOMPLETE" && run.termination_reason && (
        <p className="text-[11px] leading-snug text-amber-600 dark:text-amber-400">
          Ended without delivering — {run.termination_reason}
        </p>
      )}

      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center">
          {live && (
            <Link
              to={liveRunHref(activeRun.run_id, activeRun.project_id)}
              onClick={(e) => e.stopPropagation()}
            >
              <AgentStatus
                phase={activeRun.phase ?? ""}
                startedAt={activeRun.started_at ?? null}
                status="running"
                compact
              />
            </Link>
          )}
        </span>
        <span className="flex items-center gap-2">
          {run.status === "RUNNING" ? (
            <>
              <Button
                size="xs"
                variant="destructive"
                onClick={(e) => {
                  e.stopPropagation();
                  onCancel(run.id);
                }}
              >
                Cancel
              </Button>
              <Button
                size="xs"
                variant="secondary"
                onClick={(e) => e.stopPropagation()}
                nativeButton={false}
                render={
                  <Link
                    to={
                      live
                        ? liveRunHref(activeRun.run_id, activeRun.project_id)
                        : historyRunHref(run.id, run.project_id)
                    }
                  />
                }
              >
                View run ▸
              </Button>
            </>
          ) : (
            <Button
              size="xs"
              variant={needsEyes && !muted ? "default" : "ghost"}
              className={needsEyes && !muted ? undefined : "text-muted-foreground"}
              onClick={(e) => {
                e.stopPropagation();
                onSelect(run);
              }}
            >
              {needsEyes && !muted
                ? "Inspect run ▸"
                : run.status === "APPROVED"
                  ? "View run details"
                  : "Details"}
            </Button>
          )}
        </span>
      </div>
    </div>
  );
}
