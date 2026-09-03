import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Lock, MessageSquare, SquareCheck, SquarePen } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

import {
  api,
  type ActiveRun,
  type BacklogItem,
  type ClarificationResolveBody,
  type Project,
  type RunMode,
} from "../../api/client";
import {
  acceptanceCriteria,
  askPmPrefill,
  isBlocked,
  isLocked,
  requestEditsPrefill,
  runsForItem,
} from "../../lib/backlog";
import { providerNouns } from "../../lib/providerNouns";
import { historyRunHref, liveRunHref } from "../../lib/runs";
import { AgentStatus } from "../AgentStatus";
import { ConsoleLabel } from "../overview/bits";
import { OUTCOME_META, parkReason, runOutcome } from "../../lib/validation";
import { ItemStatusBadge } from "./BacklogCard";
import { CostModeSelect, ModeSelect } from "./RunLaunchControls";
import { severityBadge } from "../StatusBadge";
import { ClarifyCard } from "./ClarifyCard";
import { RunPreviewCard } from "./RunPreviewCard";

function LimitSlider({
  label,
  value,
  min,
  max,
  onChange,
  display,
  hint,
  step = 1,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
  display: string;
  hint: string;
  step?: number;
}) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-foreground/90">{label}</span>
        <span className="font-mono text-xs text-primary">{display}</span>
      </div>
      <Slider
        aria-label={label}
        value={value}
        min={min}
        max={max}
        step={step}
        onValueChange={onChange}
      />
      <p className="text-[10px] leading-relaxed text-muted-foreground/60">{hint}</p>
    </div>
  );
}

function fmtDate(at: string | null): string | null {
  if (!at) return null;
  const d = new Date(at);
  return Number.isNaN(d.getTime()) ? null : d.toLocaleDateString();
}

const TEXTAREA_CLS =
  "min-h-24 w-full rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

/** Item detail drawer: the card stays compact on the board, everything needed
 *  to decide lives here. Content derives from live query data; an edit draft
 *  is local and never overwritten by polling. No delete/archive — there is no
 *  endpoint yet (Settings-era work). */
/** Duplicated across both components below; named once so a body field cannot be added
 *  to one signature and missed at the other (ADR-0091). */
type ResolveClarification = (itemId: number, body: ClarificationResolveBody) => Promise<void>;

export function BacklogItemSheet({
  item,
  project,
  activeRun,
  runDisabled,
  patchPending,
  onClose,
  onRun,
  onPatch,
  onSetDependencies,
  onSetLock,
  onResolveClarification,
  onAskPm,
}: {
  item?: BacklogItem;
  project: Project;
  activeRun?: ActiveRun;
  runDisabled: boolean;
  patchPending: boolean;
  onClose: () => void;
  onRun: (
    item: BacklogItem,
    mode?: RunMode,
    limits?: {
      max_iterations?: number | null;
      budget_tokens?: number | null;
      budget_usd?: number | null;
      cost_mode?: string | null;
    },
    override?: boolean,
  ) => void;
  onPatch: (itemId: number, body: Partial<BacklogItem>) => Promise<void>;
  onSetDependencies: (itemId: number, dependsOn: number[]) => Promise<void>;
  onSetLock: (itemId: number, locked: boolean, reason?: string) => Promise<void>;
  onResolveClarification: ResolveClarification;
  onAskPm: (prefill: string) => void;
}) {
  return (
    <Sheet open={Boolean(item)} onOpenChange={(open) => !open && onClose()}>
      {item && (
        <SheetContent
          side="right"
          className="overflow-y-auto sm:max-w-lg [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin]"
        >
          {/* Keyed by item id so edit state resets when the selection changes. */}
          <SheetBody
            key={item.id}
            item={item}
            project={project}
            activeRun={activeRun}
            runDisabled={runDisabled}
            patchPending={patchPending}
            onRun={onRun}
            onPatch={onPatch}
            onSetDependencies={onSetDependencies}
            onSetLock={onSetLock}
            onResolveClarification={onResolveClarification}
            onAskPm={onAskPm}
          />
        </SheetContent>
      )}
    </Sheet>
  );
}

