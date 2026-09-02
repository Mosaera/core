import { ChevronRight, SquareKanban } from "lucide-react";
import { Fragment } from "react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

import type { BacklogItem, Project } from "../../api/client";
import { backlogCounts } from "../../lib/overview";
import { TONE_BADGE } from "../StatusBadge";
import { CardHead, EmptyNote } from "./bits";

const LANES: { key: string; label: string }[] = [
  { key: "todo", label: "Planned" },
  { key: "in_progress", label: "In progress" },
  { key: "in_review", label: "Review" },
  { key: "done", label: "Done" },
];


/** The delivery scoreboard (Overview rebuild, 2026-08-13): the four backlog lanes as
 *  LINKED count tiles with their top items. Replaces WorkPipelineSummary +
 *  ProjectStatsGrid, which rendered the same counts twice. The stats footer (runs / files
 *  changed / artifacts) was cut in the redundancy audit 2026-08-22 — each number's own page
 *  states it; the sidebar routes there. */
export function PipelineCard({
  project,
  mrState,
}: {
  project: Project;
  mrState: string | null;
}) {
  const items = project.backlog ?? [];
  const byLane = (key: string): BacklogItem[] =>
    items.filter((i) => i.status === key).sort((a, b) => a.position - b.position || a.id - b.id);
  return (
    <Card>
      <CardHeader className="grid-cols-[1fr_auto_auto] items-center gap-2">
        <CardHead icon={SquareKanban}>Work pipeline</CardHead>
        {items.length > 0 && (
          <span className="font-mono text-xs tabular-nums text-muted-foreground">
            {backlogCounts(items).done}/{items.length} done
          </span>
        )}
        {project.mr_url && (
          <Link to={`/projects/${project.id}/changes`}>
            <Badge className={`font-mono text-[10px] uppercase ${TONE_BADGE.amber}`}>
              MR {mrState ?? "open"}
            </Badge>
          </Link>
        )}
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <EmptyNote icon={SquareKanban} hint="Lanes fill once the PM decomposes the brief.">
            No backlog yet
          </EmptyNote>
        ) : (
          <div className="grid grid-cols-2 gap-2 lg:flex lg:items-start">
            {LANES.map((lane, idx) => {
              const laneItems = byLane(lane.key);
              return (
                <Fragment key={lane.key}>
                  {idx > 0 && (
                    <ChevronRight className="mt-2 hidden size-3.5 shrink-0 text-muted-foreground/40 lg:block" />
                  )}
                  <Link
                    to={`/projects/${project.id}/backlog`}
                    className="min-w-0 rounded-md bg-muted/30 p-2 transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:flex-1"
                  >
                    <div className="mb-1.5 flex items-baseline gap-2 px-0.5">
                      <span className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
                        {lane.label}
                      </span>
                      <span className="text-lg font-semibold tabular-nums leading-none">
                        {laneItems.length}
                      </span>
                    </div>
                  </Link>
                </Fragment>
              );
            })}
          </div>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border pt-3 font-mono text-xs">
          <Link
            to={`/projects/${project.id}/backlog`}
            className="ml-auto text-primary underline-offset-2 hover:underline"
          >
            View full backlog
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}
