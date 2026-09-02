import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { Skeleton } from "@/components/ui/skeleton";

import { api } from "../api/client";
import { RunHistoryView } from "../components/runs/RunHistoryView";

export function RunDetailPage() {
  // /history/:id (global) or /projects/:id/history/:runId (project-nested).
  const { id, runId } = useParams();
  const rid = runId ?? id ?? "";
  const projectId = runId ? id : undefined;
  const {
    data: detail,
    isLoading,
    error,
  } = useQuery({
    // Same key the workbench uses → cache is shared with a just-finished run.
    queryKey: ["run", rid],
    queryFn: () => api.runDetail(rid),
  });

  if (isLoading)
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  if (error || !detail)
    return (
      <p className="rounded-md bg-destructive/10 p-3 font-mono text-xs text-destructive">
        {error ? String(error) : "run not found"}
      </p>
    );

  return <RunHistoryView detail={detail} projectId={projectId} />;
}
