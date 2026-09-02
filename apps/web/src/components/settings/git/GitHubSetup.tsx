import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../../api/client";
import { Button } from "@/components/ui/button";

import { CopyValue, Field, SetupWizard, Steps } from "./SetupWizard";

/** First-run GitHub setup: one click, nothing typed.
 *
 *  GitHub's App-manifest flow lets Mosaera hand GitHub a description of the App it wants; the
 *  operator presses one button on github.com and GitHub returns the app id, private key, slug,
 *  client id and client secret in a single response. So where GitLab has a five-field form (it
 *  has no equivalent), GitHub has a button — and the credentials never pass through a clipboard.
 *
 *  The manual form stays, one link away, for an operator who already registered an App and would
 *  rather paste than create a second one. It is not the default because making everyone copy five
 *  values — one of them a multi-line private key — is exactly the setup this removes. */
export function GitHubSetup({ onDone }: { onDone: () => void }) {
  const [manual, setManual] = useState(false);
  const params = new URLSearchParams(window.location.search);
  const setupError = params.get("setup_error");

  // The browser must POST the manifest to github.com as a form — a fetch cannot navigate the
  // operator there, and GitHub's flow is a page they have to see and approve.
  const register = useMutation({
    mutationFn: () => api.githubSetupManifest(),
    onSuccess: (data) => {
      const form = document.createElement("form");
      form.method = "POST";
      form.action = data.url;
      const field = document.createElement("input");
      field.type = "hidden";
      field.name = "manifest";
      field.value = data.manifest;
      form.appendChild(field);
      document.body.appendChild(form);
      form.submit();
    },
  });

  if (manual) return <ManualApp onBack={() => setManual(false)} onDone={onDone} />;

  return (
    <div className="flex flex-col items-stretch gap-3">
      <p className="text-[12.5px] leading-relaxed text-muted-foreground">
        Mosaera creates the app for you — you approve it on GitHub and nothing is copied back by
        hand.
      </p>
      {
        <Steps
          items={[
            <>
              Press <b className="text-foreground">Create GitHub App</b> — it takes you to GitHub.
            </>,
            <>Choose the account or organization the app belongs to, and confirm.</>,
            <>
              GitHub sends you back and Mosaera stores the credentials. It asks for{" "}
              <CopyValue>Contents: read &amp; write</CopyValue> and{" "}
              <CopyValue>Pull requests: read &amp; write</CopyValue> — the two permissions
              delivery uses, and nothing else.
            </>,
          ]}
        />
      }
      {(setupError || register.error) && (
        <p role="alert" className="text-xs text-destructive">
          {setupError || (register.error as Error)?.message}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" disabled={register.isPending} onClick={() => register.mutate()}>
          {register.isPending ? "Opening GitHub…" : "Create GitHub App"}
        </Button>
        <button
          type="button"
          onClick={() => setManual(true)}
          className="border-0 bg-transparent p-0 text-[12.5px] text-primary underline-offset-2 hover:underline"
        >
          I already have one
        </button>
      </div>
    </div>
  );
}

/** The escape hatch: an App the operator registered themselves. Every field is required — a
 *  half-configured App fails much later, at a connect, with an error pointing nowhere near here,
 *  so the server refuses the write and the private key is checked for readability up front. */
function ManualApp({ onBack, onDone }: { onBack: () => void; onDone: () => void }) {
  const [f, setF] = useState({
    app_id: "",
    private_key: "",
    slug: "",
    client_id: "",
    client_secret: "",
  });
  const set = (k: keyof typeof f) => (v: string) => setF((p) => ({ ...p, [k]: v }));

  const save = useMutation({
    mutationFn: () => api.githubSetupManual(f),
    onSuccess: onDone,
  });

  return (
    <SetupWizard
      step={1}
      steps={3}
      title="Use an existing GitHub App"
      description="Paste the app's details. You will find these on the app's settings page on GitHub."
      instructions={
        <Steps
          items={[
            <>
              Open the app on GitHub →{" "}
              <b className="text-foreground">Settings → Developer settings → GitHub Apps</b>.
            </>,
            <>
              Permissions must include <CopyValue>Contents: read &amp; write</CopyValue> and{" "}
              <CopyValue>Pull requests: read &amp; write</CopyValue>.
            </>,
            <>Generate a private key if you do not have the PEM, and copy it whole.</>,
          ]}
        />
      }
      onBack={onBack}
      onContinue={() => save.mutate()}
      continueLabel={save.isPending ? "Saving…" : "Save"}
      continueDisabled={save.isPending}
    >
      <div className="flex flex-col gap-3">
        <Field label="App ID" value={f.app_id} onChange={set("app_id")} placeholder="123456" mono />
        <Field
          label="App slug"
          hint="The name in the app's URL — github.com/apps/<slug>."
          value={f.slug}
          onChange={set("slug")}
          placeholder="mosaera"
          mono
        />
        <Field
          label="Client ID"
          value={f.client_id}
          onChange={set("client_id")}
          placeholder="Iv1.0123456789abcdef"
          mono
        />
        <Field
          label="Client secret"
          type="password"
          value={f.client_secret}
          onChange={set("client_secret")}
          placeholder="the app's client secret"
          mono
        />
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-medium text-foreground">Private key (PEM)</span>
          <textarea
            value={f.private_key}
            onChange={(e) => setF((p) => ({ ...p, private_key: e.target.value }))}
            placeholder="-----BEGIN RSA PRIVATE KEY-----"
            rows={4}
            className="w-full resize-y rounded-md border border-border/70 bg-background px-3 py-2 font-mono text-xs outline-none transition-colors placeholder:text-muted-foreground/60 focus:border-ring"
          />
          <span className="text-[11.5px] text-muted-foreground">
            Stored encrypted and never shown again.
          </span>
        </label>
      </div>
      {save.error && (
        <p role="alert" className="text-xs text-destructive">
          {(save.error as Error).message}
        </p>
      )}
    </SetupWizard>
  );
}
