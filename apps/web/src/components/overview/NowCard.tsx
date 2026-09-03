import { ArrowRight, CirclePlay } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

import type { ActiveRun, Project } from "../../api/client";
import { liveRunHref } from "../../lib/runs";
import { AgentStatus } from "../AgentStatus";
import { TONE_BADGE } from "../StatusBadge";
import { CardHead } from "./bits";

/** The page's ONE "is anything running right now" surface (5C: trimmed from its former dual
 *  charter — the project-level lifecycle move it used to carry beneath a divider moved into
 *  `DecisionBand`, which is now the page's single "needs you" region; a card that both reports
 *  status and asks for a decision was the second half of the "what do I do now" contradiction
 *  this pass removed). Every value traces to real project state — no generated prose. */
export function NowCard({
  project,
  activeRun,
}: {
  project: Project;
  activeRun?: ActiveRun;
}) {
  const inProgress = (project.backlog ?? []).filter((i) => i.status === "in_progress");
  const topItem = inProgress[0];

  // Fully idle: one quiet line, not a band of chrome around a single sentence. The worklist
  // above owns what to do next (2026-08-22) — this card answers only "is anything running".
  if (!activeRun && !topItem) {
    return (
      <Card size="sm">
        <CardContent className="flex items-center gap-2.5">
          <CirclePlay className="size-4 shrink-0 text-muted-foreground/60" />
          <span className="text-[13px] text-muted-foreground">
            Nothing running right now — the worklist above has what needs you.
          </span>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardHead icon={CirclePlay}>Happening now</CardHead>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {activeRun ? (
          <div className="flex flex-col gap-2.5">
            <Badge className={`font-mono text-[10px] uppercase ${TONE_BADGE.success}`}>
              Running
            </Badge>
            {/* A run always carries a task by construction (task_spec.py) — no placeholder
                pretends otherwise; an empty string here would mean the record is wrong, which
                is worth seeing as blank rather than papered over. */}
            <p className="text-[15px] font-medium leading-snug">{activeRun.task}</p>
            <Link to={liveRunHref(activeRun.run_id, project.id)} className="block hover:opacity-90">
              <AgentStatus
                phase={activeRun.phase ?? ""}
                startedAt={activeRun.started_at ?? null}
                status="running"
                compact
              />
            </Link>
            <div>
              <Button
                size="sm"
                variant="outline"
                className="h-7 font-mono text-[11px]"
                render={<Link to={liveRunHref(activeRun.run_id, project.id)} />}
              >
                Watch the live run <ArrowRight />
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-2.5">
            <Badge className={`font-mono text-[10px] uppercase ${TONE_BADGE.amber}`}>
              In progress
            </Badge>
            <p className="text-[15px] font-medium leading-snug">{topItem.title}</p>
            {inProgress.length > 1 && (
              <p className="font-mono text-[11px] text-muted-foreground/60">
                +{inProgress.length - 1} more in progress
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
