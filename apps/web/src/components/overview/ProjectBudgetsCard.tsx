import { useQuery } from "@tanstack/react-query";
import { Wallet } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

import { api, type Project, type ProjectBudgetStatus } from "../../api/client";
import { TONE_BADGE } from "../StatusBadge";
import { BudgetBar, CardHead, ConsoleLabel } from "./bits";

const usd = (n: number) => `$${n.toFixed(2)}`;

/** Project budgets. Monthly spend-vs-cap meters when ceilings are set; with NO cap the whole card
 *  collapses to a single line — a box of chrome around one figure was the "some items don't need
 *  that much horizontal space" complaint (owner, 2026-08-22).
 *  Read-only here; caps are edited in project Settings. The LIFETIME block moved to
 *  project Settings → General in the 2026-08-22 redundancy audit — the overview keeps
 *  only the number that changes month to month. */
export function ProjectBudgetsCard({ project }: { project: Project }) {
  const { data: status } = useQuery<ProjectBudgetStatus>({
    queryKey: ["project-budget", project.id],
    queryFn: () => api.projectBudget(project.id),
  });
  const hasCap = status && (status.budget_usd != null || status.budget_tokens != null);
  // Local models are unpriced: an all-$0 column is noise, so dollars only render once
  // any dollar exists (spend, or a $ cap to track against).
  const dollarsMatter = Boolean(status && (status.spent_usd > 0 || status.budget_usd != null));

  return (
    <Card>
      <CardHeader className="grid-cols-[1fr_auto]">
        <CardHead icon={Wallet}>Budgets</CardHead>
        {status?.over ? (
          <Badge className={`font-mono text-[10px] uppercase ${TONE_BADGE.destructive}`}>
            Over budget
          </Badge>
        ) : status?.warn ? (
          <Badge className={`font-mono text-[10px] uppercase ${TONE_BADGE.amber}`}>
            {Math.round(status.pct * 100)}% used
          </Badge>
        ) : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-col gap-2">
          {hasCap && <ConsoleLabel className="text-[10px]">This month</ConsoleLabel>}
          {status ? (
            hasCap ? (
              <div className="flex flex-col gap-2">
                {status.budget_usd != null && (
                  <BudgetBar
                    label="Spend"
                    spent={status.spent_usd}
                    cap={status.budget_usd}
                    fmt={usd}
                  />
                )}
                {status.budget_tokens != null && (
                  <BudgetBar
                    label="Tokens"
                    spent={status.spent_tokens}
                    cap={status.budget_tokens}
                  />
                )}
              </div>
            ) : (
              <p className="font-mono text-[13px]">
                <span className="text-muted-foreground">This month </span>
                {dollarsMatter ? `${usd(status.spent_usd)} · ` : ""}
                {status.spent_tokens.toLocaleString()} tokens
                <span className="ml-2 text-muted-foreground">no budget set</span>
              </p>
            )
          ) : (
            <p className="font-mono text-[13px] text-muted-foreground">—</p>
          )}
          {status?.resets_at && (
            <p className="font-mono text-[11px] text-muted-foreground/60">
              resets {new Date(status.resets_at).toLocaleDateString()}
            </p>
          )}
        </div>

        <Link
          to={`/projects/${project.id}/settings`}
          className="font-mono text-xs text-primary underline-offset-2 hover:underline"
        >
          Edit budgets
        </Link>
      </CardContent>
    </Card>
  );
}
