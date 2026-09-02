import { Link, useNavigate } from "react-router-dom";

import { cn } from "@/lib/utils";

import type { ActiveRun, Project } from "../../api/client";
import { historyRunHref } from "../../lib/runs";
import {
  thrashing,
  triage,
  triageBuckets,
  type TriageEntry,
  type TriageVerb,
} from "../../lib/triage";
import { ConsoleLabel, SeverityDot } from "./bits";

/** Where each verb's action actually lives. The destination IS the verb — a bucket that sends the
 *  operator somewhere they cannot perform the action is a label pretending to be a worklist. */
const DEST: Record<TriageVerb, "backlog" | "run" | "pm"> = {
  answer: "backlog", // the ClarifyCard, where the ask is answered
  review: "backlog", // the Review action on the item
  respecify: "pm", // Quincy re-scopes; retrying hits the same wall
  environment: "run", // the run shows WHICH check did not run
  judge: "run", // the evidence the verdict was read from
  blocked: "backlog",
  run: "backlog",
  inspect: "run",
};

/** The operator's worklist: every open item bucketed by the one intervention it needs
 *  (`lib/triage.ts`). This replaced the single rule-derived "next action" and the latest-run
 *  attention strip, which between them named one thing to do and counted attempts rather than
 *  items — so a project with three different kinds of stuck work said "1 next action". */
export function TriageBand({
  project,
  activeRun,
  onAskPm,
}: {
  project: Project;
  activeRun?: ActiveRun;
  onAskPm: (prefill: string) => void;
}) {
  const navigate = useNavigate();
  const live = new Set(activeRun ? [activeRun.run_id] : []);
  const entries = triage(project.backlog ?? [], project.runs ?? [], live);
  const buckets = triageBuckets(entries);
  const stuck = thrashing(project.backlog ?? [], project.runs ?? []);

  if (buckets.length === 0) {
    return (
      <section aria-label="Worklist" className="rounded-lg bg-card p-4 ring-1 ring-white/12">
        <ConsoleLabel>Worklist</ConsoleLabel>
        <p className="mt-1.5 text-[13px] text-muted-foreground">
          Nothing open needs a decision. Every item is delivered, running, or accepted.
        </p>
      </section>
    );
  }

  function go(e: TriageEntry) {
    const dest = DEST[e.verb];
    if (dest === "pm") {
      const prefill =
        `Backlog item #${e.item.id} ("${e.item.title}") is stuck: ${e.note}. ` +
        `Re-scope or split it so it can be attempted again.`;
      onAskPm(prefill);
      return;
    }
    if (dest === "run" && e.run) {
      navigate(historyRunHref(e.run.id, e.run.project_id));
      return;
    }
    navigate(`/projects/${project.id}/backlog`);
  }

  return (
    <section aria-label="Worklist" className="flex flex-col gap-3">
      {/* Above the ladder: the engine walking into the same wall. #113 returned an identical
          four-reason signature on attempts 1 and 3 and was retried eight times over 27 hours
          before anyone was told (measured 2026-08-22). */}
      {stuck.map((t) => (
        <div
          key={`thrash-${t.item.id}`}
          className="rounded-lg bg-card p-3.5 ring-1 ring-destructive/40"
        >
          <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
            <SeverityDot severity="red" />
            <h3 className="text-sm font-semibold">Stop retrying</h3>
            <span className="min-w-0 flex-1 text-[12.5px] text-muted-foreground">
              The same failure {t.repeats} times running — retrying spends money on the same wall.
            </span>
          </div>
          <button
            type="button"
            onClick={() =>
              navigate(
                `/projects/${project.id}/runs`,
              )
            }
            className="mt-1.5 flex w-full items-baseline gap-2 rounded border-0 bg-transparent px-1 py-1 text-left hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          >
            <span className="min-w-0 flex-1 truncate text-[13px]">
              <span className="font-mono text-[11px] text-muted-foreground">#{t.item.id}</span>{" "}
              {t.item.title}
            </span>
            <span className="shrink-0 font-mono text-[10.5px] text-muted-foreground/70">
              {t.attempts} attempts
            </span>
          </button>
          <p className="px-1 font-mono text-[10.5px] leading-relaxed text-destructive/80">
            {t.signature.map((r) => r.replace(/_/g, " ")).join(" · ")}
          </p>
        </div>
      ))}
      {buckets.map((b) => (
        <div key={b.verb} className="rounded-lg bg-card p-3.5 ring-1 ring-white/12">
          <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
            <SeverityDot severity={b.severity === "neutral" ? "green" : b.severity} />
            <h3 className="text-sm font-semibold">{b.label}</h3>
            <span className="font-mono text-xs tabular-nums text-muted-foreground">
              {b.entries.length}
            </span>
            <span className="min-w-0 flex-1 text-[12.5px] text-muted-foreground">{b.action}</span>
          </div>
          <ul className="mt-2 flex flex-col">
            {b.entries.map((e) => (
              <li key={e.item.id}>
                <button
                  type="button"
                  onClick={() => go(e)}
                  className={cn(
                    "flex w-full items-baseline gap-2 rounded border-0 bg-transparent px-1 py-1 text-left",
                    "hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
                  )}
                >
                  <span className="min-w-0 flex-1 truncate text-[13px]">
                    <span className="font-mono text-[11px] text-muted-foreground">
                      #{e.item.id}
                    </span>{" "}
                    {e.item.title}
                  </span>
                  {e.note && (
                    <span className="shrink-0 font-mono text-[10.5px] text-muted-foreground/70">
                      {e.note}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
          {b.verb === "review" && (
            <Link
              to={`/projects/${project.id}/changes`}
              className="mt-1 inline-block px-1 font-mono text-[11px] text-primary hover:underline"
            >
              see the diffs →
            </Link>
          )}
        </div>
      ))}
    </section>
  );
}
