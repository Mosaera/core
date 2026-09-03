import { useParams } from "react-router-dom";

import { RunWorkbench } from "../components/runs/RunWorkbench";

/** The run's live page — the Live Workbench. Thin wrapper: the workbench owns
 *  the poll-authoritative stream, the gate, evidence, and actions.
 *
 *  Global route is /runs/:id; the project-nested route is
 *  /projects/:id/runs/:runId — so when runId is present, :id is the project. */
export function RunPage() {
  const { id, runId } = useParams();
  const rid = runId ?? id ?? "";
  const projectId = runId ? id : undefined;
  return <RunWorkbench rid={rid} projectId={projectId} />;
}
