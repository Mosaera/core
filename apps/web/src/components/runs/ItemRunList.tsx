/* The item-consolidated run list — one card per backlog item, its latest attempt as its state,
 * prior attempts collapsed behind "attempt N of N". Replaces RunGroups' per-attempt sections:
 * seven incomplete attempts of one item are ONE line with a pattern, which is a stronger signal
 * than seven rows (the Firehose Audit's exhibit A).
 *
 * ADR-0107: an item carrying an OPEN clarification shows the ask badge here — the grouped view
 * must never tidy an unanswered question out of sight. */

import type { ActiveRun, HistoryRun } from "../../api/client";
import { cn } from "../../lib/utils";
import { OUTCOME_META } from "../../lib/validation";
import type { ItemGroup } from "../../lib/itemRuns";
import { Badge } from "../ui/badge";
import { TONE_BADGE } from "../StatusBadge";
import { taskTitle } from "../../lib/runs";
import { ConsoleLabel, SeverityDot } from "../overview/bits";
import { RunCard } from "./RunCard";

const SEV_TONE = { green: TONE_BADGE.success, amber: TONE_BADGE.amber, red: TONE_BADGE.destructive };

function ItemCard({
  group,
  activeRun,
  latestId,
  selectedId,
  onSelect,
  onCancel,
}: {
  group: ItemGroup;
  activeRun?: ActiveRun;
  latestId?: string;
  selectedId?: string;
  onSelect: (run: HistoryRun) => void;
  onCancel: (runId: string) => void;
}) {
  const meta = OUTCOME_META[group.outcome];
  const openAsk = group.item?.clarification?.status === "open";
  const title = group.item
    ? `#${group.item.id} · ${group.item.title}`
    : taskTitle(group.latest.task);
  const priors = group.attempts.filter((r) => r.id !== group.latest.id);
  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-lg bg-card p-3 ring-1 ring-white/12",
        group.archived && "opacity-60",
      )}
    >
      <div className="flex items-center gap-2">
        <SeverityDot severity={meta.attention ? (meta.severity === "red" ? "red" : "amber") : "green"} />
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{title}</span>
        {openAsk && (
          <Badge className={cn("font-mono text-[10px] uppercase", TONE_BADGE.amber)}>
            question open
          </Badge>
        )}
        <Badge className={cn("font-mono text-[10px] uppercase", SEV_TONE[meta.severity])}>
          {meta.label}
        </Badge>
      </div>
      <RunCard
        run={group.latest}
        activeRun={activeRun}
        latest={group.latest.id === latestId}
        selected={group.latest.id === selectedId}
        muted={group.archived}
        hideTask
        hideBadge
        onSelect={onSelect}
        onCancel={onCancel}
      />
      {priors.length > 0 && (
        <details className="group/attempts">
          <summary className="flex cursor-pointer list-none items-center gap-2 rounded-md bg-muted/30 px-2.5 py-1.5 hover:bg-muted/50 [&::-webkit-details-marker]:hidden">
            <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
              attempt {group.attempts.length} of {group.attempts.length} · {priors.length} earlier
            </span>
            <span className="ml-auto font-mono text-[10px] text-muted-foreground/60 transition-transform group-open/attempts:rotate-180">
              ▾
            </span>
          </summary>
          <div className="mt-2 flex flex-col gap-2">
            {priors.map((run) => (
              <RunCard
                key={run.id}
                run={run}
                activeRun={activeRun}
                latest={false}
                selected={run.id === selectedId}
                muted
                hideTask
                onSelect={onSelect}
                onCancel={onCancel}
              />
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

export function ItemRunList({
  groups,
  showArchived,
  activeRun,
  latestId,
  selectedId,
  onSelect,
  onCancel,
}: {
  groups: ItemGroup[];
  showArchived: boolean;
  activeRun?: ActiveRun;
  latestId?: string;
  selectedId?: string;
  onSelect: (run: HistoryRun) => void;
  onCancel: (runId: string) => void;
}) {
  const visible = groups.filter((g) => showArchived || !g.archived);
  const archivedCount = groups.length - groups.filter((g) => !g.archived).length;
  return (
    <div className="flex flex-col gap-3">
      {visible.map((g) => (
        <ItemCard
          key={g.item ? `item-${g.item.id}` : `run-${g.latest.id}`}
          group={g}
          activeRun={activeRun}
          latestId={latestId}
          selectedId={selectedId}
          onSelect={onSelect}
          onCancel={onCancel}
        />
      ))}
      {!showArchived && archivedCount > 0 && (
        <ConsoleLabel className="px-1">
          {archivedCount} archived item{archivedCount === 1 ? "" : "s"} hidden — nothing left the
          record
        </ConsoleLabel>
      )}
    </div>
  );
}
