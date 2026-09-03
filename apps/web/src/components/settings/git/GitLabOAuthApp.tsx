import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";

import { api } from "../../../api/client";
import { CopyValue, Field, Steps, SubItems } from "./SetupWizard";

/** The OAuth application a project authorizes against (ADR-0104).
 *
 *  GitLab's counterpart to registering the GitHub App — and, unlike GitHub, it cannot be
 *  automated: there is no manifest flow, so the operator creates it by hand. What this step can
 *  do is remove every ambiguity in that: the redirect URI, the scope and the confidential flag are
 *  stated exactly, and the redirect URI is DERIVED from this instance rather than written down,
 *  because a hardcoded one is wrong for every self-hosted install and wrong in the way that only
 *  surfaces much later as an opaque OAuth error.
 *
 *  Registering this once is what lets every project connect by authorizing instead of pasting a
 *  personal token — which is the whole point of ADR-0104 and worth saying, since the alternative
 *  still exists and looks easier. */
export function GitLabOAuthApp({
  host,
  configured,
  clientIdMasked,
  envPinned,
}: {
  host: string;
  configured: boolean;
  clientIdMasked?: string | null;
  envPinned?: boolean;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ id: "", secret: "" });
  const set = (k: keyof typeof f) => (v: string) => setF((p) => ({ ...p, [k]: v }));

  const callback = `${window.location.origin}/oauth/callback`;
  // The repo-CREATE flow authorizes against its own callback (routes/gitlab_repo.py). GitLab
  // validates redirect URIs against the registered list, so BOTH must be registered (the form
  // takes one per line) — found live 2026-09-03: an app registered with only /oauth/callback
  // makes "Create repository" die on GitLab's error page instead of the consent screen.
  const createCallback = `${window.location.origin}/oauth/gitlab/create/callback`;
  const save = useMutation({
    mutationFn: () =>
      api.saveGitlab({
        base_url: window.location.origin,
        oauth_client_id: f.id.trim(),
        oauth_client_secret: f.secret.trim(),
      }),
    onSuccess: () => {
      setOpen(false);
      void qc.invalidateQueries({ queryKey: ["gitlab-status"] });
      void qc.invalidateQueries({ queryKey: ["oauth-status"] });
    },
  });

  if (envPinned) {
    return (
      <p className="text-[12.5px] leading-relaxed text-muted-foreground">
        Set by environment variables on this instance, so it is read-only here. Change{" "}
        <CopyValue>MOSAERA_GITLAB_OAUTH_CLIENT_ID</CopyValue> /{" "}
        <CopyValue>_SECRET</CopyValue> to replace it.
      </p>
    );
  }

  if (configured && !open) {
    return (
      <>
        <p className="text-[12.5px] leading-relaxed text-muted-foreground">
          Registered on <span className="text-foreground/90">{host}</span>
          {clientIdMasked ? (
            <>
              {" "}
              as <span className="font-mono text-[11.5px] text-foreground/90">{clientIdMasked}</span>
            </>
          ) : null}
          . Projects connect by authorizing against it — nothing to paste per project.
        </p>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="w-fit border-0 bg-transparent p-0 text-[12.5px] text-primary underline-offset-2 hover:underline"
        >
          Replace it
        </button>
      </>
    );
  }

  return (
    <div className="flex flex-col items-stretch gap-3">
      <p className="text-[12.5px] leading-relaxed text-muted-foreground">
        Registered once on <span className="text-foreground/90">{host}</span>. It is what lets each
        project connect by authorizing, instead of you creating and pasting a token per project.
      </p>

      <div className="rounded-lg bg-muted/30 p-4 ring-1 ring-white/10">
        <h4 className="mb-2 text-[13px] font-semibold text-foreground">Setup instructions</h4>
        <Steps
          items={[
            <>
              On {host}, open{" "}
              <b className="text-foreground">Admin &gt; Applications</b> (or your user{" "}
              <b className="text-foreground">Settings &gt; Applications</b> if you are not an
              instance admin)
            </>,
            <>
              Create an application with:
              <SubItems
                items={[
                  <>
                    <b className="text-foreground">Redirect URIs</b> (both, one per line):{" "}
                    <CopyValue>{callback}</CopyValue> <CopyValue>{createCallback}</CopyValue>
                  </>,
                  <>
                    <b className="text-foreground">Scopes:</b> <CopyValue>api</CopyValue>
                  </>,
                  <>
                    <b className="text-foreground">Confidential:</b>{" "}
                    <span className="text-foreground/90">Yes</span>
                  </>,
                ]}
              />
            </>,
            <>Copy the Application ID and secret below</>,
          ]}
        />
      </div>

      <div className="flex flex-col gap-3">
        <Field
          label="Application ID"
          value={f.id}
          onChange={set("id")}
          placeholder="Your OAuth application ID"
          mono
        />
        <Field
          label="Application secret"
          type="password"
          value={f.secret}
          onChange={set("secret")}
          placeholder="Your OAuth application secret"
          mono
        />
      </div>

      {save.error && (
        <p role="alert" className="text-xs text-destructive">
          {(save.error as Error).message}
        </p>
      )}

      <div className="flex items-center gap-3">
        <Button
          size="sm"
          disabled={!f.id.trim() || !f.secret.trim() || save.isPending}
          onClick={() => save.mutate()}
        >
          {save.isPending ? "Saving…" : "Save"}
        </Button>
        {configured && (
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="border-0 bg-transparent p-0 text-[12.5px] text-muted-foreground hover:text-foreground"
          >
            Cancel
          </button>
        )}
      </div>

      <p className="text-[11.5px] leading-relaxed text-muted-foreground/80">
        The secret is checked against your instance before it is stored, so a wrong value is caught
        here rather than at the first connect. It is kept encrypted and never shown again.
      </p>
    </div>
  );
}
