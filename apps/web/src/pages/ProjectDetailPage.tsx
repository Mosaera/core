import { useQuery } from "@tanstack/react-query";
import { Navigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { Spinner } from "../components/AgentStatus";
import { QueryState } from "../components/QueryState";
import { DeliverySection } from "../components/delivery/DeliverySection";
import { StartWorkspace } from "../components/start/StartWorkspace";
import { isInitializing } from "../lib/overview";
import { BacklogWorkspace } from "../components/backlog/BacklogWorkspace";
import { ProjectOverview } from "../components/overview/ProjectOverview";
import { PmWorkspace } from "../components/pm/PmWorkspace";
import { RunsSection } from "../components/runs/RunsSection";
import { ProjectSettingsWorkspace } from "../components/settings/ProjectSettingsWorkspace";

/* Sections are URL slugs (/projects/:id/:section) so the sidebar drives them
   and they deep-link; the values are the labels the body conditionals use. */
const SECTIONS: Record<string, string> = {
  start: "Start",
  overview: "Overview",
  pm: "PM",
  backlog: "Backlog",
  delivery: "Delivery",
  runs: "Runs",
  settings: "Settings",
};

/* Phase 9: Changes + Artifacts folded into Delivery, Activity folded into Runs, as internal
   views (`DeliverySection` / `RunsSection`) rather than their own tabs. Their old routes keep
   working — every deep link and bookmark redirects to the new section with the matching
   `?view=`, so this map is the ONLY thing that changed about them. */
const RETIRED_SECTION_REDIRECTS: Record<string, string> = {
  changes: "delivery?view=changes",
  artifacts: "delivery?view=artifacts",
  activity: "runs?view=activity",
};

export function ProjectDetailPage() {
  const { id = "", section = "overview" } = useParams();

  const projectQuery = useQuery({
    queryKey: ["project", id],
    queryFn: () => api.getProject(id),
    // Keep polling for the WHOLE working cycle: intake, decomposition, any item
    // running, and — crucially — while an autonomous run still has items to do
    // (so the board updates in the gap between one item finishing and the next
    // starting, instead of freezing until a manual refresh).
    refetchInterval: (q) => {
      const p = q.state.data;
      if (!p) return false;
      if (p.status === "draft" || p.status === "drafting") return 2000;
      const backlog = p.backlog ?? [];
      const running = backlog.some((i) => i.status === "in_progress");
      const hasTodo = backlog.some((i) => i.status === "todo");
      const decomposing = p.status === "active" && backlog.length === 0;
      const autonomousCycle = p.autonomous && (running || hasTodo);
      return running || autonomousCycle || decomposing ? 2000 : false;
    },
  });
  const { data: project, error } = projectQuery;

  // Live agent status for this project's in-flight run (in-memory sessions).
  const { data: active } = useQuery({
    queryKey: ["active-runs"],
    queryFn: () => api.activeRuns(),
    refetchInterval: 2000,
  });
  const activeRun = (active?.runs ?? []).find(
    (r) => r.project_id === id && (r.status === "running" || r.status === "awaiting_approval"),
  );

  if (section in RETIRED_SECTION_REDIRECTS) {
    return <Navigate to={`/projects/${id}/${RETIRED_SECTION_REDIRECTS[section]}`} replace />;
  }
  const tab = SECTIONS[section];

  if (!tab) {
    return <Navigate to={`/projects/${id}/overview`} replace />;
  }
  if (error) {
    return <QueryState query={projectQuery} errorLabel="Couldn't load this project">{null}</QueryState>;
  }
  if (!project) {
    return (
      <div className="flex items-center justify-center gap-2 px-5 py-16 font-mono text-[13px] text-muted-foreground">
        <Spinner /> loading…
      </div>
    );
  }

  // Initialize phase: only Start (+ Settings) are reachable until the backlog is
  // built; once active, Start disappears.
  const initializing = isInitializing(project.status);
  if (initializing && section !== "start" && section !== "settings") {
    return <Navigate to={`/projects/${id}/start`} replace />;
  }
  if (!initializing && section === "start") {
    return <Navigate to={`/projects/${id}/overview`} replace />;
  }

  if (tab === "Start") {
    return <StartWorkspace project={project} />;
  }
  if (tab === "Overview") {
    return <ProjectOverview project={project} activeRun={activeRun} />;
  }

  // Every tab is a workspace; the breadcrumb (AppHeader) carries project
  // identity. The legacy page-head is gone — Delete Project lives in
  // Settings' danger zone.
  return (
    <>
      {tab === "Backlog" && <BacklogWorkspace project={project} activeRun={activeRun} />}
      {tab === "PM" && <PmWorkspace project={project} />}
      {tab === "Delivery" && <DeliverySection project={project} />}
      {tab === "Runs" && <RunsSection project={project} activeRun={activeRun} />}
      {tab === "Settings" && <ProjectSettingsWorkspace project={project} />}
    </>
  );
}
