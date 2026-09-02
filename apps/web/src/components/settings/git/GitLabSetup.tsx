import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../../api/client";
import { CopyValue, Field, SetupWizard, Steps, SubItems } from "./SetupWizard";

/** First-run GitLab setup.
 *
 *  GitLab has no manifest flow, so unlike GitHub this genuinely is a form: the operator creates
 *  an OAuth application in their own admin panel and copies two values back. The wizard's job is
 *  to make that unambiguous — the redirect URI, the scope and the confidential flag are stated
 *  exactly, and the redirect URI is DERIVED from this instance rather than written down, because a
 *  hardcoded one is wrong for every self-hosted install and silently wrong at that (the mismatch
 *  surfaces as an opaque OAuth error much later).
 *
 *  Self-hosted first throughout: nothing here assumes gitlab.com. */
export function GitLabSetup({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState({
    url: "",
    oauth_client_id: "",
    oauth_client_secret: "",
  });
  const set = (k: keyof typeof f) => (v: string) => setF((p) => ({ ...p, [k]: v }));

  // The instance's own public origin. `base_url` is what the server uses to build the exact
  // redirect_uri it will send, so the value shown here and the value sent are the same value.
  const origin = window.location.origin;
  const redirectUri = `${origin}/oauth/callback`;

  const save = useMutation({
    mutationFn: () =>
      api.saveGitlab({
        url: f.url.trim(),
        base_url: origin,
        oauth_client_id: f.oauth_client_id.trim(),
        oauth_client_secret: f.oauth_client_secret.trim(),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["gitlab-status"] });
      void qc.invalidateQueries({ queryKey: ["oauth-status"] });
      onDone();
    },
  });

  const ready = Boolean(
    f.url.trim() && f.oauth_client_id.trim() && f.oauth_client_secret.trim(),
  );

  return (
    <SetupWizard
      step={1}
      steps={3}
      title="Configure GitLab instance"
      description="Enter your GitLab instance details. You'll need to create an OAuth application in your GitLab admin panel first."
      instructions={
        <Steps
          items={[
            <>
              Go to your GitLab instance&rsquo;s{" "}
              <b className="text-foreground">Admin &gt; Applications</b> page
            </>,
            <>
              Create a new application with:
              <SubItems
                items={[
                  <>
                    <b className="text-foreground">Redirect URI:</b>{" "}
                    <CopyValue>{redirectUri}</CopyValue>
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
      }
      onContinue={() => save.mutate()}
      continueLabel={save.isPending ? "Saving…" : "Continue"}
      continueDisabled={!ready || save.isPending}
    >
      <div className="flex flex-col gap-3">
        <Field
          label="GitLab URL"
          hint="The URL of your self-hosted GitLab instance"
          value={f.url}
          onChange={set("url")}
          placeholder="https://gitlab.company.com"
        />
        <Field
          label="Application ID"
          value={f.oauth_client_id}
          onChange={set("oauth_client_id")}
          placeholder="Your OAuth application ID"
          mono
        />
        <Field
          label="Application secret"
          type="password"
          value={f.oauth_client_secret}
          onChange={set("oauth_client_secret")}
          placeholder="Your OAuth application secret"
          mono
        />
      </div>
      {save.error && (
        <p role="alert" className="text-xs text-destructive">
          {(save.error as Error).message}
        </p>
      )}
      <p className="text-[11.5px] leading-relaxed text-muted-foreground/80">
        The secret is verified against your instance before it is stored, so a wrong value is
        caught here rather than at the first connect. It is kept encrypted and never shown again.
      </p>
    </SetupWizard>
  );
}
