import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { api } from "../api/client";
import { ConsoleLabel } from "../components/overview/bits";

const CARD = "flex flex-col gap-4 rounded-lg bg-card p-5 ring-1 ring-white/12";

export function NewProjectPage() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [sourceRepo, setSourceRepo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      // No credential here on purpose: GitLab is connected from the project's own Integration
      // pane, in one place, after creation. The API still accepts a seeded token (unchanged) —
      // this form simply stopped being a fourth place to paste one.
      const project = await api.createProject({
        name: name.trim(),
        source_repo: sourceRepo.trim(),
      });
      navigate(`/projects/${project.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold tracking-tight">New project</h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          Name it and point it at the source repository. Quincy clones the repo, then you'll shape
          the project together in a short intake chat — when you're ready, one click builds the
          backlog and the full workspace opens.
        </p>
      </div>

      <form className={CARD} onSubmit={submit}>
        <div className="flex flex-col gap-1.5">
          <ConsoleLabel>Project name</ConsoleLabel>
          <Input
            aria-label="Project name"
            placeholder="e.g. Mosaera — RAG memory recall"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>

        {/* Optional (ADR-0123). A project starts as its own repository on this server; pointing
            it at an existing one is the IMPORT path, not the only way in. Leaving this required
            is what made "create a project, then publish it" impossible. */}
        <div className="flex flex-col gap-1.5">
          <ConsoleLabel>Import an existing repository — optional</ConsoleLabel>
          <Input
            aria-label="Source repository"
            placeholder="https://gitlab.example.com/group/repo.git"
            value={sourceRepo}
            onChange={(e) => setSourceRepo(e.target.value)}
          />
        </div>

        <p className="text-[11.5px] leading-relaxed text-muted-foreground">
          {sourceRepo.trim() ? (
            <>
              The repository is cloned onto this server and worked on there; merge requests still
              go back to it. A private one needs GitLab connected first — one step from the
              project&rsquo;s <b className="text-foreground">Settings → Integration</b> once it
              exists. A public source needs nothing.
            </>
          ) : (
            <>
              Leave this empty and the project starts as a fresh repository on this server. You can
              publish it to GitHub later from{" "}
              <b className="text-foreground">Settings → Integration</b> — until you do, its code
              lives only here.
            </>
          )}
        </p>

        {error && (
          <p role="alert" className="text-xs text-destructive">
            {error}
          </p>
        )}

        <div className="flex justify-end">
          <Button type="submit" disabled={busy || !name.trim()}>
            {busy ? "Creating…" : "Create project"}
          </Button>
        </div>
      </form>
    </div>
  );
}
