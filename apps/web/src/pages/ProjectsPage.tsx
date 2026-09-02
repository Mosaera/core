import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { TONE_BADGE } from "../components/StatusBadge";

import { api, type Project } from "../api/client";
import { EmptyNote } from "../components/overview/bits";

// Project status → badge tone (project-level; NOT the run-level runOutcome).
const STATUS_BADGE: Record<string, string> = {
  active: TONE_BADGE.success,
  merged: TONE_BADGE.success,
  in_review: TONE_BADGE.amber,
  ready: TONE_BADGE.amber,
  drafting: TONE_BADGE.neutral,
  draft: TONE_BADGE.neutral,
};

const ROW =
  "flex items-center gap-3 rounded-lg bg-card p-3 ring-1 ring-white/12 transition-colors hover:bg-muted/30";

export function ProjectsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.listProjects(),
    // Poll so a project mid-intake flips forward without a manual refresh.
    refetchInterval: 4000,
  });
  const projects = data?.projects ?? [];

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-bold tracking-tight">Projects</h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
            A project is a workspace you initialize with the PM — point it at a source repo, shape
            the work with Quincy, then let the team drive an isolated clone toward a reviewable
            merge. Requires the database (
            <span className="font-mono text-xs">MOSAERA_DB_URL</span>).
          </p>
        </div>
        <Link
          to="/projects/new"
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          <Plus className="size-4" />
          New project
        </Link>
      </header>

      {isLoading && <Skeleton className="h-24 w-full" />}
      {error && (
        <p className="rounded-md bg-destructive/10 p-3 font-mono text-xs text-destructive">
          {String(error)}
        </p>
      )}
      {!isLoading && !error && projects.length === 0 && (
        <EmptyNote>No projects yet. Create one to start the PM intake.</EmptyNote>
      )}

      <div className="flex flex-col gap-2">
        {projects.map((p: Project) => (
          <Link className={ROW} to={`/projects/${p.id}`} key={p.id}>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">{p.name}</div>
              <div className="truncate font-mono text-[11px] text-muted-foreground">
                {p.source_repo}
              </div>
            </div>
            <Badge
              className={cn(
                "font-mono text-[10px] uppercase",
                STATUS_BADGE[p.status] ?? TONE_BADGE.neutral,
              )}
            >
              {p.status}
            </Badge>
          </Link>
        ))}
      </div>
    </div>
  );
}
