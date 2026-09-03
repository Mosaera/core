import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import { severityBadge } from "../components/StatusBadge";
import { QueryState } from "../components/QueryState";

import { api, type Project } from "../api/client";
import { EmptyNote } from "../components/overview/bits";
import { STATUS_BADGE } from "../lib/overview";

const ROW =
  "flex items-center gap-3 rounded-lg bg-card p-3 ring-1 ring-white/12 transition-colors hover:bg-muted/30";

/** A project's status → the badge everywhere else on the page already speaks (`lib/overview`'s
 *  severity vocabulary): reused here instead of a second status→label table (5B). */
function statusBadge(status: string): { label: string; className: string } {
  const s = STATUS_BADGE[status];
  return { label: s?.label ?? status.replace(/_/g, " "), className: severityBadge(s?.severity ?? "neutral") };
}

export function ProjectsPage() {
  const query = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.listProjects(),
    // Poll so a project mid-intake flips forward without a manual refresh.
    refetchInterval: 4000,
  });
  const projects = query.data?.projects ?? [];

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-bold tracking-tight">Projects</h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
            You describe the work, Mosaera plans it, does it in an isolated copy of your repo, and
            shows you the evidence before anything ships.
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

      <QueryState query={query} errorLabel="Couldn't load your projects">
        {projects.length === 0 && (
          <EmptyNote>No projects yet. Create one to describe the work and get started.</EmptyNote>
        )}

        <div className="flex flex-col gap-2">
          {projects.map((p: Project) => {
            const badge = statusBadge(p.status);
            return (
              <Link className={ROW} to={`/projects/${p.id}`} key={p.id}>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{p.name}</div>
                  <div className="truncate font-mono text-[11px] text-muted-foreground">
                    {p.source_repo}
                  </div>
                </div>
                <Badge className={cn("font-mono text-[10px] uppercase", badge.className)}>
                  {badge.label}
                </Badge>
              </Link>
            );
          })}
        </div>
      </QueryState>
    </div>
  );
}
