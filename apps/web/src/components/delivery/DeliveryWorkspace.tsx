import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GitMerge } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { useAuth } from "../../api/authContext";
import { api, type Project } from "../../api/client";
import type { MrCompose } from "../../api/delivery";
import { deriveReadiness } from "../../lib/changes";
import {
  deliverySummary,
  driftNote,
  itemMrRows,
  projectComposeDraft,
  stuckItems,
  READINESS_PLAIN,
  remoteSyncPlain,
  standingPlain,
} from "../../lib/delivery";
import { providerNouns } from "../../lib/providerNouns";
import { ConsoleLabel } from "../overview/bits";
import { BranchConfirmDialogs, type BranchConfirm } from "./BranchConfirmDialogs";
import { CleanCheckPanel } from "./CleanCheckPanel";
import { DeliveryCredentials } from "./DeliveryCredentials";
import { DriftRecovery } from "./DriftRecovery";
import { ItemRow } from "./ItemRow";
import { MergeConfirm } from "./MergeConfirm";
import { MrComposeSheet, type ComposeDraft } from "./MrComposeSheet";

/** Delivery tab (ADR-0102 slice P): ONE surface to see and drive the git last
 *  mile — the pipeline verdict, per-item branches → MRs → merge states with the
 *  manual opener, and the delivery knobs. Changes stays the diff REVIEW surface;
 *  this is the MANAGEMENT surface. */

