import { ArrowRight, CirclePlay } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

import type { ActiveRun, Project } from "../../api/client";
import { lifecycleAction } from "../../lib/overview";
import { liveRunHref } from "../../lib/runs";
import { AgentStatus } from "../AgentStatus";
import { TONE_BADGE } from "../StatusBadge";
import { CardHead, ConsoleLabel } from "./bits";

/** The page's one "now" surface (Overview rebuild, 2026-08-13): what is happening this
 *  minute on top, the rule-derived next decision beneath it. Replaces CurrentWorkCard +
 *  RecommendedNextActionCard, which each gave half of the same answer. Every suggestion
 *  traces to real project state — no generated prose. */
export function NowCard({
  project,
  activeRun,
}: {
  project: Project;
  activeRun?: ActiveRun;
}) {
  // Project-level move only (intake / MR / post-merge). Item work lives in the worklist above.
  const lifecycle = lifecycleAction(project);
  const inProgress = (project.backlog ?? []).filter((i) => i.status === "in_progress");
  const topItem = inProgress[0];

  // Fully idle: one quiet line, not a band of chrome around a single sentence. The worklist
  // above owns what to do next (2026-08-22) — this card answers only "is anything running".
  if (!activeRun && !topItem && !lifecycle) {
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
        {/* --- now --- */}
        {activeRun ? (
          <div className="flex flex-col gap-2.5">
            <Badge className={`font-mono text-[10px] uppercase ${TONE_BADGE.success}`}>
              Running
            </Badge>
            <p className="text-[15px] font-medium leading-snug">{activeRun.task || "(task)"}</p>
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
        ) : topItem ? (
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
        ) : (
          <p className="text-[13px] text-muted-foreground">Nothing running right now.</p>
        )}

        {lifecycle && (
          <div className="flex flex-col gap-1 border-t border-border pt-3">
            <ConsoleLabel className="text-[10px]">Project</ConsoleLabel>
            <p className="text-sm font-medium leading-snug">{lifecycle.title}</p>
            <p className="text-[13px] leading-relaxed text-muted-foreground">{lifecycle.reason}</p>
            {lifecycle.cta && (
              <div className="pt-1">
                <Button
                  size="sm"
                  variant="outline"
                  className="border-primary/40 text-primary hover:border-primary/70 hover:bg-primary/10 hover:text-primary"
                  render={
                    lifecycle.cta.kind === "external" ? (
                      <a href={lifecycle.cta.to} target="_blank" rel="noreferrer" />
                    ) : (
                      <Link to={`/projects/${project.id}/${lifecycle.cta.to}`} />
                    )
                  }
                >
                  {lifecycle.cta.label} <ArrowRight />
                </Button>
              </div>
            )}
          </div>
        )}

      </CardContent>
    </Card>
  );
}
