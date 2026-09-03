import { MessageSquare } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";

import type { ActiveRun, HistoryRun } from "../../api/client";
import { historyRunHref, liveRunHref } from "../../lib/runs";

/** Compact identity + honest counts; run-specific asks live on the detail
 *  panel, the toolbar carries only the whole-history one.
 *
 *  Redundancy audit 2026-08-22: the summary-tile row was deleted (its four numbers restated this
 *  line's `itemRunsSummary`); the two behaviors it carried live here now — the archived toggle
 *  and the back-to-latest UNPIN (which snaps the detail panel's selection, distinct from
 *  "View latest run" which navigates away). */
export function RunsToolbar({
  summary,
  latest,
  activeRun,
  archivedCount = 0,
  showArchived = false,
  pinned = false,
  onToggleArchived,
  onSelectLatest,
  onSummarize,
}: {
  summary: string;
  latest?: HistoryRun;
  activeRun?: ActiveRun;
  archivedCount?: number;
  showArchived?: boolean;
  /** A run other than the latest is pinned into the detail panel. */
  pinned?: boolean;
  onToggleArchived?: () => void;
  onSelectLatest?: () => void;
  onSummarize: () => void;
}) {
  const liveLatest = latest?.status === "RUNNING" && activeRun?.run_id === latest.id;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <h1 className="font-sans text-2xl font-bold tracking-tight">Runs</h1>
      <span className="font-mono text-xs tabular-nums text-muted-foreground">{summary}</span>

      <div className="ms-auto flex flex-wrap items-center gap-2">
        {pinned && onSelectLatest && (
          <Button
            size="sm"
            variant="ghost"
            className="text-muted-foreground"
            onClick={onSelectLatest}
          >
            Back to latest run
          </Button>
        )}
        {archivedCount > 0 && onToggleArchived && (
          <Button
            size="sm"
            variant="ghost"
            className="text-muted-foreground"
            onClick={onToggleArchived}
          >
            Archived {archivedCount} — {showArchived ? "hide" : "show"}
          </Button>
        )}
        {latest && (
          <Button
            size="sm"
            variant="secondary"
            nativeButton={false}
            render={
              <Link
                to={
                  liveLatest
                    ? liveRunHref(activeRun.run_id, activeRun.project_id)
                    : historyRunHref(latest.id, latest.project_id)
                }
              />
            }
          >
            View latest run
          </Button>
        )}
        <Button size="sm" variant="ghost" className="text-muted-foreground" onClick={onSummarize}>
          <MessageSquare data-icon="inline-start" />
          Ask PM to summarize runs
        </Button>
      </div>
    </div>
  );
}
