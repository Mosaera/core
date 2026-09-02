import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";

import type { Project } from "../../api/client";
import type { DeliveryCapability } from "../../api/delivery";
import { ConsoleLabel } from "../overview/bits";
import { GitHubDelivery } from "./GitHubDelivery";

/** Which credentials this project has, and what each one decides.
 *
 *  Extracted from DeliveryWorkspace when that file reached the 500-line ceiling. Purely
 *  presentational: it owns no query and performs no action.
 *
 *  It states the api-token bit in BOTH directions (#98/F64) because that bit alone decides whether
 *  a project can ever read as delivered — `status=merged` is written only by the MR REST poll,
 *  which needs `api` scope. Without saying so, a stalled delivery and a missing credential look
 *  identical from this page.
 *
 *  ADR-0112/#120 adds the bit one level up: WHICH forge this project's source lives on. A GitHub
 *  or unrecognized source can never open a merge request here, and until now the only place that
 *  appeared was a 400 at the finish line whose wording blamed the operator's URL. GitLab token
 *  prose is not merely unhelpful on those projects — it is untrue, so it is not rendered at all. */
export function DeliveryCredentials({
  project,
  apiTokenPresent,
  capability,
}: {
  project: Project;
  apiTokenPresent: boolean;
  /** Absent while the query is in flight, or on an older server without the endpoint —
   *  in both cases the card falls back to the GitLab-only view it has always shown. */
  capability?: DeliveryCapability;
}) {
  const provider = capability?.provider ?? "gitlab";

  // ADR-0114: GitHub is deliverable now, and owns its own state + action.
  if (provider === "github") {
    return <GitHubDelivery projectId={project.id} capability={capability} />;
  }

  if (provider !== "gitlab") {
    return (
      <section
        aria-label="Delivery credentials"
        className="flex flex-col gap-2 rounded-lg bg-card p-4 ring-1 ring-white/12"
      >
        <ConsoleLabel>Delivery</ConsoleLabel>
        <p className="text-[12.5px] text-muted-foreground">
          This project&rsquo;s source is not on the configured GitLab, and is not a recognized
          GitHub repository.
        </p>
        <p className="text-[11.5px] leading-relaxed text-amber-600 dark:text-amber-400">
          {capability?.detail ||
            "Delivery has nowhere to open a request for this project."}
        </p>
        <p className="text-[11.5px] text-muted-foreground/80">
          Work still runs, commits, and validates normally — only the final open-a-request
          step is unavailable. Nothing you do here will change that, so it is said now
          rather than at the end.
        </p>
      </section>
    );
  }

  return (
    <section
      aria-label="Delivery credentials"
      className="flex flex-col gap-2 rounded-lg bg-card p-4 ring-1 ring-white/12"
    >
      <ConsoleLabel>Credentials</ConsoleLabel>
      <p className="text-[12.5px] text-muted-foreground">
        {project.has_gitlab_token
          ? `Project token ${project.gitlab_token_masked || "set"} — scoped write_repository; pushes and MRs use it, never the global token.`
          : "No project GitLab token — merge requests can't be opened for this project."}
      </p>
      {/* #98/F64: the api-scoped token decides whether this project can ever READ as
          delivered — `status=merged` is written only by the MR REST poll, which needs `api`
          scope. Saying so in both directions: an operator whose project never reaches
          "Delivered" could not otherwise tell a stalled delivery from a missing credential,
          and one who HAS the token had no confirmation that merging would work at all. */}
      {apiTokenPresent ? (
        <p className="text-[11.5px] text-muted-foreground/80">
          An <span className="font-mono">api</span>-scoped token is set — merge state is
          polled from GitLab, and merge requests can be merged from this page.
        </p>
      ) : (
        <p className="text-[11.5px] text-muted-foreground/80">
          No <span className="font-mono">api</span>-scoped token — merging from this page,
          editing the MR body, labels and a branch picker are unavailable until one is added.
          Merge state cannot be polled either, so this project will not show as delivered
          even after its merge requests land.
        </p>
      )}
      <Button
        size="sm"
        variant="outline"
        className="w-fit"
        nativeButton={false}
        render={<Link to={`/projects/${project.id}/settings?pane=integration`} />}
      >
        {project.has_gitlab_token ? "Manage GitLab" : "Connect GitLab"}
      </Button>
    </section>
  );
}
