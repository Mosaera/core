import { Lock, SquareCheck } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { ActiveRun, BacklogItem, HistoryRun } from "../../api/client";
import { AgentStatus } from "../AgentStatus";
import { severityBadge, TONE_BADGE } from "../StatusBadge";
import { acceptanceCriteria, ITEM_BADGE, isBlocked, isLocked } from "../../lib/backlog";
import { historyRunHref, liveRunHref } from "../../lib/runs";
import { OUTCOME_META, runOutcome } from "../../lib/validation";

export function ItemStatusBadge({ status, className }: { status: string; className?: string }) {
  const meta = ITEM_BADGE[status] ?? { label: status, severity: "neutral" as const };
  return (
    <Badge className={cn("h-4 px-1.5 font-mono text-[10px] uppercase", severityBadge(meta.severity), className)}>
      {meta.label}
    </Badge>
  );
}

function shortDate(at: string | null): string | null {
  if (!at) return null;
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** One backlog item on the board. The whole card opens the detail drawer;
 *  inline actions (run, reset, links) stop propagation. Every field shown is a
 *  real API field — nothing synthesized. */
export function BacklogCard({
  item,
  activeRun,
  latestRun,
  anyRunning,
  runBusy,
  onOpen,
  onRun,
  onReset,
}: {
  item: BacklogItem;
  activeRun?: ActiveRun;
  latestRun?: HistoryRun;
  anyRunning: boolean;
  runBusy: boolean;
  onOpen: (item: BacklogItem) => void;
  onRun: (item: BacklogItem) => void;
  onReset: (item: BacklogItem) => void;
}) {
  const live = item.status === "in_progress" && activeRun && activeRun.item_id === item.id;
  const criteria = acceptanceCriteria(item.acceptance);
  const created = shortDate(item.created_at);
  const blocked = isBlocked(item);
  const locked = isLocked(item);
  const runDisabled = anyRunning || Boolean(activeRun) || runBusy || blocked || locked;
  const runTitle = blocked
    ? `blocked — waiting on ${item.blocked_by?.length} item(s) to be delivered`
    : locked
      ? item.lock_reason
        ? `locked — ${item.lock_reason}`
        : "locked — open the item to unlock or run anyway"
      : runDisabled
        ? "another item is running on this project"
        : // Say the posture out loud. This button always starts a GUIDED run, while the
          // toolbar's "Autonomous on" chip sits inches away governing only the sweep — so on
          // 2026-08-06 an operator turned autonomy on, pressed Run, and got a guided run that
          // had to be cancelled. Open the item to choose a different mode.
          "Run guided — you approve every write and the delivery. Open the item for other modes.";

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`Open details for ${item.title}`}
      onClick={() => onOpen(item)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen(item);
        }
      }}
      className={cn(
        "flex cursor-pointer flex-col gap-2 rounded-lg bg-card p-3 text-left ring-1 transition-[box-shadow,background-color] hover:bg-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
        item.status === "in_review"
          ? "ring-primary/40 hover:ring-primary/60"
          : "ring-white/12 hover:ring-foreground/20",
      )}
    >
      <div className="text-sm font-medium leading-snug">{item.title}</div>
      {item.description && (
        /* One line: the card's job is identity + state; BacklogItemSheet holds the full
           description on click (redundancy audit 2026-08-22 — "title + first line"). */
        <p className="line-clamp-1 text-xs leading-relaxed text-muted-foreground">
          {item.description}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <ItemStatusBadge status={item.status} />
        {blocked && (
          <Badge
            className={cn(
              "h-4 gap-1 px-1.5 font-mono text-[10px] uppercase",
              TONE_BADGE.destructive,
            )}
          >
            <Lock className="size-2.5 shrink-0" />
            Blocked · {item.blocked_by?.length}
          </Badge>
        )}
        {locked && (
          <Badge
            className={cn(
              "h-4 gap-1 px-1.5 font-mono text-[10px] uppercase",
              TONE_BADGE.amber,
            )}
            title={item.lock_reason || undefined}
          >
            <Lock className="size-2.5 shrink-0" />
            Locked
          </Badge>
        )}
        {criteria.length > 0 && (
          <span className="flex items-center gap-1 font-mono text-[10px] text-muted-foreground">
            <SquareCheck className="size-3 shrink-0" />
            {criteria.length} criteria
          </span>
        )}
        {item.clarification && (
          <Badge
            className={cn("h-4 gap-1 px-1.5 font-mono text-[10px] uppercase", TONE_BADGE.amber)}
            title={`Quincy asked: ${item.clarification.claim_text}`}
          >
            Question open
          </Badge>
        )}
        {!item.clarification && item.checkability === "UNDER_SPECIFIED" && (
          <Badge
            className={cn("h-4 gap-1 px-1.5 font-mono text-[10px] uppercase", TONE_BADGE.amber)}
            title="No material acceptance claim can be checked as written — clarify before running."
          >
            Needs clarifying
          </Badge>
        )}
        {!item.clarification && item.decidability === "UNDECIDABLE" && (
          <Badge
            className={cn("h-4 gap-1 px-1.5 font-mono text-[10px] uppercase", TONE_BADGE.amber)}
            title="A check can bind to this acceptance, but the text doesn't fix one answer — two readers would build two different things. Pin the rule before running."
          >
            One answer?
          </Badge>
        )}
        {/* The THIRD intake axis (F76, #78). The server has computed and served `reachability`
            since it shipped, and the SPA never rendered it — so "the engine cannot do this work"
            was discoverable only as a 409 at launch, after the operator had committed to running
            it. Item 88 cost five runs and ~2.9M tokens to that exact silence. */}
        {item.reachability === "UNREACHABLE" && (
          <Badge
            className={cn("h-4 gap-1 px-1.5 font-mono text-[10px] uppercase", TONE_BADGE.amber)}
            title="This acceptance asks for work the delivery agent has no tool for, so no run can satisfy it. Re-scope it, or do that part by hand."
          >
            Can't be built
          </Badge>
        )}
        {item.status !== "todo" && item.compliant === false && (
          <Badge
            className={cn("h-4 gap-1 px-1.5 font-mono text-[10px] uppercase", TONE_BADGE.neutral)}
            title={`This item's acceptance would not pass today's intake bar (${(
              item.compliance_reasons ?? []
            ).join("; ")}). It says the work was gated on weaker evidence than we now accept — not that the delivered code is wrong.`}
          >
            Pre-standard
          </Badge>
        )}
        {item.checkability === "CHECKABLE" && (item.claims?.length ?? 0) > 0 && (
          <span
            className="font-mono text-[10px] text-muted-foreground"
            title="Every material acceptance claim has a bound check."
          >
            {item.claims?.filter((c) => c.material && c.oracle_kind !== "none").length} claims
            bound
          </span>
        )}
        {created && (
          <span className="font-mono text-[10px] text-muted-foreground/60">{created}</span>
        )}
      </div>

      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center">
          {live && (
            <Link
              to={liveRunHref(activeRun.run_id, activeRun.project_id)}
              onClick={(e) => e.stopPropagation()}
              className="min-w-0"
            >
              <AgentStatus
                phase={activeRun.phase ?? ""}
                startedAt={activeRun.started_at ?? null}
                status="running"
                compact
              />
            </Link>
          )}
          {item.status === "in_progress" && !live && (
            /* Recover an item stuck in_progress with no live run (orphaned run). */
            <Button
              size="xs"
              variant="ghost"
              className="text-muted-foreground"
              onClick={(e) => {
                e.stopPropagation();
                onReset(item);
              }}
            >
              Reset to todo
            </Button>
          )}
          {(item.status === "in_review" || item.status === "done") && latestRun && (
            <Link
              to={historyRunHref(latestRun.id, latestRun.project_id)}
              onClick={(e) => e.stopPropagation()}
              className="truncate font-mono text-[10px] text-muted-foreground hover:text-foreground"
            >
              latest run · {OUTCOME_META[runOutcome(latestRun)].label.toLowerCase()} ↗
            </Link>
          )}
        </span>

        {item.status === "todo" && (
          <Button
            size="xs"
            disabled={runDisabled}
            title={runTitle}
            onClick={(e) => {
              e.stopPropagation();
              onRun(item);
            }}
          >
            Run guided ▸
          </Button>
        )}
        {item.status === "in_review" && (
          <Button
            size="xs"
            onClick={(e) => {
              e.stopPropagation();
              onOpen(item);
            }}
          >
            Review
          </Button>
        )}
        {item.status === "done" && (
          <Button
            size="xs"
            variant="ghost"
            className="text-muted-foreground"
            onClick={(e) => {
              e.stopPropagation();
              onOpen(item);
            }}
          >
            View result
          </Button>
        )}
      </div>
    </div>
  );
}
