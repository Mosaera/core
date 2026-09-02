import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";

import { api } from "../../api/client";
import type { DeliveryCapability } from "../../api/delivery";
import { ConsoleLabel } from "../overview/bits";

/** GitHub delivery state for one project — state only, plus a link to where it is changed.
 *
 *  It used to own its own Connect button. That put a second connect control on a second page,
 *  which GitLab has never done: `DeliveryCredentials` links to the project's Integration pane
 *  rather than duplicating the action. Now GitHub matches — one control, one place
 *  (`settings/github/GitHubConnection`), and this card reports.
 *
 *  The underlying handshake is still deliberately unlike GitLab's: that one sends the operator
 *  through a full-page OAuth redirect, while GitHub's equivalent redirect hands back an
 *  `installation_id` that GitHub itself documents as spoofable, so Mosaera never reads one.
 *  The server asks GitHub which installation owns this project's repo instead.
 *
 *  Three states, because they have three different remedies and collapsing them would send
 *  someone to fix a thing that is already fine:
 *    · the instance has no App        → an admin configures it once
 *    · the App is not on this repo    → install it, then Connect
 *    · connected                      → nothing to do */
export function GitHubDelivery({
  projectId,
  capability,
}: {
  projectId: string;
  capability?: DeliveryCapability;
}) {
  const { data: status } = useQuery({
    queryKey: ["github-status"],
    queryFn: () => api.githubStatus(),
  });

  const connected = Boolean(capability?.has_github_connection);
  const configured = capability?.github_app_configured ?? status?.configured ?? false;

  return (
    <section
      aria-label="Delivery credentials"
      className="flex flex-col gap-2 rounded-lg bg-card p-4 ring-1 ring-white/12"
    >
      <ConsoleLabel>GitHub delivery</ConsoleLabel>

      {connected ? (
        <p className="text-[12.5px] text-muted-foreground">
          Connected — pull requests are opened with a short-lived token scoped to this
          repository, minted for each delivery and never stored.
        </p>
      ) : (
        <p className="text-[11.5px] leading-relaxed text-amber-600 dark:text-amber-400">
          {capability?.detail || "GitHub delivery is not available for this project yet."}
        </p>
      )}

      {capability?.note && (
        <p className="text-[11.5px] text-muted-foreground/80">{capability.note}</p>
      )}

      {/* Per-item pull requests are not built yet; say so where the item controls are missing,
          rather than leaving their absence to look like a bug. */}
      {connected && capability?.item_requests_supported === false && (
        <p className="text-[11.5px] text-muted-foreground/80">
          One combined pull request per project — per-item pull requests are GitLab-only for
          now.
        </p>
      )}

      {status?.is_admin && (
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Button
            size="sm"
            variant={connected ? "outline" : "default"}
            nativeButton={false}
            render={<Link to={`/projects/${projectId}/settings?pane=integration`} />}
          >
            {connected ? "Manage GitHub" : configured ? "Connect GitHub" : "Set up GitHub"}
          </Button>
        </div>
      )}

    </section>
  );
}
