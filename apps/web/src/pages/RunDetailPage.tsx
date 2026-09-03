import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import { QueryState } from "../components/QueryState";
import { RunHistoryView } from "../components/runs/RunHistoryView";

export function RunDetailPage() {
  // /history/:id (global) or /projects/:id/history/:runId (project-nested).
  const { id, runId } = useParams();
  const rid = runId ?? id ?? "";
  const projectId = runId ? id : undefined;
  const query = useQuery({
    // Same key the workbench uses → cache is shared with a just-finished run.
    queryKey: ["run", rid],
    queryFn: () => api.runDetail(rid),
  });
  const { data: detail } = query;

  return (
    <QueryState query={query} loadingClassName="h-40" errorLabel="Couldn't load this run">
      {detail ? (
        <RunHistoryView detail={detail} projectId={projectId} />
      ) : (
        <p className="rounded-md bg-destructive/10 p-3 font-mono text-xs text-destructive">
          run not found
        </p>
      )}
    </QueryState>
  );
}
