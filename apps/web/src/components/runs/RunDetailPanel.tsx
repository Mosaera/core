import { useQuery } from "@tanstack/react-query";
import { Activity, ChevronDown, MessageSquare } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { taskTitle } from "../../lib/runs";
import { cn } from "@/lib/utils";

import { api, type ActiveRun, type HistoryRun, type Project } from "../../api/client";
import { CostBreakdown } from "../CostBreakdown";
import { backlogItemForRun, runCardBadge } from "../../lib/changes";
import { parseDiff } from "../../lib/diff";
import {
  diagnoseValidationPrefill,
  explainRunPrefill,
  historyRunHref,
  liveRunHref,
  parkedRunPrefill,
  parseValidationPlan,
  validationVerdict,
  type VerdictKind,
} from "../../lib/runs";
import { AgentStatus } from "../AgentStatus";
import { severityBadge } from "../StatusBadge";
import { ConsoleLabel, EmptyNote } from "../overview/bits";
import { VERDICT_REASON_CLASS } from "../../lib/verdict";
import { ReceiptCard, receiptFromDetail } from "./ReceiptCard";
import { RunDiagnosisCard } from "./RunDiagnosisCard";

const VERDICT_CLS: Record<VerdictKind, string> = {
  pass: "text-success",
  failed: "text-destructive",
  "no-tests": "text-muted-foreground",
  unavailable: "text-muted-foreground",
  unverified: "text-muted-foreground",
  "no-evidence": "text-muted-foreground",
  pending: "text-muted-foreground",
};

function fmtDate(at: string | null): string | null {
  if (!at) return null;
  const d = new Date(at);
  return Number.isNaN(d.getTime()) ? null : d.toLocaleDateString();
}

/** Persistent right panel: a preview of the selected run — status, honest
 *  validation verdict from real evidence, changed files, and actions. Links
 *  out to the full run view; never duplicates it. Sectioned so a future
 *  Validation Planner (plan/commands/evidence) can slot in below the verdict. */
