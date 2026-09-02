import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../../api/client";
import { CopyValue, Field, Steps } from "./SetupWizard";

/** Configure the credential that creates repositories — an **OAuth App**, not the GitHub App.
 *
 *  This exists because GitHub draws the line here and we found it the hard way: creating a
 *  repository with a GitHub App user token returns `403 Resource not accessible by integration`.
 *  App tokens are refused outright by the repository-creation endpoints, which accept OAuth-app
 *  and classic personal tokens only.
 *
 *  So unlike the App itself — which registers in one click via the manifest flow — this is a form,
 *  because GitHub has no manifest equivalent for an OAuth App. The wizard's job is the same as
 *  GitLab's: state the callback URL and scope exactly, derived from THIS instance so a
 *  self-hosted origin is never wrong. */
export function GitHubRepoCreation({ configured }: { configured: boolean }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ client_id: "", client_secret: "" });
  const set = (k: keyof typeof f) => (v: string) => setF((p) => ({ ...p, [k]: v }));

  const callback = `${window.location.origin}/oauth/github/callback`;
  const save = useMutation({
    mutationFn: () => api.githubSetupOAuthApp(f),
    onSuccess: () => {
      setOpen(false);
      void qc.invalidateQueries({ queryKey: ["github-repo-status"] });
    },
  });

  if (configured && !open) {
    return (
      <>
        <p className="text-[12.5px] leading-relaxed text-muted-foreground">
          An OAuth App is configured, so a project with no repository can have one created and its
          history pushed into it.
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
        Only needed if you want Mosaera to make repositories for projects that have none. GitHub
        refuses to create a repository with a GitHub App token, so this takes a separate{" "}
        <b className="text-foreground">OAuth App</b>. Skip it and everything else still works —
        projects just have to arrive with a repository.
      </p>

      <div className="rounded-lg bg-muted/30 p-4 ring-1 ring-white/10">
        <h4 className="mb-2 text-[13px] font-semibold text-foreground">Setup instructions</h4>
        <Steps
          items={[
            <>
              Go to <b className="text-foreground">Settings → Developer settings → OAuth Apps → New
              OAuth App</b> on GitHub
            </>,
            <>
              Set the <b className="text-foreground">Authorization callback URL</b> to{" "}
              <CopyValue>{callback}</CopyValue>
            </>,
            <>Generate a client secret, then copy the client ID and secret below</>,
          ]}
        />
      </div>

      <div className="flex flex-col gap-3">
        <Field
          label="Client ID"
          value={f.client_id}
          onChange={set("client_id")}
          placeholder="Ov23li…"
          mono
        />
        <Field
          label="Client secret"
          type="password"
          value={f.client_secret}
          onChange={set("client_secret")}
          placeholder="the OAuth app's client secret"
          mono
        />
      </div>

      {save.error && (
        <p role="alert" className="text-xs text-destructive">
          {(save.error as Error).message}
        </p>
      )}

      <button
        type="button"
        onClick={() => save.mutate()}
        disabled={!f.client_id.trim() || !f.client_secret.trim() || save.isPending}
        className="w-fit rounded-md border-0 bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/80 disabled:pointer-events-none disabled:opacity-50"
      >
        {save.isPending ? "Saving…" : "Save"}
      </button>
    </div>
  );
}
