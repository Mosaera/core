import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  api,
  type ActiveRun,
  type BacklogItem,
  type ChangesetOp,
  type ClarificationResolveBody,
  type Project,
  type RunMode,
} from "../../api/client";
import { BACKLOG_COLUMNS, type PmPrefillState } from "../../lib/backlog";
import { REPRIORITIZE_PREFILL } from "../../lib/backlog";
import { liveRunHref } from "../../lib/runs";
import { Spinner } from "../AgentStatus";
import { BacklogColumn } from "./BacklogColumn";
import { BacklogItemSheet } from "./BacklogItemSheet";
import { BacklogToolbar } from "./BacklogToolbar";
import { ChangesetReview } from "./ChangesetReview";

const REFRESH_CONFIRM =
  'Regenerate the backlog?\n\nThe PM will re-plan the project from the brief. All "To do" items are removed and replaced; items in progress, in review, or done are kept. This cannot be undone.';

/** Backlog tab: the delivery control surface. Full-height board (same shell
 *  offsets as the PM workspace: -mb-16 swallows main's bottom padding so the
 *  window itself never scrolls on desktop); columns scroll internally; the
 *  detail drawer owns depth so cards stay compact. */
export function BacklogWorkspace({
  project,
  activeRun,
}: {
  project: Project;
  activeRun?: ActiveRun;
}) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const items = project.backlog ?? [];
  const runs = project.runs ?? [];

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [runBusy, setRunBusy] = useState(false);

  const anyRunning = items.some((i) => i.status === "in_progress");
  const selected = selectedId != null ? items.find((i) => i.id === selectedId) : undefined;

  // The drawer derives from live query data; if the selected item vanishes
  // (e.g. a backlog refresh replaced it) the drawer closes rather than lying.
  useEffect(() => {
    if (selectedId != null && !selected) setSelectedId(null);
  }, [selectedId, selected]);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["project", project.id] });

  const patch = useMutation({
    mutationFn: ({ itemId, body }: { itemId: number; body: Partial<BacklogItem> }) =>
      api.patchBacklogItem(project.id, itemId, body),
    onMutate: () => setErr(null),
    onSuccess: invalidate,
    onError: (e) => setErr(e instanceof Error ? e.message : String(e)),
  });

  const add = useMutation({
    mutationFn: (title: string) => api.addBacklogItem(project.id, { title }),
    onMutate: () => setErr(null),
    onSuccess: invalidate,
    onError: (e) => setErr(e instanceof Error ? e.message : String(e)),
  });

  const deps = useMutation({
    mutationFn: ({ itemId, dependsOn }: { itemId: number; dependsOn: number[] }) =>
      api.setItemDependencies(project.id, itemId, dependsOn),
    onMutate: () => setErr(null),
    onSuccess: invalidate,
    onError: (e) => setErr(e instanceof Error ? e.message : String(e)),
  });

  const setLock = useMutation({
    mutationFn: ({ itemId, locked, reason }: { itemId: number; locked: boolean; reason?: string }) =>
      api.setItemLock(project.id, itemId, locked, reason),
    onMutate: () => setErr(null),
    onSuccess: invalidate,
    onError: (e) => setErr(e instanceof Error ? e.message : String(e)),
  });

  const resolveClarification = useMutation({
    mutationFn: ({
      itemId,
      body,
    }: {
      itemId: number;
      body: ClarificationResolveBody;
    }) => api.resolveClarification(project.id, itemId, body),
    onMutate: () => setErr(null),
    onSuccess: invalidate,
    onError: (e) => setErr(e instanceof Error ? e.message : String(e)),
  });

  // Curate: Quincy PROPOSES a changeset; nothing is applied until the review
  // panel is approved.
  const [changeset, setChangeset] = useState<ChangesetOp[] | null>(null);
  const curate = useMutation({
    mutationFn: (instruction: string) => api.curateBacklog(project.id, instruction || undefined),
    onMutate: () => setErr(null),
    onSuccess: (res) => setChangeset(res.changeset),
    onError: (e) => setErr(e instanceof Error ? e.message : String(e)),
  });
  const applyChangeset = useMutation({
    mutationFn: (ops: ChangesetOp[]) => api.applyChangeset(project.id, ops),
    onMutate: () => setErr(null),
    onSuccess: () => {
      setChangeset(null);
      invalidate();
    },
    onError: (e) => setErr(e instanceof Error ? e.message : String(e)),
  });

  function curateBacklog(instruction: string) {
    curate.mutate(instruction);
  }

  async function runItem(
    item: BacklogItem,
    mode: RunMode = "guided",
    limits?: {
      max_iterations?: number | null;
      budget_tokens?: number | null;
      budget_usd?: number | null;
      cost_mode?: string | null;
    },
    override = false,
  ) {
    setErr(null);
    setRunBusy(true);
    try {
      // Only thread override when set so the default path keeps a 4-arg call.
      const snap = override
        ? await api.runBacklogItem(project.id, item.id, mode, limits, true)
        : await api.runBacklogItem(project.id, item.id, mode, limits);
      navigate(liveRunHref(snap.run_id, project.id));
    } catch (e) {
      // The server is authoritative on run races (409 lands here).
      setErr(e instanceof Error ? e.message : String(e));
      setRunBusy(false);
    }
  }

  // Refresh gap: with no todo/running items the page query stops polling, so
  // regenerated items would never appear. Poll bounded: until the cleared
  // "To do" lane repopulates (0 → >0) or ~90s passes.
  const [regenerating, setRegenerating] = useState(false);
  const sawEmptyTodo = useRef(false);
  const todoCount = items.filter((i) => i.status === "todo").length;
  useEffect(() => {
    if (!regenerating) return;
    if (todoCount === 0) {
      sawEmptyTodo.current = true;
    } else if (sawEmptyTodo.current) {
      setRegenerating(false);
      sawEmptyTodo.current = false;
    }
  }, [regenerating, todoCount]);
  useEffect(() => {
    if (!regenerating) return;
    const started = Date.now();
    const id = setInterval(() => {
      invalidate();
      if (Date.now() - started > 90_000) setRegenerating(false);
    }, 2000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [regenerating]);

  async function refreshBacklog() {
    if (!window.confirm(REFRESH_CONFIRM)) return;
    setErr(null);
    try {
      await api.generateBacklog(project.id);
      sawEmptyTodo.current = false;
      setRegenerating(true);
      invalidate();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  async function toggleAutonomous(on: boolean) {
    setErr(null);
    try {
      await api.setAutonomous(project.id, on);
      invalidate();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  async function runAutonomously() {
    setErr(null);
    try {
      // Enable-then-start: /start 400s if the flag isn't set, so make the
      // action self-sufficient even if the toggle state is stale.
      if (!project.autonomous) await api.setAutonomous(project.id, true);
      await api.startAutonomous(project.id);
      invalidate();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  function askPm(prefill: string) {
    const state: PmPrefillState = { pmPrefill: prefill };
    navigate(`/projects/${project.id}/pm`, { state });
  }

  const drafting = project.status === "active";

  return (
    <div className="flex min-h-0 flex-col gap-4 lg:-mb-16 lg:h-[calc(100dvh-88px)] lg:min-h-[460px]">
      <BacklogToolbar
        project={project}
        onAdd={async (title) => {
          await add.mutateAsync(title);
        }}
        addPending={add.isPending}
        onRefresh={() => void refreshBacklog()}
        onRunAutonomously={() => void runAutonomously()}
        onToggleAutonomous={(on) => void toggleAutonomous(on)}
        onAskReprioritize={() => askPm(REPRIORITIZE_PREFILL)}
        onCurate={curateBacklog}
        curatePending={curate.isPending}
      />

      {err && (
        <p role="alert" className="text-xs text-destructive">
          {err}
        </p>
      )}

      {changeset && (
        <ChangesetReview
          ops={changeset}
          items={items}
          onApprove={() => applyChangeset.mutate(changeset)}
          onDiscard={() => setChangeset(null)}
          applying={applyChangeset.isPending}
          error={
            applyChangeset.error
              ? applyChangeset.error instanceof Error
                ? applyChangeset.error.message
                : String(applyChangeset.error)
              : null
          }
        />
      )}

      {items.length === 0 ? (
        <div className="flex min-h-0 flex-1 items-center justify-center rounded-lg bg-muted/30 p-6">
          <p className="text-sm text-muted-foreground">
            {drafting || regenerating ? (
              <>
                <Spinner /> The PM is drafting the backlog…
              </>
            ) : (
              "Approve the brief on Overview to have the PM draft the backlog."
            )}
          </p>
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-4">
          {BACKLOG_COLUMNS.map((col) => (
            <BacklogColumn
              key={col.key}
              col={col}
              items={items.filter((i) => i.status === col.key)}
              runs={runs}
              activeRun={activeRun}
              anyRunning={anyRunning}
              runBusy={runBusy}
              onOpen={(item) => setSelectedId(item.id)}
              onRun={(item) => void runItem(item)}
              onReset={(item) => void patch.mutate({ itemId: item.id, body: { status: "todo" } })}
            />
          ))}
        </div>
      )}

      <BacklogItemSheet
        item={selected}
        project={project}
        activeRun={activeRun}
        runDisabled={anyRunning || Boolean(activeRun) || runBusy}
        patchPending={patch.isPending}
        onClose={() => setSelectedId(null)}
        onRun={(item, mode, limits, override) => void runItem(item, mode, limits, override)}
        onPatch={async (itemId, body) => {
          await patch.mutateAsync({ itemId, body });
        }}
        onSetDependencies={async (itemId, dependsOn) => {
          await deps.mutateAsync({ itemId, dependsOn });
        }}
        onResolveClarification={async (itemId, body) => {
          await resolveClarification.mutateAsync({ itemId, body });
        }}
        onSetLock={async (itemId, locked, reason) => {
          await setLock.mutateAsync({ itemId, locked, reason });
        }}
        onAskPm={askPm}
      />
    </div>
  );
}
