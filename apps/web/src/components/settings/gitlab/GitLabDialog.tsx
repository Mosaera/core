import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { CopyButton } from "@/components/ui/CopyButton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

import { api, type GitlabStatus, type Project } from "../../../api/client";
import { ConsoleLabel } from "../../overview/bits";
import { GitLabMark } from "./GitLabMark";

/** Surface just the server's `detail` (e.g. the invalid_client message) rather than the raw
 *  "400 Bad Request: {json}" envelope the fetch helper throws. */
export function errDetail(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e);
  const m = raw.match(/\{"detail":\s*"([^"]+)"/);
  return m ? m[1] : raw;
}

type Step = "setup" | "connect";

/** The one GitLab credential surface (ADR-0104, amended). Two steps behind a single modal:
 *  SETUP is instance-scoped (the OAuth application an admin registers once), CONNECT is
 *  project-scoped (authorize, and the server mints this project's token). Opened without a
 *  project — from global Settings — it is setup-only.
 *
 *  Admin-only by construction: the caller renders no button for a member, and every write here
 *  (`saveGitlab`, `setProjectToken`, `/api/oauth/gitlab/start`) is admin-gated server-side
 *  (ADR-0004 secret writes, ADR-0104 §5). Nothing about that gating changes here. */
export function GitLabDialog({
  open,
  onOpenChange,
  project,
  status,
  host,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  project?: Project | null;
  status?: GitlabStatus;
  host?: string;
}) {
  const configured = Boolean(status?.oauth_configured);
  const [step, setStep] = useState<Step>("setup");

  useEffect(() => {
    // Open on whichever step is unsatisfied: no app registered → Setup; app ready and we have a
    // project → straight to Connect. Re-seeded per open so a reopen reflects the current state.
    if (open) setStep(configured && project ? "connect" : "setup");
  }, [open, configured, project]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-label="GitLab connection">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <GitLabMark className="size-4 text-[#FC6D26]" />
            {step === "setup" ? "Set up GitLab" : "Connect GitLab"}
          </DialogTitle>
          <DialogDescription>
            {step === "setup"
              ? `Register one OAuth application on ${host || "your GitLab"}; every project then connects with a click.`
              : `Authorize on ${host || "your GitLab"} and Mosaera provisions this project's token — nothing to paste.`}
          </DialogDescription>
        </DialogHeader>
        {step === "setup" ? (
          <SetupStep
            status={status}
            host={host}
            onReady={() => (project ? setStep("connect") : onOpenChange(false))}
            hasProject={Boolean(project)}
          />
        ) : (
          <ConnectStep project={project!} onChangeApp={() => setStep("setup")} />
        )}
      </DialogContent>
    </Dialog>
  );
}

/** Step 1 — the instance-wide OAuth application. The server VERIFIES the id+secret against the
 *  configured GitLab before storing (routes/settings.py), so a wrong secret fails here rather
 *  than at the first Connect. The secret is write-only and encrypted at rest. */
