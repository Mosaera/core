import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { api, type ActiveRun, type Project } from "../../api/client";
import type { PmPrefillState } from "../../lib/backlog";
import { QueryState } from "../QueryState";
import { CharterSummaryCard } from "./CharterSummaryCard";
import { DecisionBand } from "./DecisionBand";
import { ManualStepsCard } from "./ManualStepsCard";
import { NowCard } from "./NowCard";
import { PipelineCard } from "./PipelineCard";
import { ProjectBudgetsCard } from "./ProjectBudgetsCard";
import { ProofCard } from "./ProofCard";
import { ProjectHero } from "./ProjectHero";
import { ProjectMapCard } from "./ProjectMapCard";

/** Project command center (rebuilt 2026-08-13 to the owner's three leads: what's
 *  happening now · health + pipeline · budgets). Desktop: a 2fr/1fr grid; mobile:
 *  single column in DOM order. Data comes from the page's shared project query plus
 *  the section queries reused by other tabs. */
export function ProjectOverview({
  project,
  activeRun,
}: {
  project: Project;
  activeRun?: ActiveRun;
}) {
  const mrQuery = useQuery({
    queryKey: ["mr-status", project.id],
    queryFn: () => api.projectMrStatus(project.id),
    enabled: Boolean(project.mr_url),
  });
  const messagesQuery = useQuery({
    queryKey: ["messages", project.id],
    queryFn: () => api.projectMessages(project.id),
  });

  const navigate = useNavigate();
  const mrState = mrQuery.data?.state ?? null;
  const messages = messagesQuery.data?.messages ?? [];

  function askPm(prefill: string) {
    const state: PmPrefillState = { pmPrefill: prefill };
    navigate(`/projects/${project.id}/pm`, { state });
  }

  return (
    <div>
      <ProjectHero project={project} activeRun={activeRun} messages={messages} />
      {(messagesQuery.isError || mrQuery.isError) && (
        <QueryState
          query={
            messagesQuery.isError
              ? { isLoading: false, isError: true, error: messagesQuery.error, refetch: messagesQuery.refetch }
              : { isLoading: false, isError: true, error: mrQuery.error, refetch: mrQuery.refetch }
          }
          compact
          errorLabel="Couldn't load part of this project's overview"
        >
          {null}
        </QueryState>
      )}
      {/* What needs YOU comes before everything (operator cut): ONE region — server-derived
          decisions (ADR-0105), project-level facts, and the worklist — composed by DecisionBand
          (5C) so the page never shows a contradictory "nothing needs you" beside real work. */}
      <DecisionBand project={project} activeRun={activeRun} mrState={mrState} onAskPm={askPm} />
      <ManualStepsCard project={project} />
      {/* Two independent column STACKS (not row-coupled grid cells): each card packs to its
          own content height, so a short Health card never stretches a hole against a tall
          Now card. Mobile: one column in DOM order. */}
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-4">
          <NowCard project={project} activeRun={activeRun} />
          <PipelineCard
            project={project}
            mrState={mrState}
          />
          {/* The untrusted recon map keeps the page's tail — it is the recon control surface. */}
          <ProjectMapCard projectId={project.id} />
        </div>
        <div className="flex min-w-0 flex-col gap-4">
          {/* The proof radar leads the reference rail — the audit demoted budgets below it. */}
          <ProofCard project={project} />
          <ProjectBudgetsCard project={project} />
          {/* Charter rides the reference rail with Budgets (#42; editing → Settings). */}
          <CharterSummaryCard project={project} />
        </div>
      </div>
    </div>
  );
}