function SheetBody({
  item,
  project,
  activeRun,
  runDisabled,
  patchPending,
  onRun,
  onPatch,
  onSetDependencies,
  onSetLock,
  onResolveClarification,
  onAskPm,
}: {
  item: BacklogItem;
  project: Project;
  activeRun?: ActiveRun;
  runDisabled: boolean;
  patchPending: boolean;
  onRun: (
    item: BacklogItem,
    mode?: RunMode,
    limits?: {
      max_iterations?: number | null;
      budget_tokens?: number | null;
      budget_usd?: number | null;
      cost_mode?: string | null;
    },
    override?: boolean,
  ) => void;
  onPatch: (itemId: number, body: Partial<BacklogItem>) => Promise<void>;
  onSetDependencies: (itemId: number, dependsOn: number[]) => Promise<void>;
  onSetLock: (itemId: number, locked: boolean, reason?: string) => Promise<void>;
  onResolveClarification: ResolveClarification;
  onAskPm: (prefill: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [mode, setMode] = useState<RunMode>("guided");
  // Limits: iterations 1–25 (25 = unlimited); tokens in thousands 25–500
  // (500 = unlimited); spend $1–$100 (100 = no cap). Defaults are generous
  // safety nets — a typical item is a few thousand tokens.
  const [iters, setIters] = useState(3);
  const [tokensK, setTokensK] = useState(200);
  const [spend, setSpend] = useState(100);
  // Cost-mode routing tier (#7): which per-role model profile the run uses.
  const { data: costModes } = useQuery({
    queryKey: ["cost-modes"],
    queryFn: () => api.getCostModes(),
  });
  const [costMode, setCostMode] = useState<string | null>(null);
  useEffect(() => {
    if (costModes && costMode === null) setCostMode(costModes.default_cost_mode);
  }, [costModes, costMode]);
  // Server-enforced ceiling on revisions — the slider caps here so it can't send a
  // value the server would clamp (and that once crashed the run as GraphRecursionError).
  const { data: appConfig } = useQuery({ queryKey: ["app-config"], queryFn: () => api.config() });
  const iterCeiling = appConfig?.max_iterations_ceiling ?? 12;
  // Which forge this project delivers to (ADR-0112) — the "Review context" link below used to
  // hardcode "merge request" regardless (S4).
  const { data: capability } = useQuery({
    queryKey: ["delivery-capability", project.id],
    queryFn: () => api.projectDeliveryCapability(project.id),
  });
  const nouns = providerNouns(capability?.provider);
  const runLimits = {
    max_iterations: Math.min(iters, iterCeiling),
    budget_tokens: tokensK >= 500 ? null : tokensK * 1000,
    budget_usd: spend >= 100 ? null : spend,
    cost_mode: costMode,
  };
  const [draft, setDraft] = useState({
    title: item.title,
    description: item.description,
    acceptance: item.acceptance,
  });
  // Dependency editing: a local draft set toggled from the other items, persisted
  // on Save. blocked_by (server-derived) marks which are not yet delivered.
  const others = (project.backlog ?? []).filter((i) => i.id !== item.id);
  const [clarifyBusy, setClarifyBusy] = useState(false);
  const [depsDraft, setDepsDraft] = useState<number[]>(item.depends_on ?? []);
  const [depsSaving, setDepsSaving] = useState(false);
  const unmet = new Set(item.blocked_by ?? []);
  const depsChanged =
    depsDraft.length !== (item.depends_on?.length ?? 0) ||
    depsDraft.some((id) => !(item.depends_on ?? []).includes(id));
  function toggleDep(id: number) {
    setDepsDraft((d) => (d.includes(id) ? d.filter((x) => x !== id) : [...d, id]));
  }
  async function saveDeps() {
    setDepsSaving(true);
    try {
      await onSetDependencies(item.id, depsDraft);
    } finally {
      setDepsSaving(false);
    }
  }

  // Soft lock: a normal run is refused, but the operator can unlock or run
  // early with an explicit override.
  const locked = isLocked(item);
  const [lockBusy, setLockBusy] = useState(false);
  async function unlock() {
    setLockBusy(true);
    try {
      await onSetLock(item.id, false);
    } finally {
      setLockBusy(false);
    }
  }

  const live = activeRun && activeRun.item_id === item.id;
  const criteria = acceptanceCriteria(item.acceptance);
  const itemRuns = runsForItem(project.runs ?? [], item);
  /* F69 (#97): the DELIVERING attempt, not the latest one. A card reading "latest run · cancelled"
     while the run that actually delivered the item passed is the least useful fact to show a
     reviewer — the same defect class fixed on the Overview proof panel (ADR-0109). Falls back to
     the newest attempt when nothing was ever approved, so the link never disappears. */
  const reviewRun =
    itemRuns.find((r) => r.status === "APPROVED") ?? itemRuns[0] ?? null;
  const created = fmtDate(item.created_at);
  const canEdit = item.status !== "in_progress";

  function startEdit() {
    setDraft({ title: item.title, description: item.description, acceptance: item.acceptance });
    setEditing(true);
  }

  async function saveEdit() {
    if (!draft.title.trim()) return;
    await onPatch(item.id, {
      title: draft.title.trim(),
      description: draft.description,
      acceptance: draft.acceptance,
    });
    setEditing(false);
  }

  return (
    <>
      <SheetHeader className="pr-12">
        <div className="flex items-center gap-2">
          <ItemStatusBadge status={item.status} />
          <span className="font-mono text-[10px] text-muted-foreground/60">#{item.id}</span>
        </div>
        {editing ? (
          <Input
            aria-label="Item title"
            className="mt-1 font-medium"
            value={draft.title}
            onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))}
          />
        ) : (
          <SheetTitle className="text-base leading-snug">{item.title}</SheetTitle>
        )}
        {created && <SheetDescription>Created {created}</SheetDescription>}
      </SheetHeader>

      <div className="flex flex-1 flex-col gap-5 px-4">
        <section className="flex flex-col gap-1.5">
          <ConsoleLabel>Description</ConsoleLabel>
          {editing ? (
            <textarea
              aria-label="Item description"
              className={TEXTAREA_CLS}
              value={draft.description}
              onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
            />
          ) : item.description ? (
            <p className="whitespace-pre-wrap text-sm leading-relaxed">{item.description}</p>
          ) : (
            <p className="text-sm text-muted-foreground">No description.</p>
          )}
        </section>

        {item.clarification && (
          <ClarifyCard
            clarification={item.clarification}
            busy={clarifyBusy}
            onResolve={async (body) => {
              setClarifyBusy(true);
              try {
                await onResolveClarification(item.id, body);
              } finally {
                setClarifyBusy(false);
              }
            }}
          />
        )}
        <section className="flex flex-col gap-1.5">
          <ConsoleLabel>
            Acceptance criteria{criteria.length > 0 ? ` · ${criteria.length}` : ""}
          </ConsoleLabel>
          {editing ? (
            <textarea
              aria-label="Acceptance criteria"
              className={cn(TEXTAREA_CLS, "font-mono text-xs")}
              placeholder={"- one criterion per line"}
              value={draft.acceptance}
              onChange={(e) => setDraft((d) => ({ ...d, acceptance: e.target.value }))}
            />
          ) : criteria.length > 0 ? (
            <ul className="flex flex-col gap-1.5">
              {criteria.map((c, i) => (
                <li key={i} className="flex items-start gap-2 text-sm leading-snug">
                  <SquareCheck className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                  <span>{c}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No acceptance criteria yet.</p>
          )}
        </section>

        <section className="flex flex-col gap-1.5">
          <ConsoleLabel>Depends on</ConsoleLabel>
          {locked && (
            <div className="flex flex-col gap-1.5 rounded-lg bg-primary/5 p-2.5 ring-1 ring-primary/20">
              <div className="flex items-center gap-1.5">
                <Lock className="size-3.5 shrink-0 text-primary" />
                <ConsoleLabel className="text-primary/90">Locked</ConsoleLabel>
              </div>
              <p className="text-xs leading-relaxed text-muted-foreground">
                {item.lock_reason
                  ? item.lock_reason
                  : "This item is on hold — a normal run is refused until it's unlocked."}
              </p>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="xs"
                  variant="secondary"
                  disabled={lockBusy}
                  onClick={() => void unlock()}
                >
                  Unlock
                </Button>
                <Button
                  size="xs"
                  variant="ghost"
                  className="text-muted-foreground"
                  disabled={runDisabled}
                  title={
                    runDisabled ? "another item is running on this project" : "run this item despite the lock"
                  }
                  onClick={() => onRun(item, mode, runLimits, true)}
                >
                  Run anyway (override) ▸
                </Button>
              </div>
            </div>
          )}
          {isBlocked(item) && (
            <p className="text-xs text-destructive">
              Blocked — waiting on {item.blocked_by?.length} item(s) to be delivered before this can
              run.
            </p>
          )}
          {others.length === 0 ? (
            <p className="text-sm text-muted-foreground">No other items to depend on.</p>
          ) : (
            <>
              <ul className="flex flex-col gap-1">
                {others.map((o) => {
                  const checked = depsDraft.includes(o.id);
                  return (
                    <li key={o.id}>
                      <label className="flex cursor-pointer items-center gap-2 rounded-md px-1 py-1 hover:bg-muted/40">
                        <input
                          type="checkbox"
                          className="size-3.5 shrink-0 accent-primary"
                          checked={checked}
                          onChange={() => toggleDep(o.id)}
                          aria-label={`Depend on ${o.title}`}
                        />
                        <span className="min-w-0 flex-1 truncate text-sm">{o.title}</span>
                        {checked && unmet.has(o.id) && (
                          <span className="font-mono text-[10px] uppercase text-destructive">
                            waiting
                          </span>
                        )}
                        <ItemStatusBadge status={o.status} />
                      </label>
                    </li>
                  );
                })}
              </ul>
              {depsChanged && (
                <Button
                  size="xs"
                  className="w-fit"
                  disabled={depsSaving}
                  onClick={() => void saveDeps()}
                >
                  Save dependencies
                </Button>
              )}
            </>
          )}
        </section>

        {(live || itemRuns.length > 0) && (
          <section className="flex flex-col gap-1.5">
            <ConsoleLabel>Runs</ConsoleLabel>
            {live && activeRun ? (
              <Link to={liveRunHref(activeRun.run_id, project.id)} className="w-fit">
                <AgentStatus
                  phase={activeRun.phase ?? ""}
                  startedAt={activeRun.started_at ?? null}
                  status="running"
                  compact
                />
              </Link>
            ) : (
              <ul className="flex flex-col gap-1">
                {itemRuns.slice(0, 3).map((r) => (
                  <li key={r.id} className="flex items-center gap-2">
                    <Link
                      to={historyRunHref(r.id, project.id)}
                      className="truncate font-mono text-xs text-foreground/90 hover:text-foreground"
                    >
                      {r.id}
                    </Link>
                    <Badge
                      className={cn(
                        "h-4 px-1.5 font-mono text-[10px] uppercase",
                        severityBadge(OUTCOME_META[runOutcome(r)].severity),
                      )}
                      title={
                        runOutcome(r) === "incomplete"
                          ? (parkReason(r) ?? "no reason recorded")
                          : undefined
                      }
                    >
                      {OUTCOME_META[runOutcome(r)].label}
                    </Badge>
                    <span className="font-mono text-[10px] text-muted-foreground/60">
                      {fmtDate(r.created_at) ?? ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {item.status === "in_review" && project.mr_url && (
          <section className="flex flex-col gap-1.5">
            <ConsoleLabel className="text-primary/90">Review context</ConsoleLabel>
            <Link
              to={`/projects/${project.id}/delivery?view=changes`}
              className="w-fit text-sm text-primary hover:underline"
            >
              View accumulated changes →
            </Link>
            <a
              href={project.mr_url}
              target="_blank"
              rel="noreferrer"
              className="flex w-fit items-center gap-1 font-mono text-xs text-muted-foreground hover:text-foreground"
            >
              <ExternalLink className="size-3" />
              Open {nouns.request}
            </a>
          </section>
        )}
      </div>

      <SheetFooter>
        {editing ? (
          <div className="flex items-center gap-2">
            <Button size="sm" disabled={patchPending || !draft.title.trim()} onClick={() => void saveEdit()}>
              Save changes
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            {item.status === "todo" && (
              <div className="flex w-full flex-col gap-1.5">
                <ModeSelect mode={mode} onChange={setMode} />
                {costModes && costModes.available.length > 0 && (
                  <CostModeSelect
                    modes={costModes.available}
                    value={costMode ?? costModes.default_cost_mode}
                    onChange={setCostMode}
                  />
                )}
                <RunPreviewCard
                  mode={mode}
                  projectId={project.id}
                  costMode={costMode ?? costModes?.default_cost_mode ?? "balanced"}
                />
                <div className="flex flex-col gap-2 rounded-lg bg-card p-3 ring-1 ring-white/12">
                  <ConsoleLabel>Limits</ConsoleLabel>
                  <LimitSlider
                    label="Revisions"
                    value={Math.min(iters, iterCeiling)}
                    min={1}
                    max={iterCeiling}
                    onChange={setIters}
                    display={iters >= iterCeiling ? `${iterCeiling} · max` : `${iters}`}
                    hint="Reviewer send-backs before the run finalizes."
                  />
                  <LimitSlider
                    label="Max tokens"
                    value={tokensK}
                    min={25}
                    max={500}
                    step={25}
                    onChange={setTokensK}
                    display={tokensK >= 500 ? "Unlimited" : `${tokensK}k`}
                    hint="Parks for approval if the run crosses this many tokens."
                  />
                  <LimitSlider
                    label="Max spend"
                    value={spend}
                    min={1}
                    max={100}
                    onChange={setSpend}
                    display={spend >= 100 ? "No limit" : `$${spend}`}
                    hint="Parks if the run's $ cost crosses this."
                  />
                  <p className="text-[10px] leading-relaxed text-muted-foreground/50">
                    Local models are free — the $ cap applies only to paid/cloud models; the token
                    cap applies to every run.
                  </p>
                </div>
                <div>
                  <Button
                    size="sm"
                    disabled={runDisabled || locked}
                    title={
                      locked
                        ? "locked — unlock or use “Run anyway (override)” above"
                        : runDisabled
                          ? "another item is running on this project"
                          : undefined
                    }
                    onClick={() => onRun(item, mode, runLimits)}
                  >
                    Run item ▸
                  </Button>
                </div>
              </div>
            )}
            {item.status === "in_progress" &&
              (live && activeRun ? (
                <Button size="sm" render={<Link to={liveRunHref(activeRun.run_id, project.id)} />}>
                  View run ▸
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={patchPending}
                  onClick={() => void onPatch(item.id, { status: "todo" })}
                >
                  Reset to todo
                </Button>
              ))}
            {item.status === "in_review" && (
              <>
                {/* F68 (#94): review asked for approval without showing the change. The delivering
                    run WAS reachable — but only as an unlabelled mono run id in the list above,
                    sitting next to this approve button; driving LedgerCLI I hit it by accident
                    twice and was thrown out of the board, losing my place in the queue (case study
                    #2, 2026-08-23). The evidence now has a labelled affordance of its own, placed
                    FIRST so it is read before the decision and is nowhere near the approve button. */}
                {reviewRun && (
                  <Button
                    size="sm"
                    variant="secondary"
                    nativeButton={false}
                    render={<Link to={historyRunHref(reviewRun.id, project.id)} />}
                  >
                    See what changed
                  </Button>
                )}
                <Button
                  size="sm"
                  disabled={patchPending}
                  onClick={() => void onPatch(item.id, { status: "done" })}
                >
                  Approve — mark done
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => onAskPm(requestEditsPrefill(item))}
                >
                  Request edits
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-muted-foreground"
                  disabled={patchPending}
                  onClick={() => void onPatch(item.id, { status: "todo" })}
                >
                  Move back to To do
                </Button>
              </>
            )}
            {item.status === "done" && (
              <Button
                size="sm"
                variant="ghost"
                className="text-muted-foreground"
                disabled={patchPending}
                onClick={() => void onPatch(item.id, { status: "in_review" })}
              >
                Reopen for review
              </Button>
            )}
            {/* F66 (#93). Deferred was a TRAP STATE: the autonomous sweep could put an item here
                and the sheet offered only Edit and Ask PM — no run, no un-defer, no status control
                at all, on a column the board labels "needs attention". Driving the project through
                the UI, the only way out was asking the PM, which had to DELETE and re-create each
                item, destroying its identity and run history — the trade Quincy itself had argued
                against when it locked #88 rather than delete it (case study #2, 2026-08-23).
                No board state the engine can assign may be one the operator cannot leave. */}
            {item.status === "deferred" && (
              <Button
                size="sm"
                disabled={patchPending}
                onClick={() => void onPatch(item.id, { status: "todo" })}
              >
                Put back in the queue
              </Button>
            )}
            {canEdit && (
              <Button size="sm" variant="ghost" className="text-muted-foreground" onClick={startEdit}>
                <SquarePen data-icon="inline-start" />
                Edit
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              className="text-muted-foreground"
              onClick={() => onAskPm(askPmPrefill(item))}
            >
              <MessageSquare data-icon="inline-start" />
              Ask PM
            </Button>
          </div>
        )}
      </SheetFooter>
    </>
  );
}
