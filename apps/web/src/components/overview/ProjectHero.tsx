import { GitBranch } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import type { ActiveRun, Project, ProjectMessage } from "../../api/client";
import { severityBadge } from "../StatusBadge";
import { derivePhase, lastActivityAt, STATUS_BADGE, timeAgo } from "../../lib/overview";


/** Compact project context band: name, status, phase, repo, id, freshness. */
export function ProjectHero({
  project,
  activeRun,
  messages,
}: {
  project: Project;
  activeRun?: ActiveRun;
  messages: ProjectMessage[];
}) {
  const status = STATUS_BADGE[project.status] ?? { label: project.status, severity: "neutral" as const };
  const phase = derivePhase(project, activeRun);
  const updated = timeAgo(lastActivityAt(project, messages));
  return (
    <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-2">
      <h1 className="font-sans text-2xl font-bold tracking-tight">{project.name}</h1>
      <Badge className={cn("font-mono text-[10px] uppercase", severityBadge(status.severity))}>
        {status.label}
      </Badge>
      <Badge variant="outline" className="font-mono text-[10px] uppercase text-muted-foreground">
        Phase: {phase}
      </Badge>
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs text-muted-foreground">
        <span className="flex min-w-0 items-center gap-1.5">
          <GitBranch className="size-3.5 shrink-0" />
          <span className="truncate">{project.source_repo}</span>
        </span>
        <span>Updated {updated}</span>
        {/* Reference id: present for support/debugging, visually last and quietest. */}
        <span className="hidden text-[10px] tracking-wide text-muted-foreground/35 sm:inline">
          {project.id}
        </span>
      </div>
    </div>
  );
}
