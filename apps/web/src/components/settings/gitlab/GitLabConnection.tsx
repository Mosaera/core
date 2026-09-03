import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { cn } from "@/lib/utils";

import { api, type Project } from "../../../api/client";
import { TONE_BADGE } from "../../StatusBadge";
import { SettingsSection } from "../SettingsSection";
import { GitLabDialog } from "./GitLabDialog";
import { GitLabMark } from "./GitLabMark";

/** The ?oauth=connected / ?oauth_error=… the server's callback lands on (ADR-0104). Read once for
 *  a banner; the query string is left as-is (a refresh just re-shows the same terminal outcome). */
export function useOauthResult(): { ok: boolean; error: string | null } {
  const params = new URLSearchParams(window.location.search);
  return { ok: params.get("oauth") === "connected", error: params.get("oauth_error") };
}

/** The ONE GitLab control. Every credential path for a project starts here: one button whose
 *  label is the state — Connect (app registered, project not linked) · Configure (no app yet) ·
 *  Manage (already linked) — opening the single dialog.
 *
 *  A member sees status and nothing else. That is not a UI preference: Connect mints and stores a
 *  project credential, and secret writes are admin-only (ADR-0004), which the start endpoint and
 *  the OAuth callback both enforce server-side (ADR-0104 §5). The UI just stops offering a button
 *  that would 403. */
export function GitLabConnection({ project }: { project: Project }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const recheck = useMutation({ mutationFn: () => api.gitlabRecheck(project.id) });
  const disconnect = useMutation({
    mutationFn: () => api.disconnectProjectGitlab(project.id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["project", project.id] });
      void qc.invalidateQueries({ queryKey: ["delivery-capability", project.id] });
    },
  });
  const { data: oauth } = useQuery({
    queryKey: ["oauth-status"],
    queryFn: () => api.gitlabOauthStatus(),
  });
  // Powers the dialog's Setup step (masked client id, env-pinning, base URL). Only fetched for an
  // admin — a member never opens the dialog.
  const isAdmin = Boolean(oauth?.is_admin);
  const { data: status } = useQuery({
    queryKey: ["gitlab-status"],
    queryFn: () => api.gitlabStatus(),
    enabled: isAdmin,
  });
  const result = useOauthResult();

  const host = oauth?.host || "your GitLab";
  const connected = Boolean(project.has_gitlab_token);
  const appReady = Boolean(oauth?.configured);
  const action = connected ? "Manage" : appReady ? "Connect GitLab" : "Configure GitLab";

  return (
    <SettingsSection
      title="GitLab"
      description={
        <p className="text-sm leading-relaxed text-muted-foreground">
          How this project reaches its repository — pushing branches and opening merge requests.
          The credential is scoped to this project, stored write-only, and revocable in GitLab at
          any time.
        </p>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border/60 p-3">
          <GitLabMark className="size-5 shrink-0 text-[#FC6D26]" />
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-foreground">
                {connected ? `Connected to ${host}` : "Not connected"}
              </span>
              <Badge
                className={cn(
                  "font-mono text-[10px] uppercase",
                  connected ? TONE_BADGE.success : TONE_BADGE.neutral,
                )}
              >
                {connected ? "connected" : "no credential"}
              </Badge>
            </div>
            <span className="truncate font-mono text-[11px] text-muted-foreground">
              {connected
                ? `token ${project.gitlab_token_masked || "set"} · api scope ${
                    project.has_gitlab_api_token ? "✓" : "✗ (MR body/target locked)"
                  }`
                : isAdmin
                  ? appReady
                    ? `authorize on ${host} — nothing to paste`
                    : "no OAuth application registered on this instance yet"
                  : "Contact your administrator to set up GitLab for this project."}
            </span>
          </div>
          {isAdmin && (
            <div className="flex shrink-0 items-center gap-2">
              <Button size="sm" variant={connected ? "outline" : "default"} onClick={() => setOpen(true)}>
                {action}
              </Button>
              {connected && (
                <>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={recheck.isPending}
                    onClick={() => recheck.mutate()}
                  >
                    {recheck.isPending ? "Rechecking…" : "Recheck"}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-destructive"
                    disabled={disconnect.isPending}
                    onClick={() => setConfirmDisconnect(true)}
                  >
                    {disconnect.isPending ? "Disconnecting…" : "Disconnect"}
                  </Button>
                </>
              )}
            </div>
          )}
        </div>
        {/* task 4B-i: a stored token bit is presence, not proof — Recheck spends one cheap
            authenticated read with THIS project's own token. */}
        {recheck.data && (
          <p
            className={cn(
              "text-xs",
              recheck.data.verified ? "text-success" : "text-amber-600 dark:text-amber-400",
            )}
          >
            {recheck.data.verified
              ? "Verified just now."
              : `Credential rejected: ${recheck.data.error || "unknown reason"}.`}
          </p>
        )}
        {result.ok && <p className="text-xs text-success">Connected — project token provisioned.</p>}
        {result.error && (
          <p role="alert" className="text-xs text-destructive">
            Connect failed: {result.error}
          </p>
        )}
      </div>
      {isAdmin && (
        <GitLabDialog
          open={open}
          onOpenChange={setOpen}
          project={project}
          status={status}
          host={oauth?.host}
        />
      )}
      <ConfirmDialog
        open={confirmDisconnect}
        onOpenChange={setConfirmDisconnect}
        title="Disconnect this project from GitLab?"
        confirmLabel="Disconnect"
        busyLabel="Disconnecting…"
        busy={disconnect.isPending}
        onConfirm={() => {
          disconnect.mutate();
          setConfirmDisconnect(false);
        }}
      >
        <p>
          Clears this project&rsquo;s stored push and api tokens. Delivery has nothing to push
          with until a new credential is provisioned. The token itself is not revoked in
          GitLab — do that there if that is what you want.
        </p>
      </ConfirmDialog>
    </SettingsSection>
  );
}