export function DeliveryWorkspace({ project }: { project: Project }) {
  const qc = useQueryClient();
  const { data: diff } = useQuery({
    queryKey: ["project-diff", project.id],
    queryFn: () => api.projectDiff(project.id),
  });
  const { data: mr } = useQuery({
    queryKey: ["mr-status", project.id],
    queryFn: () => api.projectMrStatus(project.id),
    refetchInterval: 15_000,
  });
  // ADR-0112/#120: which forge this project can deliver to, and whether it can at all.
  // Derived server-side from the source URL, so it needs no refetch interval.
  const { data: capability } = useQuery({
    queryKey: ["delivery-capability", project.id],
    queryFn: () => api.projectDeliveryCapability(project.id),
  });
  const deliverable = capability?.can_finish ?? true;
  // Per-item requests are GitLab-only (ADR-0114). Absent on an older server ⇒ assume yes.
  const itemRequests = capability?.item_requests_supported ?? true;
  // S4: the copy on this page must not assume GitLab — a connected GitHub project opens a
  // pull request, not a merge request. Neutral while capability is still loading.
  const nouns = providerNouns(capability?.provider);
  const readiness = deriveReadiness(
    project,
    diff,
    mr?.state ?? null,
    Boolean(capability?.has_github_connection),
  );
  const rows = itemMrRows(project.backlog ?? [], mr?.items);
  const drift = driftNote(project.error);
  const [err, setErr] = useState<string | null>(null);
  const [draft, setDraft] = useState<ComposeDraft | null>(null);
  const apiTokenPresent = Boolean(project.has_gitlab_api_token);
  const base = diff?.base ?? "main";
  const standing = standingPlain(diff?.standing, base);

  // Branches for the target picker (A1) — read from the local clone, no token needed.
  const { data: branchData } = useQuery({
    queryKey: ["branches", project.id],
    queryFn: () => api.listBranches(project.id),
  });
  const { isAdmin } = useAuth();
  // The global-knob row, read-only here: `member_branch_delete` decides whether a member may
  // destroy a branch. Edited in Settings > Autonomy (redundancy audit 2026-08-22 — config
  // left this operations page; two editors for one stored value was the defect).
  const { data: knobs } = useQuery({
    queryKey: ["general-settings"],
    queryFn: () => api.getGeneralSettings(),
  });
  // Commits for the picker (A2) — only fetched when composing a combined MR with an api token.
  const { data: commitData } = useQuery({
    queryKey: ["commits", project.id],
    queryFn: () => api.listCommits(project.id),
    enabled: apiTokenPresent && draft?.kind === "project",
  });

  // A3: only Mosaera's own delivery branches are offered for deletion — never a human branch
  // (staging/develop/main). The server additionally refuses an open MR's source or target.
  const [deleted, setDeleted] = useState<string[]>([]);
  const deletable = (branchData?.branches ?? []).filter(
    (b) => b.name.startsWith("mosaera/") && !b.protected && !deleted.includes(b.name),
  );
  // What the prune confirm can NAME. The server's rule is item-MR-state based, so this is the
  // client's best view of the same set, never the authority — the copy says so.
  // The prune confirm names branches by the SAME predicate the server prunes with (an item whose
  // MR merged), not by GitLab's branch flag. Those are different facts: GitLab's `merged` means
  // "commits are in main", which a stacked predecessor satisfies while its own MR is still open.
  // Naming by the wrong one both over-promised and silently under-reported.
  const stuck = stuckItems(rows, branchData?.branches ?? [], branchData?.source);
  // The server refuses branch destruction for a member unless an admin opted them in, so the
  // surface must not offer it either — a button that 403s is the defect this review keeps finding.
  // Reads the knob row above.
  const mayDestroy = isAdmin || knobs?.knobs?.member_branch_delete?.value === true;
  const mergedCount = rows.filter((r) => r.mrState === "merged").length;
  const prunable = rows
    .filter((r) => r.mrState === "merged" && r.branch)
    .map((r) => r.branch)
    .filter((b) => !deleted.includes(b));

  const invalidate = () => {
    setErr(null);
    setDraft(null);
    void qc.invalidateQueries({ queryKey: ["project", project.id] });
    void qc.invalidateQueries({ queryKey: ["mr-status", project.id] });
  };
  const submit = useMutation({
    mutationFn: (v: { kind: ComposeDraft["kind"]; compose: MrCompose }) =>
      typeof v.kind === "string"
        ? api.mergeProject(project.id, v.compose)
        : api.openItemMr(project.id, v.kind.itemId, v.compose),
    onSuccess: invalidate,
    onError: (e: Error) => setErr(e.message),
  });
  // Branches the SERVER confirmed deleted. The delete/prune endpoints return 200 only after the
  // remote delete actually succeeded, so their response is the validation — and this set, not the
  // refetch, is what removes the row. Cache surgery alone loses the race: the list now comes from
  // GitLab (ADR-0103 §4), GitLab can still report a just-deleted branch, and the reconciling
  // refetch would put it straight back and leave it there until a manual page reload. Filtering
  // by confirmed deletions is stable no matter how long the remote takes to catch up.
  const dropBranches = (gone: string[]) => setDeleted((prev) => [...prev, ...gone]);
  // The last step of delivery. Admin-gated server-side; `apiTokenPresent` decides whether the
  // control is OFFERED, so an operator never meets a button that cannot work (the defect this
  // whole cluster is about).
  const [mergeItem, setMergeItem] = useState<number | null>(null);
  const merge = useMutation({
    mutationFn: (v: { itemId: number; sha: string; whenPipelineSucceeds: boolean }) =>
      api.mergeItemMr(project.id, v.itemId, {
        sha: v.sha,
        when_pipeline_succeeds: v.whenPipelineSucceeds,
      }),
    onSuccess: () => {
      setMergeItem(null);
      invalidate();
    },
    onError: (e: Error) => {
      setMergeItem(null);
      setErr(e.message);
    },
  });
  const prune = useMutation({
    mutationFn: () => api.pruneMergedBranches(project.id),
    onSuccess: (resp) => {
      dropBranches(resp.pruned);
      void qc.invalidateQueries({ queryKey: ["branches", project.id] });
    },
    onError: (e: Error) => setErr(e.message),
  });
  const del = useMutation({
    mutationFn: (branch: string) => api.deleteBranch(project.id, branch),
    onSuccess: (resp) => {
      dropBranches([resp.deleted]);
      void qc.invalidateQueries({ queryKey: ["branches", project.id] });
    },
    onError: (e: Error) => setErr(e.message),
  });
  // Both branch actions delete on the REMOTE and cannot be undone from here, so neither fires
  // straight off its button — `confirm` holds the pending one until the operator agrees.
  const [confirm, setConfirm] = useState<BranchConfirm>(null);
  const retarget = useMutation({
    mutationFn: (id: number) => api.retargetItemMr(project.id, id, base),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["project", project.id] });
      void qc.invalidateQueries({ queryKey: ["mr-status", project.id] });
    },
    onError: (e: Error) => setErr(e.message),
  });
  // Ending an MR is reversible (reopen undoes it) and touches no branch, so unlike the branch
  // actions above it does not need a confirm step.
  const mrState = useMutation({
    mutationFn: ({ id, action }: { id: number; action: "close" | "reopen" }) =>
      api.setItemMrState(project.id, id, action),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["project", project.id] });
      void qc.invalidateQueries({ queryKey: ["mr-status", project.id] });
    },
    onError: (e: Error) => setErr(e.message),
  });

  function composeItem(itemId: number) {
    const item = (project.backlog ?? []).find((i) => i.id === itemId);
    const bodyDefault = [item?.description, item?.acceptance && `## Acceptance\n${item.acceptance}`]
      .filter(Boolean)
      .join("\n\n");
    setDraft({
      kind: { itemId },
      title: `mosaera: ${item?.title ?? `item ${itemId}`}`,
      body: bodyDefault || `Delivers backlog item #${itemId}.`,
      target: base,
      squash: false,
      removeSource: false, // stacked default
    });
  }
  function composeProject() {
    // Shared with the Changes tab's merge bar so the two surfaces cannot drift.
    setDraft(projectComposeDraft(project, base));
  }

  return (
    <div className="flex min-h-0 flex-col gap-4 lg:-mb-16 lg:h-[calc(100dvh-88px)] lg:min-h-[460px]">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <h1 className="font-sans text-2xl font-bold tracking-tight">Delivery</h1>
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {deliverySummary(rows)}
        </span>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 items-start gap-3 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:items-stretch">
        {/* ---- per-item delivery table ---- */}
        <section
          aria-label="Item merge requests"
          className="flex min-h-0 flex-col gap-2 overflow-y-auto rounded-lg bg-card p-4 ring-1 ring-white/12 [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin]"
        >
          <ConsoleLabel>Item merge requests</ConsoleLabel>
          {rows.length > 0 ? (
            <ul className="flex flex-col">
              {rows.map((r) => (
                <ItemRow
                  key={r.id}
                  row={r}
                  busy={submit.isPending || retarget.isPending || mrState.isPending}
                  stuckOn={stuck.get(r.id)}
                  onOpen={deliverable && itemRequests ? composeItem : undefined}
                  onRetarget={(id) => setConfirm({ kind: "retarget", id })}
                  onMrState={(id, action) => mrState.mutate({ id, action })}
                  onMerge={apiTokenPresent ? (id) => setMergeItem(id) : undefined}
                />
              ))}
            </ul>
          ) : (
            <p className="py-1 text-[12.5px] text-muted-foreground">
              No backlog items yet — deliveries appear here per item.
            </p>
          )}
          {err && (
            <p role="alert" className="text-xs text-destructive">
              {err}
            </p>
          )}
        </section>

        <div className="flex min-h-0 flex-col gap-3 overflow-y-auto [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin]">
          {/* ---- pipeline status ---- */}
          <section
            aria-label="Delivery pipeline"
            className="flex flex-col gap-2 rounded-lg bg-card p-4 ring-1 ring-white/12"
          >
            <ConsoleLabel>Pipeline</ConsoleLabel>
            <p className="text-[13px] leading-relaxed">{READINESS_PLAIN[readiness.state]}</p>
            <p className="font-mono text-[11px] text-muted-foreground">
              base {diff?.base ?? "…"} · {remoteSyncPlain(diff?.remote_synced)}
            </p>
            {standing && (
              <p
                className={cn(
                  "font-mono text-[11px]",
                  diff?.standing?.state === "behind" ||
                    diff?.standing?.state === "behind_unknown"
                    ? "text-amber-600 dark:text-amber-400"
                    : "text-muted-foreground",
                )}
              >
                {standing}
              </p>
            )}
            {drift && <DriftRecovery projectId={project.id} detail={drift} />}
            <div className="flex flex-wrap items-center gap-2 pt-1">
              {deliverable &&
                (readiness.state === "ready" || readiness.state === "delivered-unpushed") && (
                <Button size="sm" onClick={composeProject}>
                  <GitMerge data-icon="inline-start" />
                  Open one combined {nouns.short}
                </Button>
              )}
              {(readiness.state === "mr-open" || readiness.state === "merged") &&
                project.mr_url && (
                  <Button
                    size="sm"
                    variant="secondary"
                    nativeButton={false}
                    render={<a href={project.mr_url} target="_blank" rel="noreferrer" />}
                  >
                    {readiness.state === "merged"
                      ? `View merged ${nouns.short}`
                      : `View project ${nouns.short}`}
                  </Button>
                )}
            </div>
          </section>

          <CleanCheckPanel projectId={project.id} />

          <DeliveryCredentials
            project={project}
            apiTokenPresent={apiTokenPresent}
            capability={capability}
          />

          {/* ---- branches: prune merged (ADR-0103 Phase 4) + per-branch delete (A3) ----
              GitLab-only (F15): branch listing/prune/delete are 400s server-side for any
              other provider. Absent capability (still loading, or an older server) ⇒
              treat as not-GitLab rather than flashing the panel then hiding it. */}
          {capability?.provider === "gitlab" && (mergedCount > 0 || deletable.length > 0) && (
            <section
              aria-label="Branches"
              className="flex flex-col gap-2 rounded-lg bg-card p-4 ring-1 ring-white/12"
            >
              <ConsoleLabel>Branches</ConsoleLabel>
              {mergedCount > 0 && (
                <>
                  {/* The COUNT lives in the header summary ("N merged"); this line states the
                      rule that applies to them (redundancy audit 2026-08-22). */}
                  <p className="text-[12.5px] text-muted-foreground">
                    Cleans up merged item branches only — never one an open MR still targets.
                  </p>
                  <Button
                    size="sm"
                    variant="outline"
                    className="w-fit"
                    disabled={prune.isPending || !mayDestroy}
                    onClick={() => setConfirm({ kind: "prune" })}
                  >
                    {prune.isPending ? "Pruning…" : "Prune merged branches"}
                  </Button>
                  {prune.data && prune.data.pruned.length > 0 && (
                    <p className="font-mono text-[11px] text-success">
                      pruned {prune.data.pruned.join(", ")}
                    </p>
                  )}
                </>
              )}
              {deletable.length > 0 && (
                <ul className="flex flex-col">
                  {deletable.map((b) => (
                    <li
                      key={b.name}
                      className="flex items-center gap-2 border-t border-border/40 py-1.5 first:border-t-0"
                    >
                      <span className="min-w-0 flex-1 truncate font-mono text-[11.5px]">
                        {b.name}
                        {b.merged && <span className="text-muted-foreground"> · in main</span>}
                      </span>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-destructive"
                        disabled={del.isPending || !mayDestroy}
                            onClick={() => setConfirm({ kind: "branch", name: b.name })}
                      >
                        Delete
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
              <p className="text-[11px] text-muted-foreground/80">
                Deleting the source or target branch of an open MR is refused server-side.
              </p>
              {!mayDestroy && (
                <p className="text-[11px] leading-relaxed text-muted-foreground/80">
                  Deleting branches is admin-only on this instance. An admin can allow it with
                  &ldquo;Members may delete branches&rdquo; in{" "}
                  <Link to="/settings/autonomy" className="text-primary hover:underline">
                    Settings › Autonomy
                  </Link>
                  .
                </p>
              )}
              {branchData?.source === "clone" && (
                <p className="text-[11px] leading-relaxed text-amber-600 dark:text-amber-400">
                  Partial list — read from the local clone, which never holds this project&rsquo;s
                  <span className="font-mono"> mosaera/*</span> branches. Add an{" "}
                  <span className="font-mono">api</span>-scoped token to see the real branches and
                  their merge state.
                </p>
              )}
            </section>
          )}

        </div>
      </div>

      <MrComposeSheet
        draft={draft}
        branches={branchData?.branches ?? []}
        commits={commitData?.commits ?? []}
        // GitHub's compose always goes through the REST path (an installation token, never a
        // push-option), independent of any GitLab api-scoped token (task 4A-ii).
        apiTokenPresent={capability?.provider === "github" || apiTokenPresent}
        provider={capability?.provider}
        busy={submit.isPending}
        onSubmit={(kind, compose) => submit.mutate({ kind, compose })}
        onClose={() => setDraft(null)}
      />

      <MergeConfirm
        projectId={project.id}
        itemId={mergeItem}
        open={mergeItem != null}
        onOpenChange={(o) => !o && setMergeItem(null)}
        busy={merge.isPending}
        provider={capability?.provider}
        onMerge={({ sha, whenPipelineSucceeds }) =>
          mergeItem != null && merge.mutate({ itemId: mergeItem, sha, whenPipelineSucceeds })
        }
      />

      <BranchConfirmDialogs
        confirm={confirm}
        onOpenChange={(o) => !o && setConfirm(null)}
        base={base}
        hostName={nouns.hostName}
        prunable={prunable}
        deleteBranch={(name) => del.mutate(name)}
        deleteBusy={del.isPending}
        retarget={(id) => retarget.mutate(id)}
        retargetBusy={retarget.isPending}
        prune={() => prune.mutate()}
        pruneBusy={prune.isPending}
      />
    </div>
  );
}
