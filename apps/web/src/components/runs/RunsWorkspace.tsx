import { useQueryClient } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useToast } from "@/components/ui/toast";

import { api, type ActiveRun, type HistoryRun, type Project } from "../../api/client";
import type { PmPrefillState } from "../../lib/backlog";
import { latestRun } from "../../lib/runs";
import { groupRunsByItem, itemRunsSummary, summarizeItemsPrefill } from "../../lib/itemRuns";
import { EmptyNote } from "../overview/bits";
import { RunDetailPanel } from "./RunDetailPanel";
import { ItemRunList } from "./ItemRunList";
import { RunsToolbar } from "./RunsToolbar";

/** Runs tab: execution history + diagnostics. Full-height workspace (shell
 *  offsets shared with PM/Backlog/Changes); grouped run list on the left, a
 *  persistent detail panel on the right. Selection follows the latest run
 *  until the user pins one — polls never write selection. */
export function RunsWorkspace({
  project,
  activeRun,
}: {
  project: Project;
  activeRun?: ActiveRun;
}) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { toast } = useToast();

  const runs = project.runs ?? [];
  const backlog = project.backlog ?? [];

  // null = follow the latest run; a pinned id sticks until it vanishes.
  const [pinnedRunId, setPinnedRunId] = useState<string | null>(null);
  const pinned = pinnedRunId != null ? runs.find((r) => r.id === pinnedRunId) : undefined;
  const selected: HistoryRun | undefined = pinned ?? latestRun(runs);

  useEffect(() => {
    if (pinnedRunId != null && !runs.some((r) => r.id === pinnedRunId)) setPinnedRunId(null);
  }, [pinnedRunId, runs]);

  async function cancel(runId: string) {
    try {
      await api.cancelRun(runId);
      qc.invalidateQueries({ queryKey: ["project", project.id] });
      qc.invalidateQueries({ queryKey: ["active-runs"] });
    } catch (e) {
      toast({
        title: "Couldn't cancel the run",
        description: e instanceof Error ? e.message : String(e),
        variant: "error",
      });
    }
  }

  function askPm(prefill: string) {
    const state: PmPrefillState = { pmPrefill: prefill };
    navigate(`/projects/${project.id}/pm`, { state });
  }

  const merged = project.status === "merged";
  // ITEM-consolidated: the item is the row, its latest attempt is its state, priors collapse.
  const groups = groupRunsByItem(runs, backlog, merged);
  const latest = latestRun(runs);
  const [showArchived, setShowArchived] = useState(false);

  return (
    <div className="flex min-h-0 flex-col gap-4 lg:-mb-16 lg:h-[calc(100dvh-88px)] lg:min-h-[460px]">
      <RunsToolbar
        summary={itemRunsSummary(groups, runs.length)}
        latest={latest}
        activeRun={activeRun}
        archivedCount={groups.filter((g) => g.archived).length}
        showArchived={showArchived}
        pinned={pinnedRunId != null}
        onToggleArchived={() => setShowArchived((v) => !v)}
        onSelectLatest={() => setPinnedRunId(null)}
        onSummarize={() => askPm(summarizeItemsPrefill(groups, runs.length))}
      />

      {runs.length === 0 ? (
        <div className="flex min-h-0 flex-1 items-start justify-start rounded-lg bg-muted/30 p-6">
          <EmptyNote icon={Activity} hint="Run a backlog item to generate execution history.">
            No runs yet
          </EmptyNote>
        </div>
      ) : (
        <>
          <div className="grid min-h-0 flex-1 grid-cols-1 items-start gap-3 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:items-stretch">
            <div className="flex min-h-0 flex-col gap-3 lg:overflow-y-auto lg:pr-0.5 lg:[scrollbar-color:var(--border)_transparent] lg:[scrollbar-width:thin]">
              <ItemRunList
                groups={groups}
                showArchived={showArchived}
                activeRun={activeRun}
                latestId={latest?.id}
                selectedId={selected?.id}
                onSelect={(run) => setPinnedRunId(run.id)}
                onCancel={(id) => void cancel(id)}
              />
            </div>

            <RunDetailPanel
              run={selected}
              latest={selected != null && selected.id === latest?.id}
              project={project}
              activeRun={activeRun}
              onAskPm={askPm}
              onCancel={(id) => void cancel(id)}
            />
          </div>
        </>
      )}
    </div>
  );
}
