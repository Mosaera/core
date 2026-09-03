import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GitCommitHorizontal } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, type Project } from "../../api/client";
import type { MrCompose } from "../../api/delivery";
import type { PmPrefillState } from "../../lib/backlog";
import {
  changesSummary,
  deriveReadiness,
  explainChangesPrefill,
  fileStats,
  groupItemChangesByDate,
} from "../../lib/changes";
import { itemsNeedingAttention } from "../../lib/itemRuns";
import { projectComposeDraft } from "../../lib/delivery";
import { MrComposeSheet, type ComposeDraft } from "../delivery/MrComposeSheet";
import { QueryState } from "../QueryState";
import { EmptyNote } from "../overview/bits";
import { CommitDateGroup } from "./CommitDateGroup";
import { FileImpactPanel } from "./FileImpactPanel";
import { MergeBar } from "./MergeBar";

/** Changes tab: a GitLab-style commits list of the project's changes (runs),
 *  grouped by date, over a compact merge-readiness bar. Each row toggles an
 *  `ai/commit`-style description; a row opens the full commit page. The
 *  accumulated diff is reachable via the bar's "Combined diff" toggle. */
export function ChangesCommitList({ project }: { project: Project }) {
  const qc = useQueryClient();
  const navigate = useNavigate();

  const diffQuery = useQuery({
    queryKey: ["project-diff", project.id],
    queryFn: () => api.projectDiff(project.id),
  });
  const { data: diff } = diffQuery;

  // Which forge this project delivers to (ADR-0112) — drives the request-noun copy on the
  // merge bar (S4) and, for GitHub, whether the compose sheet's title/body are editable.
  const { data: capability } = useQuery({
    queryKey: ["delivery-capability", project.id],
    queryFn: () => api.projectDeliveryCapability(project.id),
  });

  // Target-branch picker data (A1): read from the LOCAL clone, no api token needed. Same query
  // key as the Delivery tab so the two share one cache entry.
  const { data: branchData } = useQuery({
    queryKey: ["branches", project.id],
    queryFn: () => api.listBranches(project.id),
  });

  const { data: mr } = useQuery({
    queryKey: ["mr-status", project.id],
    queryFn: () => api.projectMrStatus(project.id),
    enabled: Boolean(project.mr_url),
    refetchInterval: (q) =>
      project.status === "in_review" && q.state.data?.state !== "merged" ? 15000 : false,
  });
  const mrState = mr?.state ?? null;

  useEffect(() => {
    if (mrState === "merged") {
      qc.invalidateQueries({ queryKey: ["project", project.id] });
      qc.invalidateQueries({ queryKey: ["project-diff", project.id] });
    }
  }, [mrState, qc, project.id]);

  const [err, setErr] = useState<string | null>(null);
  const [combinedOpen, setCombinedOpen] = useState(false);
  // The merge bar opens the SAME compose sheet the Delivery tab uses. It used to call
  // api.mergeProject() bare — one click pushed the commits and opened an MR the team could see,
  // with no review, while the identical call on Delivery got a full review surface.
  const [draft, setDraft] = useState<ComposeDraft | null>(null);

  const runs = project.runs ?? [];
  const backlog = project.backlog ?? [];

  const submit = useMutation({
    mutationFn: (compose: MrCompose) => api.mergeProject(project.id, compose),
    onSuccess: (r) => {
      qc.setQueryData<Project>(["project", project.id], (p) =>
        p ? { ...p, status: "in_review", mr_url: r.url } : p,
      );
      setDraft(null);
    },
    onError: (e: Error) => setErr(e.message),
  });

  function askPm(prefill: string) {
    const state: PmPrefillState = { pmPrefill: prefill };
    navigate(`/projects/${project.id}/pm`, { state });
  }

  const base = diff?.base ?? "source";
  const readiness = deriveReadiness(
    project,
    diff,
    mrState,
    Boolean(capability?.has_github_connection),
  );
  const merged = readiness.state === "merged";
  const { stats, partial } = diff ? fileStats(diff) : { stats: [], partial: false };
  const totals = stats.reduce(
    (acc, s) => ({ adds: acc.adds + (s.additions ?? 0), dels: acc.dels + (s.deletions ?? 0) }),
    { adds: 0, dels: 0 },
  );
  const mrLabel = merged ? "merged" : project.mr_url ? "MR open" : null;
  // ITEM-consolidated, like the Runs page: one entry per backlog item, latest attempt as its
  // state (redundancy audit 2026-08-22). This also ends a standing disagreement — "needs
  // attention" counted ATTEMPTS here while the Runs page and the overview counted ITEMS, so one
  // stuck item could read as eight problems.
  const itemBuckets = groupItemChangesByDate(runs, backlog, merged);
  const itemGroups = itemBuckets.flatMap((b) => b.items);
  const attentionCount = itemsNeedingAttention(itemGroups).length;

  const summary = diff
    ? changesSummary({
        fileCount: stats.length,
        adds: totals.adds,
        dels: totals.dels,
        base,
        runCount: itemGroups.length,
        attentionCount,
        mrLabel,
      })
    : "loading…";


  return (
    <div className="flex min-h-0 flex-col gap-4 lg:-mb-16 lg:h-[calc(100dvh-88px)] lg:min-h-[460px]">
      <MergeBar
        project={project}
        summary={summary}
        readiness={readiness}
        mergeBusy={submit.isPending}
        err={err}
        canCombined={Boolean(diff?.has_changes)}
        combinedOpen={combinedOpen}
        provider={capability?.provider}
        onOpenMr={() => setDraft(projectComposeDraft(project, base))}
        onExplain={() => askPm(explainChangesPrefill(base, stats.length))}
        onToggleCombined={() => setCombinedOpen((v) => !v)}
      />

      {diffQuery.isError && (
        <QueryState
          query={{ isLoading: false, isError: true, error: diffQuery.error, refetch: diffQuery.refetch }}
          compact
          errorLabel="Couldn't load the diff"
        >
          {null}
        </QueryState>
      )}

      <MrComposeSheet
        draft={draft}
        branches={branchData?.branches ?? []}
        commits={[]}
        provider={capability?.provider}
        // GitHub always opens via the REST path (a minted installation token, never a
        // push-option), so its title/body are faithfully editable independent of any
        // GitLab api-scoped token (task 4A-ii).
        apiTokenPresent={
          capability?.provider === "github" || Boolean(project.has_gitlab_api_token)
        }
        busy={submit.isPending}
        onSubmit={(_kind, compose) => submit.mutate(compose)}
        onClose={() => setDraft(null)}
      />

      {combinedOpen && (
        <div className="max-h-[45vh] shrink-0">
          <FileImpactPanel base={base} diffText={diff?.diff ?? ""} stats={stats} partial={partial} />
        </div>
      )}

      <div className="flex min-h-0 flex-1 flex-col gap-4 lg:overflow-y-auto lg:overflow-x-hidden lg:pr-0.5 lg:[scrollbar-color:var(--border)_transparent] lg:[scrollbar-width:thin]">
        {runs.length === 0 ? (
          <EmptyNote icon={GitCommitHorizontal} hint="Run backlog items to produce changes.">
            No changes yet.
          </EmptyNote>
        ) : (
          itemBuckets.map((b) => (
            <CommitDateGroup key={b.key} label={b.label} groups={b.items} backlog={backlog} />
          ))
        )}
      </div>
    </div>
  );
}
