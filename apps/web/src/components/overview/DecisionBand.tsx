import { ArrowRight, X } from "lucide-react";
import { Link } from "react-router-dom";

import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";

import type { ActiveRun, Project } from "../../api/client";
import { acknowledge, canAcknowledge } from "../../lib/decisionAck";
import { useDecisions } from "../../hooks/useDecisions";
import { attentionItems, lifecycleAction } from "../../lib/overview";
import { thrashing, triage, triageBuckets } from "../../lib/triage";
import { QueryState } from "../QueryState";
import { AttentionStrip } from "./AttentionStrip";
import { DecisionCard } from "./DecisionCard";
import { TriageBand } from "./TriageBand";
import { ConsoleLabel, SeverityDot } from "./bits";

/** THE single "what needs you" region (5C). Composes three data sources, each already its own
 *  derivation — this does not invent a fourth:
 *   - server-derived decisions (ADR-0105) — blocking first, standing (dismissible) after;
 *   - `AttentionStrip`'s project-level facts (a failed run, an open MR, a budget pause);
 *   - `TriageBand`'s worklist — every open backlog item bucketed by the intervention it needs.
 *
 *  Before this, Overview mounted DecisionBand, AttentionStrip, and TriageBand as three
 *  independent sections that could (and did, live) disagree — "Nothing needs you" beside a
 *  worklist with items waiting. Composing them here means exactly one quiet line renders, and
 *  only when all three sources agree there is truly nothing — never a contradiction. */
export function DecisionBand({
  project,
  activeRun,
  mrState = null,
  onAskPm,
}: {
  project: Project;
  activeRun?: ActiveRun;
  mrState?: string | null;
  /** Wired through to the worklist's "re-specify" handoff. Overview always passes this; the
   *  optional default keeps a bare `<DecisionBand project={p} />` call (tests, a future
   *  standalone mount) from crashing rather than requiring every caller to thread it. */
  onAskPm?: (prefill: string) => void;
}) {
  const qc = useQueryClient();
  const decisions = useDecisions(project.id);
  const { blocking, standing, isLoading, isError } = decisions;

  // A failed fetch here is the worst of the 22 silently-empty surfaces (5E): this band is the
  // one place a blocking condition surfaces, so a swallowed error reads as "nothing needs you"
  // when the truth is "we couldn't check".
  if (isError) {
    return (
      <QueryState query={decisions} errorLabel="Couldn't check what needs you">
        {null}
      </QueryState>
    );
  }

  const attention = attentionItems(project, mrState);
  const live = new Set(activeRun ? [activeRun.run_id] : []);
  const entries = triage(project.backlog ?? [], project.runs ?? [], live);
  const buckets = triageBuckets(entries);
  const stuck = thrashing(project.backlog ?? [], project.runs ?? []);
  const hasWorklist = buckets.length > 0 || stuck.length > 0;
  // The project's own lifecycle move (intake / open MR / post-merge) — moved here from NowCard
  // (5C: NowCard is trimmed to "is anything running", nothing else). Only counts against the
  // quiet fallback when it carries an action; an informational stage note ("Building the
  // backlog... no action needed") is compatible with "nothing needs you".
  const lifecycle = lifecycleAction(project);

  // Only the server-derived decisions (blocking/standing) depend on this query — the attention
  // facts, worklist, and lifecycle move all derive synchronously from `project`, so they render
  // immediately rather than waiting on a round trip. Loading only suppresses the quiet fallback,
  // so a page that has real content to show never flashes "nothing needs you" first.
  const nothing =
    !isLoading &&
    blocking.length === 0 &&
    standing.length === 0 &&
    attention.length === 0 &&
    !hasWorklist &&
    !lifecycle?.cta;

  function dismiss(id: string) {
    const d = [...blocking, ...standing].find((x) => x.id === id);
    if (!d || !canAcknowledge(d)) return;
    acknowledge(project.id, d, Date.now());
    // Re-read from cache so the band updates without another GitLab-touching request.
    qc.invalidateQueries({ queryKey: ["decisions", project.id], refetchType: "none" });
    qc.setQueryData(["decisions", project.id], (prev: unknown) => prev);
  }

  return (
    <section aria-label="Needs you" className="flex flex-col gap-2">
      {blocking.length > 0 && <ConsoleLabel>Waiting on you</ConsoleLabel>}
      {blocking.map((d) => (
        <DecisionCard key={d.id} project={project} decision={d} />
      ))}

      <AttentionStrip project={project} mrState={mrState} hideEmpty />

      <TriageBand
        project={project}
        activeRun={activeRun}
        onAskPm={onAskPm ?? (() => {})}
        hideEmpty
      />

      {lifecycle && (
        <div className="flex flex-col gap-1 rounded-lg bg-card p-3.5 ring-1 ring-white/12">
          <ConsoleLabel className="text-[10px]">Project</ConsoleLabel>
          <p className="text-sm font-medium leading-snug">{lifecycle.title}</p>
          <p className="text-[13px] leading-relaxed text-muted-foreground">{lifecycle.reason}</p>
          {lifecycle.cta && (
            <div className="pt-1">
              <Button
                size="sm"
                variant="outline"
                className="border-primary/40 text-primary hover:border-primary/70 hover:bg-primary/10 hover:text-primary"
                render={
                  lifecycle.cta.kind === "external" ? (
                    <a href={lifecycle.cta.to} target="_blank" rel="noreferrer" />
                  ) : (
                    <Link to={`/projects/${project.id}/${lifecycle.cta.to}`} />
                  )
                }
              >
                {lifecycle.cta.label} <ArrowRight />
              </Button>
            </div>
          )}
        </div>
      )}

      {standing.length > 0 && (
        <>
          <ConsoleLabel className="mt-1">Standing</ConsoleLabel>
          {standing.map((d) => (
            <div key={d.id} className="relative">
              <DecisionCard project={project} decision={d} />
              <button
                type="button"
                aria-label={`Dismiss: ${d.title}`}
                onClick={() => dismiss(d.id)}
                className="absolute right-2 top-2 rounded border-0 bg-transparent p-1 text-muted-foreground/50 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
              >
                <X className="size-3.5" />
              </button>
            </div>
          ))}
        </>
      )}

      {nothing && (
        <div className="flex items-center gap-2.5 rounded-lg bg-card px-4 py-2.5 ring-1 ring-white/12">
          <SeverityDot severity="green" />
          <span className="text-[13px] text-muted-foreground">
            Nothing needs you — the record is quiet.
          </span>
        </div>
      )}
    </section>
  );
}
