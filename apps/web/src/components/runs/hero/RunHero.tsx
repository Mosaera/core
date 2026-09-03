import { ArrowLeft, ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";

import { CopyButton } from "@/components/ui/CopyButton";
import { cn } from "@/lib/utils";

import type { LedgerRow } from "../../../lib/ledger";
import { taskBody, taskTitle } from "../../../lib/runs";
import { MODE_LABEL } from "../evidence";
import { DecisionHero } from "./DecisionHero";
import type { HeroVariant } from "./heroState";
import { DeliveredHero, RunningHero, TerminatedHero } from "./heroVariants";

const CHIP: Record<HeroVariant["kind"], { label: (v: HeroVariant) => string; cls: string }> = {
  delivered: { label: () => "Delivered", cls: "text-success" },
  "needs-you": {
    label: (v) =>
      v.kind === "needs-you" && v.flavor === "budget" ? "Budget reached" : "Needs your decision",
    cls: "text-amber-600 dark:text-amber-400",
  },
  running: { label: () => "Working", cls: "text-success" },
  terminated: { label: () => "Ended", cls: "text-muted-foreground" },
};

/** The state-adaptive hero: the page IS whatever the run is right now — the
 *  verdict, the decision, live progress, or an honest ending. Unboxed by design:
 *  a chip, a big title, and the variant body in open space. */
export function RunHero({
  rid,
  projectId,
  task,
  variant,
  rows,
  mode,
  revisions,
  busy = false,
  onDecide,
  autoAllowTests,
  onAutoAllowTests,
  onCancel,
  mergeHref,
}: {
  rid: string;
  projectId?: string;
  task: string | undefined;
  variant: HeroVariant;
  rows: LedgerRow[];
  mode?: string;
  revisions?: number;
  busy?: boolean;
  onDecide?: (approve: boolean, feedback: string) => void;
  autoAllowTests?: boolean;
  onAutoAllowTests?: (on: boolean) => void;
  onCancel?: () => void;
  mergeHref?: string;
}) {
  const chip = CHIP[variant.kind];
  const settled = variant.kind === "delivered" || variant.kind === "terminated";
  // "finished {ts}" and the patch link retired from this row 2026-08-22 (redundancy audit):
  // RecordFooter closes every settled page with both — the sealed record owns its identity.
  // The rid stays in both places on purpose (identity earns two renders).
  const metaParts = [
    revisions && revisions > 0 ? `${revisions} revision${revisions === 1 ? "" : "s"}` : null,
    mode ? (MODE_LABEL[mode] ?? mode).toLowerCase() : null,
  ].filter(Boolean);

  return (
    <header className="flex flex-col gap-4 pb-2 pt-1">
      <Link
        to={projectId ? `/projects/${projectId}/runs` : "/"}
        className="flex w-fit items-center gap-1 font-mono text-[11px] text-muted-foreground/70 hover:text-foreground"
      >
        <ArrowLeft className="size-3" />
        {projectId ? "back to runs" : "projects"}
      </Link>

      <div className="flex flex-col gap-2.5">
        {/* One statement of the outcome per page: a settled run says it once, in
            the verdict sentence below (which carries the honesty nuance the chip
            can't). The chip stays where it is the only status signal. */}
        {!settled && (
          <div className="flex items-center gap-2">
            <span aria-hidden className={cn("text-[10px] leading-none", chip.cls)}>
              {variant.kind === "running" ? <PulseDot /> : "●"}
            </span>
            <span
              className={cn("font-mono text-[11px] uppercase tracking-[0.14em]", chip.cls)}
              role="status"
            >
              {chip.label(variant)}
            </span>
          </div>
        )}
        <h1 className="max-w-4xl text-3xl font-semibold leading-tight tracking-tight text-foreground">
          {taskTitle(task)}
        </h1>
        {taskBody(task) && (
          /* The description + acceptance criteria — one disclosure away, never the headline.
             The full paragraph as an H1 was the Firehose Audit's #1 ruling and outlived three
             redesign phases before the owner caught it in the after-screenshots. */
          <details className="group/task max-w-4xl">
            <summary className="flex cursor-pointer list-none items-center gap-2 font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground hover:text-foreground [&::-webkit-details-marker]:hidden">
              full task & acceptance criteria
              <span className="font-mono text-[10px] text-muted-foreground/60 transition-transform group-open/task:rotate-180">
                ▾
              </span>
            </summary>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
              {taskBody(task)}
            </p>
          </details>
        )}
      </div>

      {variant.kind === "delivered" && <DeliveredHero badge={variant.badge} rows={rows} />}
      {variant.kind === "running" && (
        <RunningHero phase={variant.phase} startedAt={variant.startedAt} rows={rows} />
      )}
      {variant.kind === "terminated" && (
        <TerminatedHero
          status={variant.status}
          reason={variant.reason}
          reasonIsFull={variant.reasonIsFull}
        />
      )}
      {variant.kind === "needs-you" && onDecide && (
        <DecisionHero
          gate={variant.gate}
          flavor={variant.flavor}
          busy={busy}
          onDecide={onDecide}
          autoAllowTests={autoAllowTests}
          onAutoAllowTests={onAutoAllowTests}
        />
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 font-mono text-[11px] text-muted-foreground/70">
        <span className="flex items-center gap-1">
          {rid}
          <CopyButton text={rid} label="Copy run id" className="size-5" iconClassName="size-3" />
        </span>
        {metaParts.map((p, i) => (
          <span key={i}>{p}</span>
        ))}
        {/* #116: the stop control belongs in the row EVERY non-terminal variant renders. It used to
            live inside RunningHero alone, so it disappeared exactly when a run parked — and the only
            way to get it back was to answer the gate, spending another model turn on the run you had
            decided to abandon. `onCancel` is already undefined once the run settles, so terminal
            states render nothing without a second condition here. */}
        {onCancel && (
          <button
            onClick={onCancel}
            className="border-0 bg-transparent p-0 font-mono text-[11px] text-muted-foreground/60 hover:text-destructive"
          >
            cancel run
          </button>
        )}
        {/* Delivered ONLY: a park committed nothing, so "merge from the project"
            would be a lie there. */}
        {variant.kind === "delivered" && mergeHref && (
          <Link to={mergeHref} className="flex items-center gap-1 text-primary/90 hover:underline">
            <ExternalLink className="size-3" />
            merge from the project
          </Link>
        )}
      </div>
    </header>
  );
}

function PulseDot() {
  return (
    <span className="relative flex size-2">
      <span className="absolute inline-flex size-full animate-ping rounded-full bg-success/60" />
      <span className="relative inline-flex size-2 rounded-full bg-success" />
    </span>
  );
}

/** The hairline rule between a needs-you hero and the story beneath it. */
export function StorySoFarRule() {
  return (
    <div className="flex items-center gap-3 py-1">
      <span aria-hidden className="h-px flex-1 bg-border/60" />
      <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground/50">
        the story so far
      </span>
      <span aria-hidden className="h-px flex-1 bg-border/60" />
    </div>
  );
}
