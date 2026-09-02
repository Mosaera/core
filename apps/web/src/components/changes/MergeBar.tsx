import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";

import type { Project } from "../../api/client";
import type { Readiness } from "../../lib/changes";

function blockedReason(r: Readiness): string {
  return r.reason === "validation-failed"
    ? "The latest settled run's validation did not pass."
    : "The latest settled run was not approved.";
}

/** Compact merge-readiness header above the commits list — the slim replacement
 *  for the old readiness dashboard + toolbar. Keeps the `Changes` heading, the
 *  honest summary, the PM "explain" handoff, a "combined diff" toggle, and the
 *  single readiness-driven merge action. */
export function MergeBar({
  project,
  summary,
  readiness,
  mergeBusy,
  err,
  canCombined,
  combinedOpen,
  onOpenMr,
  onExplain,
  onToggleCombined,
}: {
  project: Project;
  summary: string;
  readiness: Readiness;
  mergeBusy: boolean;
  err: string | null;
  canCombined: boolean;
  combinedOpen: boolean;
  onOpenMr: () => void;
  onExplain: () => void;
  onToggleCombined: () => void;
}) {
  const state = readiness.state;
  const blocked = state === "blocked";
  return (
    <header className="flex shrink-0 flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h1 className="text-lg font-semibold tracking-tight">Changes</h1>
          <p className="truncate font-mono text-xs text-muted-foreground">{summary}</p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Button size="sm" variant="ghost" className="text-muted-foreground" onClick={onExplain}>
            Explain these changes
          </Button>
          {canCombined && (
            <Button
              size="sm"
              variant="outline"
              aria-expanded={combinedOpen}
              onClick={onToggleCombined}
            >
              {combinedOpen ? "Hide combined diff" : "Combined diff"}
            </Button>
          )}
          {(state === "merged" || state === "mr-open") && project.mr_url && (
            <Button size="sm" nativeButton={false} render={<a href={project.mr_url} target="_blank" rel="noreferrer" />}>
              {state === "merged" ? "View merged MR" : "View MR"}
            </Button>
          )}
          {state === "no-token" && (
            <Button
              size="sm"
              variant="outline"
              nativeButton={false}
              // The PROJECT's Integration pane — the credential this bar is missing is the
              // project's, not the instance-wide one this used to link to.
              render={<Link to={`/projects/${project.id}/settings?pane=integration`} />}
            >
              Connect GitLab
            </Button>
          )}
          {(state === "ready" || state === "delivered-unpushed" || state === "blocked") && (
            <Button
              size="sm"
              disabled={blocked || mergeBusy}
              onClick={onOpenMr}
            >
              {mergeBusy ? "Opening…" : "Open merge request"}
            </Button>
          )}
        </div>
      </div>
      {blocked && <p className="text-[11px] text-primary">{blockedReason(readiness)}</p>}
      {state === "delivered-unpushed" && (
        <p className="text-[11px] text-amber-600 dark:text-amber-400">
          Committed locally — these changes are not on the remote yet. Opening the merge
          request pushes them.
        </p>
      )}
      {err && (
        <p role="alert" className="text-xs text-destructive">
          {err}
        </p>
      )}
    </header>
  );
}
