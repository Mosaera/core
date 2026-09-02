import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api, type Project } from "@/api/client";
import type { Decision } from "@/api/delivery";
import { Button } from "@/components/ui/button";
import { GitLabDialog } from "@/components/settings/gitlab/GitLabDialog";
import { cn } from "@/lib/utils";

import { ConsoleLabel } from "./bits";

/** A decision the SERVER says is pending (ADR-0105), rendered on the project Overview.
 *
 *  It lived in the PM conversation until 2026-08-22. The owner's objection was the shape, not the
 *  derivation: the cards had no refetch interval, no dismissal, and no acknowledgment, so they sat
 *  pinned to the bottom of every conversation as permanent furniture. What was wanted was
 *  notification-style surfacing — the finding raised where the operator is working, actionable or
 *  delegable. ADR-0105 binds four properties (derived-never-stored, the model may reference but
 *  never mint, actions hand off carrying no endpoint, credentials never traverse the chat); it
 *  does NOT bind the placement, so this is a relocation.
 *
 *  Three things this deliberately is not:
 *  - **Not model output.** The list comes from `GET /projects/:id/decisions`, recomputed per
 *    call. Quincy may reference an id; the server drops any it did not derive. So this card
 *    cannot be summoned by anything Quincy was persuaded to say.
 *  - **Not a new control.** Every action hands off to the surface that already owns it — the
 *    run's gate, the one GitLab dialog, the Delivery page. Nothing is authorized here.
 *  - **Not response-local.** It is query-backed, so unlike the changeset and charter cards it
 *    survives a reload; a pending decision that vanished on refresh would be worse than none.
 *
 *  A credential is never typed into this card. The setup action opens the same admin-gated
 *  dialog the settings pane opens, whose save posts straight to the credential endpoint — the
 *  chat transcript never carries the value.
 */
export function DecisionCard({ project, decision }: { project: Project; decision: Decision }) {
  const [open, setOpen] = useState(false);
  const { data: oauth } = useQuery({
    queryKey: ["oauth-status"],
    queryFn: () => api.gitlabOauthStatus(),
    enabled: decision.kind === "integration_missing",
  });
  const isAdmin = Boolean(oauth?.is_admin);
  const { data: status } = useQuery({
    queryKey: ["gitlab-status"],
    queryFn: () => api.gitlabStatus(),
    enabled: decision.kind === "integration_missing" && isAdmin,
  });

  // `blocking` = delivery cannot proceed until a human acts. `standing` = nothing is broken, work
  // is outstanding. Every card links out, so the tier is about the CONDITION, not the button — and
  // a standing condition announced as "waiting on you" is a banner the operator learns to ignore
  // (red team 2026-08-19, finding 2, found by the owner clicking through and coming back).
  const standing = decision.tier === "standing";
  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-lg bg-card p-3 text-sm ring-1",
        standing ? "ring-white/12" : "ring-amber-500/30",
      )}
    >
      <ConsoleLabel>{standing ? "Standing" : "Waiting on you"}</ConsoleLabel>
      <p className="text-[13px] font-medium">{decision.title}</p>
      <p className="text-[12.5px] leading-relaxed text-muted-foreground">{decision.summary}</p>

      <div className="flex flex-wrap items-center gap-2">
        {decision.kind === "gate_pending" && decision.run_id && (
          <Button size="sm" nativeButton={false} render={<Link to={`/runs/${decision.run_id}`} />}>
            Open the gate
          </Button>
        )}
        {decision.kind === "delivered_no_mr" && (
          <Button
            size="sm"
            variant="outline"
            nativeButton={false}
            render={<Link to={`/projects/${project.id}/delivery`} />}
          >
            Review on the Delivery page
          </Button>
        )}
        {decision.kind === "backlog_health" && (
          <Button
            size="sm"
            variant="outline"
            nativeButton={false}
            render={<Link to={`/projects/${project.id}/backlog`} />}
          >
            Review the backlog
          </Button>
        )}
        {decision.kind === "mr_stuck" && (
          <Button
            size="sm"
            variant="outline"
            nativeButton={false}
            render={<Link to={`/projects/${project.id}/delivery`} />}
          >
            Repoint it on the Delivery page
          </Button>
        )}
        {decision.kind === "integration_missing" &&
          (isAdmin ? (
            decision.actions.length > 0 && (
              <Button size="sm" onClick={() => setOpen(true)}>
                {decision.actions[0].label}
              </Button>
            )
          ) : (
            // The surface stops offering what the server would 403, rather than acquiring an
            // ability (ADR-0104 Amendment 2).
            <p className="text-[12.5px] text-muted-foreground">
              Contact your administrator to set up GitLab for this project.
            </p>
          ))}
      </div>

      {decision.kind === "integration_missing" && isAdmin && (
        <GitLabDialog
          open={open}
          onOpenChange={setOpen}
          project={project}
          status={status}
          host={oauth?.host}
        />
      )}
    </div>
  );
}
