import { useQuery } from "@tanstack/react-query";

import { api } from "../../../api/client";
import { GitLabMark } from "../gitlab/GitLabMark";
import { SettingsSection } from "../SettingsSection";
import { GitHubMark } from "./GitHubMark";
import { ProviderRow } from "./ProviderRow";

/** The Git index: which forges this workspace can reach.
 *
 *  This page is the thing that was missing. GitLab used to live in Settings and GitHub only
 *  inside one project's Delivery panel, so nothing anywhere answered "what is this workspace
 *  connected to?" — an operator had to already know a forge was supported to find out whether
 *  it was configured. */
export function GitIndex() {
  const { data: gh } = useQuery({ queryKey: ["github-status"], queryFn: () => api.githubStatus() });
  const { data: gl } = useQuery({
    queryKey: ["oauth-status"],
    queryFn: () => api.gitlabOauthStatus(),
  });

  return (
    <SettingsSection
      title="Git"
      description={
        <p className="text-sm leading-relaxed text-muted-foreground">
          Connect the GitHub or GitLab accounts your projects deliver to. A connection made here
          is available to every project on this instance; each project then links to one
          repository, and delivery opens its requests there.
        </p>
      }
    >
      <div className="flex flex-col items-stretch divide-y divide-border/40 overflow-hidden rounded-lg ring-1 ring-white/12">
        <ProviderRow
          to="/settings/git/github"
          mark={<GitHubMark className="size-5" />}
          name="GitHub"
          description="Deliver pull requests with a GitHub App installation"
          state={gh?.configured ? "app registered" : "not configured"}
          tone={gh?.configured ? "success" : "neutral"}
        />
        <ProviderRow
          to="/settings/git/gitlab"
          mark={<GitLabMark className="size-5 text-[#FC6D26]" />}
          name="GitLab"
          description="Deliver merge requests to GitLab.com or self-managed GitLab"
          state={gl?.configured ? "oauth app set" : "not configured"}
          tone={gl?.configured ? "success" : "neutral"}
        />
      </div>
    </SettingsSection>
  );
}
