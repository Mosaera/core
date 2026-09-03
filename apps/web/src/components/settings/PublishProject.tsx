import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";

import { api, type Project } from "../../api/client";
import { GitHubMark } from "./git/GitHubMark";
import { GitLabMark } from "./gitlab/GitLabMark";
import { SettingsSection } from "./SettingsSection";

/** A project whose code is not on a forge yet, and what can be done about it (ADR-0120/0125).
 *
 *  Both providers can create a repository and push this project's history into it, so both are
 *  offered — and only the ones this instance can actually perform. Withholding an option is the
 *  honest form of "not configured"; offering a button that fails at the far end of a redirect is
 *  not.
 *
 *  The visibility difference is stated per provider rather than smoothed over, because it is real
 *  and the operator is choosing: GitLab is created private (`clone.py` can authenticate a private
 *  clone on the configured host), GitHub public (it cannot, yet — so a private repo there would be
 *  one whose runs never start). */
export function PublishProject({ project }: { project: Project }) {
  const { data: gh } = useQuery({
    queryKey: ["github-repo-status"],
    queryFn: () => api.githubRepoStatus(),
  });
  const { data: gl } = useQuery({
    queryKey: ["gitlab-repo-status"],
    queryFn: () => api.gitlabRepoStatus(),
  });

  const isAdmin = Boolean(gh?.is_admin || gl?.is_admin);
  const hasLocalSource = Boolean(project.source_repo?.trim());
  const options = [
    {
      key: "github",
      ready: Boolean(gh?.configured),
      mark: <GitHubMark className="size-5 shrink-0" />,
      name: "GitHub",
      note: "Created public — Mosaera cannot clone a private GitHub repository yet.",
      href: `/api/oauth/github/start?project_id=${project.id}`,
    },
    {
      key: "gitlab",
      ready: Boolean(gl?.configured),
      mark: <GitLabMark className="size-5 shrink-0 text-[#FC6D26]" />,
      name: gl?.host || "GitLab",
      note: "Created private, and connected in the same step.",
      href: `/api/oauth/gitlab/create/start?project_id=${project.id}`,
    },
  ];
  const available = options.filter((o) => o.ready);

  return (
    <SettingsSection
      title="Repository"
      description={
        <p className="text-sm leading-relaxed text-muted-foreground">
          {hasLocalSource
            ? "This project's code is on this server and not on a forge yet. Publishing it creates a repository and pushes the project's history into it."
            : "This project has no repository yet. Publishing it creates one and points the project at it."}
        </p>
      }
    >
      {!isAdmin ? (
        <p className="text-[12.5px] text-muted-foreground">
          Contact your administrator to publish this project.
        </p>
      ) : available.length === 0 ? (
        <div className="flex flex-col gap-2 rounded-lg border border-dashed border-border/70 px-4 py-4">
          <p className="text-[12.5px] leading-relaxed text-muted-foreground">
            No forge on this instance can create a repository yet. Work still runs, commits and
            validates normally — only publishing is unavailable.
          </p>
          <Button
            size="sm"
            variant="outline"
            className="w-fit"
            nativeButton={false}
            render={<Link to="/settings/git" />}
          >
            Set one up
          </Button>
        </div>
      ) : (
        <div className="flex flex-col items-stretch gap-2">
          {available.map((o) => (
            <div
              key={o.key}
              className="flex items-center justify-between gap-3 rounded-lg border border-border/60 p-3"
            >
              <div className="flex min-w-0 items-center gap-3">
                {o.mark}
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="text-sm font-medium text-foreground">{o.name}</span>
                  <span className="text-[12.5px] leading-snug text-muted-foreground">{o.note}</span>
                </span>
              </div>
              {/* A full-page navigation, not a fetch: this is a browser handshake and the session
                  cookie has to ride the redirect (SameSite=Lax). */}
              <Button
                size="sm"
                className="shrink-0"
                nativeButton={false}
                render={<a href={o.href} />}
              >
                {hasLocalSource ? "Create and push" : "Create repository"}
              </Button>
            </div>
          ))}
        </div>
      )}
    </SettingsSection>
  );
}
