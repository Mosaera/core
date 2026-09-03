import { cn } from "@/lib/utils";

import type { ActiveRun, BacklogItem, HistoryRun } from "../../api/client";
import { runsForItem, type ColumnMeta } from "../../lib/backlog";
import { EmptyNote } from "../overview/bits";
import { BacklogCard } from "./BacklogCard";

const TONE_ICON: Record<ColumnMeta["tone"], string> = {
  neutral: "text-muted-foreground",
  amber: "text-primary",
  green: "text-success",
};

/** One board lane: informative header (icon, label, count, status meaning),
 *  internally-scrolling card list, and an intentional empty state. */
export function BacklogColumn({
  col,
  items,
  runs,
  activeRun,
  anyRunning,
  runBusy,
  onOpen,
  onRun,
  onReset,
}: {
  col: ColumnMeta;
  items: BacklogItem[];
  runs: HistoryRun[];
  activeRun?: ActiveRun;
  anyRunning: boolean;
  runBusy: boolean;
  onOpen: (item: BacklogItem) => void;
  onRun: (item: BacklogItem) => void;
  onReset: (item: BacklogItem) => void;
}) {
  const Icon = col.icon;
  return (
    <section
      aria-label={col.label}
      className="flex min-h-0 flex-col gap-2 rounded-lg bg-muted/30 p-2"
    >
      <header className="flex flex-col gap-0.5 px-1.5 pt-0.5">
        <div className="flex items-center gap-2">
          <Icon className={cn("size-4 shrink-0", TONE_ICON[col.tone])} />
          <span className="font-mono text-[11px] font-medium uppercase tracking-[0.18em] text-foreground/80">
            {col.label}
          </span>
          <span className="ml-auto font-mono text-[11px] tabular-nums text-muted-foreground/60">
            {items.length}
          </span>
        </div>
        <p className="pl-6 text-[11px] text-muted-foreground/60">{col.meaning}</p>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pb-1 [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin]">
        {items.length === 0 ? (
          <div className="px-1.5">
            <EmptyNote icon={col.icon} hint={col.emptyHint}>
              {col.emptyTitle}
            </EmptyNote>
          </div>
        ) : (
          items.map((item) => (
            <BacklogCard
              key={item.id}
              item={item}
              activeRun={activeRun}
              latestRun={runsForItem(runs, item)[0]}
              anyRunning={anyRunning}
              runBusy={runBusy}
              onOpen={onOpen}
              onRun={onRun}
              onReset={onReset}
            />
          ))
        )}
      </div>
    </section>
  );
}
