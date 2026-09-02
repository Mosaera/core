import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { api, type Project } from "../../../api/client";
import type { DeliveryCapability } from "../../../api/delivery";
import { TONE_BADGE } from "../../StatusBadge";
import { GitHubMark } from "../git/GitHubMark";
import { SettingsSection } from "../SettingsSection";

/** A project's GitHub connection, on the project's own Integration pane.
 *
 *  This pane used to render `GitLabConnection` for every project regardless of forge, so a
 *  GitHub-backed project was shown GitLab token prose that could not apply to it — the same
 *  untruth ADR-0112 removed from the Delivery page, still live one screen over.
 *
 *  Built to `GitLabConnection`'s shape on purpose: one status line, one button whose label IS
 *  the state, and a member sees status only (Connect writes a credential-bearing record, which
 *  is admin-only per ADR-0004, enforced server-side — the UI just stops offering a button that
 *  would 403).
 *
 *  Where it legitimately differs from GitLab is the handshake, and only there: GitLab sends the
 *  operator through an OAuth redirect, while GitHub's equivalent redirect hands back an
 *  `installation_id` that GitHub documents as spoofable. So installing the App is an
 *  out-of-band step and Connect is a plain POST whose answer comes from GitHub, about this
 *  project's own repository (ADR-0114). */
export function GitHubConnection({
  project,
  capability,
}: {
  project: Project;
  capability?: DeliveryCapability;
}) {
  const qc = useQueryClient();
  const [err, setErr] = useState<string | null>(null);
  const { data: status } = useQuery({
    queryKey: ["github-status"],
    queryFn: () => api.githubStatus(),
  });
  const { data: repoStatus } = useQuery({
    queryKey: ["github-repo-status"],
    queryFn: () => api.githubRepoStatus(),
  });
  // The outcome of the authorize round-trip, read once from the query string the callback
  // lands on. Left in place: a refresh just re-shows the same terminal result.
  const params = new URLSearchParams(window.location.search);
  const repoCreated = params.get("repo") === "created";
  const repoError = params.get("repo_error");

  const connect = useMutation({
    mutationFn: () => api.connectGithub(project.id),
    onSuccess: () => {
      setErr(null);
      void qc.invalidateQueries({ queryKey: ["delivery-capability", project.id] });
      void qc.invalidateQueries({ queryKey: ["project", project.id] });
    },
    onError: (e: Error) => setErr(e.message),
  });

  const isAdmin = Boolean(status?.is_admin);
  const provider = capability?.provider ?? "gitlab";
  // A project that is not yet ON A FORGE can have a repository made for it — including one
  // whose source is a local path, which is the common case and the one a `!source_repo` test
  // wrongly excluded. A local path is a source; it is not a repository.
  const onAForge = provider === "github" || provider === "gitlab";
  const canCreateRepo = isAdmin && !onAForge && Boolean(repoStatus?.configured);
  const hasLocalSource = !onAForge && Boolean(project.source_repo?.trim());
  const connected = Boolean(capability?.has_github_connection);
  const configured = capability?.github_app_configured ?? status?.configured ?? false;
  const installUrl = status?.install_url ?? "";

  const detail = !onAForge
    ? hasLocalSource
      ? "this project's code is on disk and not on a forge yet"
      : "this project has no repository yet"
    : connected
    ? "delivery mints a fresh token for this repository, valid an hour, never stored"
    : !configured
      ? "no GitHub App is registered on this instance yet"
      : isAdmin
        ? "install the app on this repository, then connect"
        : "Contact your administrator to set up GitHub for this project.";

  return (
    <SettingsSection
      title="GitHub"
      description={
        <p className="text-sm leading-relaxed text-muted-foreground">
          How this project reaches its repository — pushing branches and opening pull requests.
          Delivery authenticates as a GitHub App installation scoped to this one repository, so
          there is no token to paste and none to rotate.
        </p>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border/60 p-3">
          <GitHubMark className="size-5 shrink-0" />
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-foreground">
                {connected ? "Connected to GitHub" : "Not connected"}
              </span>
              <Badge
                className={cn(
                  "font-mono text-[10px] uppercase",
                  connected ? TONE_BADGE.success : TONE_BADGE.neutral,
                )}
              >
                {connected ? "connected" : "no installation"}
              </Badge>
            </div>
            <span className="truncate font-mono text-[11px] text-muted-foreground">{detail}</span>
          </div>
          {isAdmin &&
            (configured ? (
              <Button
                size="sm"
                variant={connected ? "outline" : "default"}
                disabled={connect.isPending}
                onClick={() => connect.mutate()}
              >
                {connect.isPending ? "Connecting…" : connected ? "Recheck" : "Connect GitHub"}
              </Button>
            ) : (
              <Button
                size="sm"
                variant="outline"
                nativeButton={false}
                render={<Link to="/settings/git/github" />}
              >
                Configure GitHub
              </Button>
            ))}
        </div>

        {canCreateRepo && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-dashed border-border/70 px-4 py-3">
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="text-sm font-medium text-foreground">
                {hasLocalSource ? "Not on GitHub yet" : "No repository yet"}
              </span>
              <span className="text-[12.5px] leading-snug text-muted-foreground">
                {hasLocalSource
                  ? `Authorize on ${repoStatus?.host || "github.com"} and Mosaera creates a public repository and pushes this project's history into it.`
                  : `Authorize on ${repoStatus?.host || "github.com"} and Mosaera creates a public repository for this project — nothing to paste.`}
              </span>
            </div>
            {/* A full-page navigation, not a fetch: this is a browser handshake, and the
                session cookie has to ride the redirect (SameSite=Lax). */}
            <Button
              size="sm"
              className="shrink-0"
              nativeButton={false}
              render={<a href={`/api/oauth/github/start?project_id=${project.id}`} />}
            >
              {hasLocalSource ? "Create and push" : "Create repository"}
            </Button>
          </div>
        )}

        {repoCreated && (
          <p className="text-xs text-success">
            Repository created and your project pushed to it — install the app on it, then
            connect.
          </p>
        )}
        {repoError && (
          <p role="alert" className="text-xs text-destructive">
            {repoError}
          </p>
        )}

        {/* Public repositories only for now: a private one cannot be cloned by this system
            yet, so creating one would hand over a repo whose runs never start. */}
        {canCreateRepo && (
          <p className="text-[11.5px] text-muted-foreground/80">
            Public repositories only in this release.
          </p>
        )}

        {/* A limit that holds even when the project is fully connected — stated here rather
            than discovered at the finish line (ADR-0114 §7). */}
        {capability?.note && (
          <p className="text-[11.5px] leading-relaxed text-muted-foreground/80">
            {capability.note}
          </p>
        )}

        {isAdmin && configured && !connected && installUrl && (
          <p className="text-[11.5px] text-muted-foreground/80">
            Not installed on this repository yet?{" "}
            <a
              href={installUrl}
              target="_blank"
              rel="noreferrer"
              className="text-primary underline-offset-2 hover:underline"
            >
              Install the app
            </a>
            , then connect.
          </p>
        )}

        {err && (
          <p role="alert" className="text-xs text-destructive">
            Connect failed: {err}
          </p>
        )}
      </div>
    </SettingsSection>
  );
}