function SetupStep({
  status,
  host,
  onReady,
  hasProject,
}: {
  status?: GitlabStatus;
  host?: string;
  onReady: () => void;
  hasProject: boolean;
}) {
  const qc = useQueryClient();
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);

  useEffect(() => {
    // Default the base URL to this app's own origin — that IS the public origin the redirect_uri
    // must use, so the operator rarely needs to change it.
    if (!baseUrl) setBaseUrl(status?.base_url || window.location.origin);
  }, [status, baseUrl]);

  const redirectUri = `${(baseUrl || window.location.origin).replace(/\/$/, "")}/oauth/callback`;
  const isSet =
    status?.oauth_configured || status?.oauth_secret_set || Boolean(status?.oauth_client_id_masked);
  const envPinned = Boolean(status?.oauth_env_pinned);
  const locked = saving || envPinned; // env pins the value (env > stored) → the UI can't change it

  async function save() {
    setSaving(true);
    setMsg(null);
    try {
      // Only send what was typed — an empty field means "leave unchanged", never "clear" (so
      // updating the secret alone can't wipe the saved id).
      const body: { base_url?: string; oauth_client_id?: string; oauth_client_secret?: string } = {};
      if (baseUrl.trim()) body.base_url = baseUrl.trim();
      if (clientId.trim()) body.oauth_client_id = clientId.trim();
      if (secret.trim()) body.oauth_client_secret = secret.trim();
      const s = await api.saveGitlab(body);
      setSecret("");
      qc.setQueryData(["gitlab-status"], s);
      qc.invalidateQueries({ queryKey: ["oauth-status"] });
      if (s.oauth_configured) {
        onReady();
        return;
      }
      setMsg(s.oauth_note || "Saved. Add the Application ID + Secret to finish.");
    } catch (e) {
      setMsg(errDetail(e));
    } finally {
      setSaving(false);
    }
  }

  async function disconnect() {
    // Clear all three (the server treats "" as "clear"), so a stale/wrong config can be wiped.
    // Project tokens already minted are untouched — this only removes the app.
    setSaving(true);
    setMsg(null);
    try {
      const s = await api.saveGitlab({ base_url: "", oauth_client_id: "", oauth_client_secret: "" });
      setClientId("");
      setSecret("");
      setBaseUrl("");
      qc.setQueryData(["gitlab-status"], s);
      qc.invalidateQueries({ queryKey: ["oauth-status"] });
      setMsg("Disconnected — the OAuth app is cleared. You can enter new credentials above.");
    } catch (e) {
      setMsg(errDetail(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="flex flex-col gap-3 px-4">
        {envPinned && (
          <p className="rounded-md bg-amber-500/10 px-3 py-2 text-[12px] leading-relaxed text-amber-600 dark:text-amber-400">
            These values are pinned by <span className="font-mono">MOSAERA_GITLAB_OAUTH_*</span>{" "}
            environment variables, which override anything set here — so this form is read-only. To
            change them, edit your <span className="font-mono">.env</span> and restart; to manage
            OAuth from this UI instead, remove those env vars and restart.
          </p>
        )}
        {/* NOT a flex column: a flex container makes its children flex items, which do not
            generate ::marker, so `list-decimal` would silently render nothing. Order is the
            point of these steps — keep this block-level. */}
        <ol className="list-decimal space-y-1 pl-5 text-[12.5px] leading-relaxed text-muted-foreground marker:text-muted-foreground/70">
          <li>
            On <span className="font-mono text-foreground/90">{host || status?.url}</span>, open{" "}
            <b className="text-foreground">Settings → Applications</b> and add a new application.
          </li>
          <li>Paste the redirect URI below and tick the {""}
            <span className="font-mono text-foreground/90">api</span> scope.
          </li>
          <li>Copy the Application ID and Secret it gives you into the two fields below.</li>
        </ol>
        <div className="flex flex-col gap-1 rounded-md bg-muted/30 p-2.5 font-mono text-[11px] leading-relaxed text-muted-foreground">
          <div className="flex items-center gap-1">
            <span className="shrink-0">redirect URI:</span>
            <span className="min-w-0 truncate text-foreground/90">{redirectUri}</span>
            <CopyButton text={redirectUri} label="Copy redirect URI" className="ml-auto" />
          </div>
          <div className="flex items-center gap-1">
            <span className="shrink-0">scope:</span>
            <span className="text-foreground/90">api</span>
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <ConsoleLabel>Mosaera base URL (this app&rsquo;s public origin)</ConsoleLabel>
          <Input
            aria-label="Mosaera base URL"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://mosaera.example.com"
            className="text-sm"
            disabled={locked}
          />
        </div>
        <div className="flex flex-col gap-1">
          <ConsoleLabel>
            Application ID{" "}
            {status?.oauth_client_id_masked ? `(saved: ${status.oauth_client_id_masked})` : ""}
          </ConsoleLabel>
          <Input
            aria-label="OAuth application id"
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            placeholder={
              status?.oauth_client_id_masked ? "leave blank to keep the saved id" : "application id"
            }
            className="font-mono text-xs"
            disabled={locked}
          />
        </div>
        <div className="flex flex-col gap-1">
          <ConsoleLabel>Secret {status?.oauth_secret_set ? "(saved)" : ""}</ConsoleLabel>
          <Input
            type="password"
            aria-label="OAuth application secret"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            placeholder={
              status?.oauth_secret_set ? "leave blank to keep the saved secret" : "application secret"
            }
            className="font-mono text-xs"
            disabled={locked}
          />
        </div>
        {msg && <p className="font-mono text-xs text-muted-foreground">{msg}</p>}
        <p className="font-mono text-[11px] leading-relaxed text-muted-foreground/70">
          The secret is write-only and encrypted at rest when MOSAERA_SECRET_KEY is set (else 0600
          plaintext). MOSAERA_GITLAB_OAUTH_* env vars override these.
        </p>
      </div>
      <DialogFooter className="flex-row items-center gap-2">
        <Button size="sm" onClick={() => void save()} disabled={locked}>
          {saving ? "Saving…" : isSet ? "Update app" : hasProject ? "Save and continue" : "Save app"}
        </Button>
        {isSet && !envPinned && (
          <Button
            size="sm"
            variant="destructive"
            onClick={() => setConfirmDisconnect(true)}
            disabled={saving}
          >
            Disconnect
          </Button>
        )}
      </DialogFooter>
      <ConfirmDialog
        open={confirmDisconnect}
        onOpenChange={setConfirmDisconnect}
        title="Disconnect the OAuth application?"
        confirmLabel="Disconnect"
        busyLabel="Disconnecting…"
        busy={saving}
        onConfirm={() => {
          setConfirmDisconnect(false);
          void disconnect();
        }}
      >
        <p>
          This clears the OAuth application for the <b className="text-foreground">whole instance</b>
          , so every project loses the Connect button and falls back to pasting a token.
        </p>
        <p className="mt-2">
          The client secret is write-only — Mosaera can&rsquo;t show it to you and can&rsquo;t put it
          back. Reconnecting means generating a new secret on {host || "your GitLab"}. Project tokens
          already provisioned keep working.
        </p>
      </ConfirmDialog>
    </>
  );
}

/** Step 2 — authorize, and the server mints this project's token. The manual PAT path survives
 *  as a disclosure: it is the fallback when OAuth can't be used, not the headline (ADR-0103). */
function ConnectStep({ project, onChangeApp }: { project: Project; onChangeApp: () => void }) {
  return (
    <>
      <div className="flex flex-col gap-3 px-4">
        <p className="text-[12.5px] leading-relaxed text-muted-foreground">
          The token is scoped to this project and stays revocable in GitLab. Mosaera keeps no GitLab
          identity of yours — the authorization is used once, to mint the token, and discarded.
        </p>
        <Button
          className="w-fit"
          // A full-page navigation (a browser OAuth handshake), NOT a fetch: the server 302s to
          // GitLab and back to this project's Integration pane.
          onClick={() =>
            window.location.assign(`/api/oauth/gitlab/start?project_id=${project.id}`)
          }
        >
          Authorize with GitLab
        </Button>
        <button
          type="button"
          onClick={onChangeApp}
          className="w-fit border-0 bg-transparent p-0 text-left text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        >
          Change the OAuth application
        </button>
        <ManualTokens project={project} />
      </div>
    </>
  );
}

/** The ADR-0103 credential pair, kept as an explicit fallback behind a disclosure.
 *  Field semantics are the server's: untouched → unchanged, "" → cleared. */
function ManualTokens({ project }: { project: Project }) {
  const qc = useQueryClient();
  const [token, setToken] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [saved, setSaved] = useState(false);

  const update = useMutation({
    mutationFn: () =>
      api.setProjectToken(
        project.id,
        token.trim() ? token.trim() : undefined, // untouched → leave the push token unchanged
        apiToken.trim() ? apiToken.trim() : undefined,
      ),
    onSuccess: (resp) => {
      qc.setQueryData(["project", project.id], resp);
      setToken("");
      setApiToken("");
      setSaved(true);
    },
  });

  return (
    <details className="rounded-md border border-border/60 p-2.5">
      <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
        Enter a token manually instead
      </summary>
      <div className="mt-3 flex flex-col gap-3">
        <p className="text-[11.5px] leading-relaxed text-muted-foreground">
          The <span className="font-mono">write_repository</span> token does all git transport; the
          optional <span className="font-mono">api</span>-scoped token lets you edit the MR
          body/labels and pick a target branch before sending.
        </p>
        <div className="flex flex-col gap-1.5">
          <p className="font-mono text-xs text-muted-foreground">
            Push token (write_repository): {project.gitlab_token_masked || "none"}
          </p>
          <Input
            type="password"
            aria-label="New GitLab push token"
            placeholder="glpat-… (write_repository)"
            className="font-mono text-xs"
            value={token}
            onChange={(e) => {
              setToken(e.target.value);
              setSaved(false);
            }}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <p className="font-mono text-xs text-muted-foreground">
            API token (optional, api scope): {project.has_gitlab_api_token ? "set" : "none"}
          </p>
          <Input
            type="password"
            aria-label="New GitLab api token"
            placeholder="glpat-… (api scope)"
            className="font-mono text-xs"
            value={apiToken}
            onChange={(e) => {
              setApiToken(e.target.value);
              setSaved(false);
            }}
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            disabled={(!token.trim() && !apiToken.trim()) || update.isPending}
            onClick={() => update.mutate()}
          >
            Update tokens
          </Button>
          {saved && <span className="text-xs text-success">Tokens updated.</span>}
        </div>
        {update.isError && (
          <p role="alert" className="text-xs text-destructive">
            {errDetail(update.error)}
          </p>
        )}
      </div>
    </details>
  );
}
