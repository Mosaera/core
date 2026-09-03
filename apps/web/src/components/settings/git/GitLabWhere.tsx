import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { api } from "../../../api/client";
import { Field } from "./SetupWizard";

const GITLAB_COM = "https://gitlab.com";

/** Which GitLab this instance talks to — the one step GitHub has no equivalent for.
 *
 *  It comes FIRST because everything after it derives from the answer: the OAuth application is
 *  registered on that host, and the redirect URI and API calls are all built from it. Asking for
 *  an application id before knowing where the application lives is the ordering that made the old
 *  form feel like a pile of fields rather than a sequence.
 *
 *  Self-managed is not an afterthought here. Mosaera's GitLab support has always derived every
 *  endpoint from `gitlab_url` rather than assuming gitlab.com (ADR-0104), so the choice is real
 *  rather than cosmetic — it is just never been asked plainly before. */
export function GitLabWhere({ url, onDone }: { url: string; onDone: () => void }) {
  const qc = useQueryClient();
  const configured = Boolean(url.trim());
  const [editing, setEditing] = useState(!configured);
  const [kind, setKind] = useState<"com" | "self">(
    configured && url.trim() !== GITLAB_COM ? "self" : "com",
  );
  const [host, setHost] = useState(configured && url !== GITLAB_COM ? url : "");

  const save = useMutation({
    mutationFn: () => api.saveGitlab({ url: kind === "com" ? GITLAB_COM : host.trim() }),
    onSuccess: () => {
      setEditing(false);
      void qc.invalidateQueries({ queryKey: ["gitlab-status"] });
      void qc.invalidateQueries({ queryKey: ["oauth-status"] });
      onDone();
    },
  });

  if (configured && !editing) {
    return (
      <>
        <p className="text-[12.5px] leading-relaxed text-muted-foreground">
          {url === GITLAB_COM ? (
            <>Using <span className="text-foreground/90">gitlab.com</span>.</>
          ) : (
            <>
              Using your own instance at{" "}
              <span className="font-mono text-[11.5px] text-foreground/90">{url}</span>.
            </>
          )}
        </p>
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="w-fit border-0 bg-transparent p-0 text-[12.5px] text-primary underline-offset-2 hover:underline"
        >
          Change
        </button>
      </>
    );
  }

  const ready = kind === "com" || host.trim().startsWith("http");

  return (
    <div className="flex flex-col items-stretch gap-3">
      <p className="text-[12.5px] leading-relaxed text-muted-foreground">
        Everything after this is registered on the instance you choose, so it comes first.
      </p>

      <div className="flex flex-col gap-2">
        {(
          [
            ["com", "GitLab.com", "The hosted service at gitlab.com"],
            ["self", "Self-managed", "Your own instance, at your own domain"],
          ] as const
        ).map(([value, label, hint]) => (
          <button
            key={value}
            type="button"
            onClick={() => setKind(value)}
            aria-pressed={kind === value}
            className={cn(
              "flex items-start gap-3 rounded-lg border p-3 text-left transition-colors",
              kind === value
                ? "border-primary/60 bg-primary/5"
                : "border-border/60 hover:bg-muted/30",
            )}
          >
            <span
              aria-hidden
              className={cn(
                "mt-0.5 size-3.5 shrink-0 rounded-full border-2",
                kind === value ? "border-primary bg-primary" : "border-border",
              )}
            />
            <span className="flex min-w-0 flex-col gap-0.5">
              <span className="text-sm font-medium text-foreground">{label}</span>
              <span className="text-[12.5px] text-muted-foreground">{hint}</span>
            </span>
          </button>
        ))}
      </div>

      {kind === "self" && (
        <Field
          label="Instance URL"
          hint="The address you sign in at — no trailing path."
          value={host}
          onChange={setHost}
          placeholder="https://gitlab.company.com"
        />
      )}

      {save.error && (
        <p role="alert" className="text-xs text-destructive">
          {(save.error as Error).message}
        </p>
      )}

      <div className="flex items-center gap-3">
        <Button size="sm" disabled={!ready || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Continue"}
        </Button>
        {configured && (
          <button
            type="button"
            onClick={() => setEditing(false)}
            className="border-0 bg-transparent p-0 text-[12.5px] text-muted-foreground hover:text-foreground"
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}