export function RunDetailPanel({
  run,
  latest,
  project,
  activeRun,
  onAskPm,
  onCancel,
}: {
  run?: HistoryRun;
  latest: boolean;
  project: Project;
  activeRun?: ActiveRun;
  onAskPm: (prefill: string) => void;
  onCancel: (runId: string) => void;
}) {
  const settled = run != null && run.status !== "RUNNING";
  const { data: detail, isLoading } = useQuery({
    // Same key + fetcher as RunDetailPage/ChangeDetailSheet — caches shared.
    queryKey: ["run", run?.id],
    queryFn: () => api.runDetail(run!.id),
    // Live runs have an incomplete durable record; their home is /runs/:id.
    enabled: settled,
  });
  const [costOpen, setCostOpen] = useState(false);

  if (!run) {
    return (
      <section className="flex min-h-0 flex-col rounded-lg bg-card p-4 ring-1 ring-white/12">
        <EmptyNote icon={Activity}>No run selected.</EmptyNote>
      </section>
    );
  }

  const badge = runCardBadge(run);
  const live = run.status === "RUNNING" && activeRun && activeRun.run_id === run.id;
  const item = backlogItemForRun(run, project.backlog ?? []);
  const verdict = validationVerdict(detail, run);
  const plan = parseValidationPlan(detail);
  const receipt = receiptFromDetail(detail);
  // Evidence rows are per validation step (each self-headed with "[step …]").
  const output = (detail?.test_results ?? []).map((r) => r.output).join("\n\n");
  const runFiles = detail
    ? parseDiff(detail.repo_changes[0]?.diff ?? "").filter((f) => f.path)
    : [];
  const created = fmtDate(run.created_at);
  const metaParts = [
    run.id,
    run.commit_sha ? run.commit_sha.slice(0, 8) : null,
    run.branch || null,
    created,
    run.iterations > 0 ? `${run.iterations} iteration${run.iterations === 1 ? "" : "s"}` : null,
  ].filter(Boolean);

  return (
    <section
      aria-label="Run detail"
      className="flex min-h-0 flex-col gap-4 overflow-y-auto rounded-lg bg-card p-4 ring-1 ring-white/12 [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin]"
    >
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge className={cn("font-mono text-[10px] uppercase", severityBadge(badge.tone))}>
            {badge.label}
          </Badge>
          {latest && (
            <Badge className={cn("font-mono text-[10px] uppercase", severityBadge("neutral"))}>
              Latest
            </Badge>
          )}
          {live && (
            <Link to={liveRunHref(activeRun.run_id, activeRun.project_id)}>
              <AgentStatus
                phase={activeRun.phase ?? ""}
                startedAt={activeRun.started_at ?? null}
                status="running"
                compact
              />
            </Link>
          )}
        </div>
        <h2 className="text-base font-medium leading-snug">{taskTitle(run.task)}</h2>
        <p className="font-mono text-xs text-muted-foreground">{metaParts.join(" · ")}</p>
      </header>

      {item && (
        <section className="flex flex-col gap-1.5">
          <ConsoleLabel>Backlog item</ConsoleLabel>
          <Link
            to={`/projects/${project.id}/backlog`}
            className="w-fit text-sm text-foreground/90 hover:text-foreground hover:underline"
          >
            #{item.id} · {item.title}
          </Link>
        </section>
      )}

      <section className="flex flex-col gap-1.5">
        <ConsoleLabel>Validation</ConsoleLabel>
        {settled && isLoading ? (
          <Skeleton className="h-4 w-1/2" />
        ) : (
          <>
            <p className={cn("text-sm font-medium", VERDICT_CLS[verdict.kind])}>{verdict.label}</p>
            {verdict.helper && (
              <p className="text-xs leading-relaxed text-muted-foreground">{verdict.helper}</p>
            )}
            {plan && (
              <div className="mt-1 flex flex-col gap-1 rounded-md bg-muted/30 p-2">
                <p className="font-mono text-[10px] uppercase tracking-wide text-muted-foreground/70">
                  Validation plan · {plan.project_type ?? "unknown"}
                </p>
                {plan.reason && (
                  <p className="text-[11px] leading-relaxed text-muted-foreground">{plan.reason}</p>
                )}
                {(plan.results ?? []).length > 0 && (
                  <ul className="flex flex-col gap-0.5">
                    {(plan.results ?? []).map((step, i) => (
                      <li key={i} className="flex items-center gap-2 font-mono text-[11px]">
                        <span
                          className={cn(
                            "size-1.5 shrink-0 rounded-full",
                            step.ok ? "bg-success" : "bg-destructive",
                          )}
                          aria-hidden
                        />
                        <span className="text-foreground/80">{step.name}</span>
                        <span className="text-muted-foreground/60">
                          {step.timed_out ? "TIMED OUT" : `exit code ${step.exit_code}`}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </>
        )}
        {output && (
          <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded-md bg-background p-2 font-mono text-[11px] leading-relaxed text-foreground/80 [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin]">
            {output}
          </pre>
        )}
      </section>

      {/* How it ended (#75). Above the receipt on purpose: the receipt records what a human's
          approval put on record, which only exists for a run that REACHED the gate. This says why
          the run ended at all, which is the first question about a run that didn't deliver. */}
      {(detail?.diagnosis ?? run.diagnosis) && (
        <RunDiagnosisCard diagnosis={(detail?.diagnosis ?? run.diagnosis)!} />
      )}

      {/* Redundancy audit 2026-08-22: the diagnosis card above already renders the gate reasons,
          so an expanded receipt said the same sentences twice in one pane. The receipt collapses
          ONLY when the diagnosis actually carries reasons (live pre-redesign runs exist whose
          diagnosis had none while the receipt held four — see VerdictBand's incident note) and
          none of its reasons are tamper/not_run class: bad news never starts folded (puncture
          rule). ADR-0063 requires the receipt inline on run pages, not expanded; this pane shows
          settled runs, so ADR-0082 §1 (open gates) does not bind here. */}
      {receipt &&
        (() => {
          const diagReasons = (detail?.diagnosis ?? run.diagnosis)?.gate_reasons ?? [];
          const punctures = receipt.reasons.some((r) =>
            ["tamper", "not_run"].includes(VERDICT_REASON_CLASS[r] ?? "objection"),
          );
          const collapsible = diagReasons.length > 0 && !punctures;
          if (!collapsible) {
            return (
              <section className="flex flex-col gap-1.5">
                <ConsoleLabel>Receipt</ConsoleLabel>
                <ReceiptCard receipt={receipt} compact />
              </section>
            );
          }
          return (
            <details className="group/receipt">
              <summary className="flex cursor-pointer list-none items-center gap-2 [&::-webkit-details-marker]:hidden">
                <ConsoleLabel>Receipt</ConsoleLabel>
                <span className="ml-auto font-mono text-[10px] text-muted-foreground/60 transition-transform group-open/receipt:rotate-180">
                  ▾
                </span>
              </summary>
              <div className="mt-1.5">
                <ReceiptCard receipt={receipt} compact />
              </div>
            </details>
          );
        })()}

      {detail?.cost && detail.cost.total_tokens > 0 && (
        <section className="flex flex-col gap-1.5">
          {/* Lean inline: dollars and tokens (separate figures — a free local
              model is $0 with real token usage). Drill down for the breakdown. */}
          <button
            type="button"
            aria-expanded={costOpen}
            onClick={() => setCostOpen((o) => !o)}
            className="flex w-full cursor-pointer items-center justify-between gap-2 border-0 bg-transparent p-0 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ConsoleLabel>Cost</ConsoleLabel>
            <span className="flex items-center gap-3 font-mono text-sm">
              {/* Real spend when there is any; otherwise the imputed on-box figure, marked so
                  a shadow price can never be mistaken for a bill. */}
              <span className="text-foreground">
                {detail.cost.usd > 0 ? `$${detail.cost.usd.toFixed(4)}` : "$0.00"}
              </span>
              {detail.cost.usd === 0 && (detail.cost.shadow_usd ?? 0) > 0 && (
                <span
                  className="text-muted-foreground"
                  title="Imputed cost of on-box models — not billed"
                >
                  ~${detail.cost.shadow_usd!.toFixed(4)} shadow
                </span>
              )}
              <span className="text-foreground/90">
                {detail.cost.total_tokens.toLocaleString()}{" "}
                <span className="text-muted-foreground">tok</span>
              </span>
              <ChevronDown
                className={cn(
                  "size-3.5 shrink-0 text-muted-foreground/60 transition-transform",
                  costOpen && "rotate-180",
                )}
              />
            </span>
          </button>
          {costOpen && (
            <div className="flex flex-col gap-2 border-t border-border/40 pt-2">
              <p className="font-mono text-[11px] text-muted-foreground">
                {detail.cost.input_tokens.toLocaleString()} in ·{" "}
                {detail.cost.output_tokens.toLocaleString()} out · {detail.cost.calls} call
                {detail.cost.calls === 1 ? "" : "s"}
              </p>
              <CostBreakdown label="By agent" rows={detail.cost.by_agent} nameKey="agent" />
              <CostBreakdown label="By model" rows={detail.cost.by_model} nameKey="model" />
            </div>
          )}
        </section>
      )}

      <section className="flex flex-col gap-1.5">
        <ConsoleLabel>Changed files in this run</ConsoleLabel>
        {settled && isLoading ? (
          <div className="flex flex-col gap-1.5">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        ) : runFiles.length > 0 ? (
          <ul className="flex flex-col gap-1">
            {runFiles.map((f) => (
              <li key={f.path} className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate font-mono text-xs text-foreground/90">
                  {f.path}
                </span>
                <span className="font-mono text-[10px] tabular-nums">
                  <span className="text-success">+{f.adds}</span>{" "}
                  <span className="text-destructive">−{f.dels}</span>
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">
            {run.status === "RUNNING"
              ? "Files appear when the run records its changes."
              : "No per-run diff was recorded for this run."}
          </p>
        )}
      </section>

      <footer className="mt-auto flex flex-wrap items-center gap-2 pt-2">
        <Button
          size="sm"
          variant="secondary"
          nativeButton={false}
          render={
            <Link
              to={
                live
                  ? liveRunHref(activeRun.run_id, activeRun.project_id)
                  : historyRunHref(run.id, run.project_id)
              }
            />
          }
        >
          View full run
        </Button>
        {run.status === "RUNNING" && (
          <Button size="sm" variant="destructive" onClick={() => onCancel(run.id)}>
            Cancel
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          className="text-muted-foreground"
          onClick={() => onAskPm(explainRunPrefill(run))}
        >
          <MessageSquare data-icon="inline-start" />
          Ask PM to explain this run
        </Button>
        {verdict.kind === "failed" && (
          <Button
            size="sm"
            variant="ghost"
            className="text-muted-foreground"
            onClick={() => onAskPm(diagnoseValidationPrefill(run))}
          >
            Ask PM to diagnose validation failure
          </Button>
        )}
        {/* Every non-delivered end gets the park handoff — INCOMPLETE (the honest
            park) had NO PM button before this, the most common dead-end of all. */}
        {["INCOMPLETE", "CANCELLED", "ERROR", "NOT APPROVED"].includes(run.status) && (
          <Button
            size="sm"
            variant="ghost"
            className="text-muted-foreground"
            onClick={() => onAskPm(parkedRunPrefill(run, detail?.diagnosis ?? run.diagnosis))}
          >
            Ask PM how to unblock
          </Button>
        )}
        {/* Merge language lives on the Changes tab; this is only the handoff. */}
        <Button
          size="sm"
          variant="ghost"
          className="text-muted-foreground"
          nativeButton={false}
          render={<Link to={`/projects/${project.id}/delivery?view=changes`} />}
        >
          View merge readiness
        </Button>
      </footer>
    </section>
  );
}
