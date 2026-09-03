import { useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuth } from "../../../api/authContext";
import { api, type Project } from "../../../api/client";
import { GitLabMark } from "../gitlab/GitLabMark";
import { ConnectionShell, PanelSection } from "./ConnectionShell";
import { ConnectionsTable } from "./ConnectionsTable";
import { GitLabDiscovery } from "./GitLabDiscovery";
import { GitLabOAuthApp } from "./GitLabOAuthApp";
import { GitLabWhere } from "./GitLabWhere";
import { SetupStep, SetupSteps, type StepState } from "./SetupSteps";

/** GitLab at the workspace level — the same shape as `GitHubPanel`, deliberately.
 *
 *  Both forges now read as one product: a setup checklist that knows what is done, then the
 *  projects it covers. The steps differ where the providers genuinely differ and nowhere else:
 *
 *  - GitLab asks **which instance** first, because everything after it is registered on that host.
 *    GitHub has no equivalent question.
 *  - GitLab's application is registered **by hand**; GitHub's registers itself from a manifest.
 *    That is not a design choice, it is that GitLab has no manifest flow.
 *  - GitLab's optional third step browses your projects; GitHub's grants repository creation.
 *
 *  Everything else — the ordering, the done/current/pending states, the optional marker, the
 *  projects table underneath — is shared, so learning one teaches the other. */
export function GitLabPanel() {
  const qc = useQueryClient();
  const { isAdmin, status: authStatus } = useAuth();
  const canConfig = isAdmin || !authStatus?.auth_required;

  const { data: oauth } = useQuery({
    queryKey: ["oauth-status"],
    queryFn: () => api.gitlabOauthStatus(),
  });
  const { data: status } = useQuery({
    queryKey: ["gitlab-status"],
    queryFn: () => api.gitlabStatus(),
    enabled: canConfig,
  });
  const { data: projectList } = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.listProjects(),
    enabled: canConfig,
  });

  const url = (status?.url ?? "").trim();
  const hostChosen = Boolean(url);
  const appReady = Boolean(oauth?.configured || status?.oauth_configured);
  const browsing = Boolean(status?.configured && status?.ok);
  const host = oauth?.host || (url ? new URL(url).host : "your GitLab");

  const connected = (projectList?.projects ?? []).filter((p: Project) => p.has_gitlab_token);

  const step = (done: boolean, blocked: boolean): StepState =>
    done ? "done" : blocked ? "pending" : "current";

  return (
    <ConnectionShell
      mark={<GitLabMark className="size-7 text-[#FC6D26]" />}
      title="Connect GitLab"
      description="Connect GitLab.com or your own instance, then link projects to repositories."
    >
      <PanelSection title="Setup">
        <SetupSteps>
          <SetupStep
            index={1}
            state={hostChosen ? "done" : "current"}
            title="Choose your GitLab"
          >
            <GitLabWhere url={url} onDone={() => void qc.invalidateQueries()} />
          </SetupStep>

          <SetupStep
            index={2}
            state={step(appReady, !hostChosen)}
            title="Register an OAuth application"
          >
            {!hostChosen ? (
              <p className="text-[12.5px] text-muted-foreground">
                Available once you have chosen an instance — the application is registered on it.
              </p>
            ) : (
              <GitLabOAuthApp
                host={host}
                configured={appReady}
                clientIdMasked={status?.oauth_client_id_masked}
                envPinned={status?.oauth_env_pinned}
              />
            )}
          </SetupStep>

          <SetupStep
            index={3}
            state={step(browsing, !hostChosen)}
            title="Browse your groups and projects"
            optional
          >
            {!hostChosen ? (
              <p className="text-[12.5px] text-muted-foreground">
                Available once you have chosen an instance.
              </p>
            ) : (
              <GitLabDiscovery status={status} />
            )}
          </SetupStep>
        </SetupSteps>
      </PanelSection>

      <PanelSection title="Projects on GitLab">
        <ConnectionsTable
          columns={["Project", "Repository", "Merge state"]}
          rows={connected.map((p) => ({
            key: p.id,
            cells: [
              p.name,
              <span className="font-mono text-[11.5px] text-muted-foreground">{p.source_repo}</span>,
              // The `api`-scoped half decides whether a merge request can ever read as merged
              // (#98/F64) — a project without it delivers and then never shows as delivered.
              p.has_gitlab_api_token ? "Readable" : "Not polled (no api scope)",
            ],
          }))}
          empty="None yet — a project connects from its own settings, and appears here once it has."
        />
      </PanelSection>
    </ConnectionShell>
  );
}
