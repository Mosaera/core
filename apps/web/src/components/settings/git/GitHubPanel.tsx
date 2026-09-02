import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { useAuth } from "../../../api/authContext";
import { api, type Project } from "../../../api/client";
import { TONE_BADGE } from "../../StatusBadge";
import { ConnectionShell, PanelSection } from "./ConnectionShell";
import { ConnectionsTable } from "./ConnectionsTable";
import { GitHubMark } from "./GitHubMark";
import { GitHubRepoCreation } from "./GitHubRepoCreation";
import { GitHubSetup } from "./GitHubSetup";
import { SetupStep, SetupSteps, type StepState } from "./SetupSteps";
import { ownerOf, ownerRepoLabel } from "./ownerOf";

/** GitHub at the workspace level: what is set up, what is left, and which projects it covers.
 *
 *  Setting GitHub up is three trips to GitHub — register the app, install it somewhere, and
 *  optionally add an OAuth App so repositories can be created. This page used to present the
 *  first as a wizard and the rest as unrelated-looking sections underneath, so the stepper said
 *  "1 of 3" and never moved, and the remaining work was something you had to notice rather than
 *  be led to. It is one checklist now, and each step knows whether it is already done.
 *
 *  This page never *spends* an installation id (ADR-0114): the list is for the operator's eyes,
 *  and delivery still asks GitHub which installation owns the repository it is about to write to. */
export function GitHubPanel() {
  const qc = useQueryClient();
  // Gate the fetches on the SAME rule the endpoints enforce (`require_admin`, satisfied by an
  // admin session or an open loopback box) rather than a narrower session-only test, which left a
  // dev instance rendering an empty list produced by a query that never ran.
  const { isAdmin, status: authStatus } = useAuth();
  const canConfig = isAdmin || !authStatus?.auth_required;

  const { data: status } = useQuery({
    queryKey: ["github-status"],
    queryFn: () => api.githubStatus(),
  });
  const { data, isFetching } = useQuery({
    queryKey: ["github-installations"],
    queryFn: () => api.githubInstallations(),
    enabled: canConfig,
  });
  const { data: repoStatus } = useQuery({
    queryKey: ["github-repo-status"],
    queryFn: () => api.githubRepoStatus(),
    enabled: canConfig,
  });
  const { data: projectList } = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.listProjects(),
    enabled: canConfig,
  });

  const appReady = data?.configured ?? status?.configured ?? false;
  const installations = data?.installations ?? [];
  const installUrl = data?.install_url || status?.install_url || "";
  const installed = installations.length > 0;
  const canCreateRepos = Boolean(repoStatus?.configured);

  // Which projects sit on GitHub, and under which account — the part the installation list does
  // not already say. Repeating account/type/access in a second grid would look like more
  // information and be none.
  const githubProjects = (projectList?.projects ?? [])
    .map((p: Project) => ({ project: p, owner: ownerOf(p.source_repo) }))
    .filter((r): r is { project: Project; owner: string } => r.owner !== null);

  const step = (done: boolean, blocked: boolean): StepState =>
    done ? "done" : blocked ? "pending" : "current";

  return (
    <ConnectionShell
      mark={<GitHubMark className="size-7" />}
      title="Connect GitHub"
      description="Connect a GitHub account or organization, then link projects to repositories."
    >
      <PanelSection
        title="Setup"
        action={
          appReady ? (
            <Button
              size="sm"
              variant="outline"
              disabled={isFetching}
              onClick={() => void qc.invalidateQueries({ queryKey: ["github-installations"] })}
            >
              <RefreshCw className={cn("size-3.5", isFetching && "animate-spin")} aria-hidden />
              Refresh
            </Button>
          ) : undefined
        }
      >
        <SetupSteps>
          <SetupStep index={1} state={appReady ? "done" : "current"} title="Register the app">
            {appReady ? (
              <p className="text-[12.5px] leading-relaxed text-muted-foreground">
                Registered on this instance. Delivery signs as this app and mints a token scoped to
                a single repository for each pull request.
              </p>
            ) : (
              <GitHubSetup onDone={() => void qc.invalidateQueries()} />
            )}
          </SetupStep>

          <SetupStep index={2} state={step(installed, !appReady)} title="Install it on an account">
            {!appReady ? (
              <p className="text-[12.5px] text-muted-foreground">
                Available once the app is registered.
              </p>
            ) : installed ? (
              <>
                <p className="text-[12.5px] leading-relaxed text-muted-foreground">
                  Delivery picks the right installation from a project&rsquo;s own repository, so
                  there is nothing to choose here.
                </p>
                <ul className="flex flex-col items-stretch overflow-hidden rounded-lg ring-1 ring-white/12">
                  {installations.map((inst) => (
                    <li
                      key={inst.id ?? inst.account}
                      className="flex items-center gap-3 border-b border-border/40 px-3 py-2.5 last:border-0"
                    >
                      <GitHubMark className="size-4 shrink-0 text-muted-foreground" />
                      <span className="min-w-0 flex-1 truncate text-[13px] text-foreground/90">
                        {inst.account ?? "—"}
                      </span>
                      <Badge className={cn("font-mono text-[10px] uppercase", TONE_BADGE.neutral)}>
                        {inst.account_type ?? "account"}
                      </Badge>
                      <Badge
                        className={cn(
                          "font-mono text-[10px] uppercase",
                          inst.repository_selection === "all"
                            ? TONE_BADGE.success
                            : TONE_BADGE.neutral,
                        )}
                      >
                        {inst.repository_selection === "all" ? "all repos" : "selected repos"}
                      </Badge>
                    </li>
                  ))}
                </ul>
                {installUrl && (
                  <a
                    href={installUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="w-fit text-[12.5px] text-primary underline-offset-2 hover:underline"
                  >
                    Install on another account
                  </a>
                )}
              </>
            ) : (
              <>
                <p className="text-[12.5px] leading-relaxed text-muted-foreground">
                  The app cannot see any repositories until it is installed. Put it on the account
                  or organization that owns the repositories you want Mosaera to work with — you
                  choose which repositories it may touch.
                </p>
                {data?.error && (
                  <p role="alert" className="text-xs text-destructive">
                    Couldn&rsquo;t reach GitHub: {data.error}
                  </p>
                )}
                {installUrl ? (
                  <Button
                    size="sm"
                    className="w-fit"
                    nativeButton={false}
                    render={<a href={installUrl} target="_blank" rel="noreferrer" />}
                  >
                    Install on GitHub
                  </Button>
                ) : (
                  <p className="text-[11.5px] text-muted-foreground/80">
                    No install link — this app has no slug recorded, so install it from its own page
                    on GitHub.
                  </p>
                )}
              </>
            )}
          </SetupStep>

          <SetupStep
            index={3}
            state={step(canCreateRepos, !appReady)}
            title="Let Mosaera create repositories"
            optional
          >
            <GitHubRepoCreation configured={canCreateRepos} />
          </SetupStep>
        </SetupSteps>
      </PanelSection>

      <PanelSection title="Projects on GitHub">
        <ConnectionsTable
          columns={["Project", "Repository", "Account"]}
          rows={githubProjects.map(({ project, owner }) => ({
            key: project.id,
            cells: [
              project.name,
              <span className="font-mono text-[11.5px] text-muted-foreground">
                {ownerRepoLabel(project.source_repo)}
              </span>,
              <span className="flex items-center gap-1.5">
                <GitHubMark className="size-3.5 text-muted-foreground" />
                {owner}
              </span>,
            ],
          }))}
          empty="None yet — a project whose repository is on GitHub appears here once it exists."
        />
      </PanelSection>
    </ConnectionShell>
  );
}
