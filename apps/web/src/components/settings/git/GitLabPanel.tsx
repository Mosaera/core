import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../../api/client";
import { GitLabCard } from "../GitLabCard";
import { GitLabMark } from "../gitlab/GitLabMark";
import { ConnectionShell } from "./ConnectionShell";
import { GitLabSetup } from "./GitLabSetup";

/** GitLab at the workspace level.
 *
 *  Two states, and only the first is new: an instance with no OAuth application registered gets
 *  the first-run wizard; one that is configured gets the existing card unchanged. Deliberately
 *  NOT a rewrite of that card — its OAuth summary, identity block, visible-projects list and
 *  secure-dev checklist all still work, and replacing working surface was not what was asked for.
 *
 *  The shell is shared with `GitHubPanel` so both forges read as one product, even though their
 *  setup steps differ irreducibly: GitHub registers its App in one click, GitLab cannot. */
export function GitLabPanel() {
  const qc = useQueryClient();
  const { data: oauth } = useQuery({
    queryKey: ["oauth-status"],
    queryFn: () => api.gitlabOauthStatus(),
  });

  // Undefined while the probe is in flight — render nothing rather than flash the wizard at an
  // instance that turns out to be configured.
  if (oauth === undefined) return null;

  return (
    <ConnectionShell
      mark={<GitLabMark className="size-7 text-[#FC6D26]" />}
      title="Connect GitLab Self-Managed"
      description="Connect a self-hosted GitLab instance to sync repositories."
    >
      {oauth.configured ? (
        <GitLabCard />
      ) : (
        <GitLabSetup onDone={() => void qc.invalidateQueries()} />
      )}
    </ConnectionShell>
  );
}
