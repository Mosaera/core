import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { api, type CheckRow, type GitlabProject, type GitlabStatus } from "../../../api/client";
import { SeverityDot } from "../../overview/bits";
import { TONE_BADGE } from "../../StatusBadge";
import { Field } from "./SetupWizard";

const RECOMMENDED = ["api", "write_repository"];

function Check({ ok, label, detail }: CheckRow) {
  return (
    <div className="flex items-start gap-2">
      <SeverityDot severity={ok ? "green" : "red"} className="mt-1.5" />
      <div className="min-w-0">
        <span className="text-sm text-foreground/90">{label}</span>
        <span className="block font-mono text-[11px] text-muted-foreground">{detail}</span>
      </div>
    </div>
  );
}

/** The OPTIONAL instance-wide token: it browses groups and projects, and powers legacy one-off
 *  runs. Projects never spend it — each holds its own scoped credential from the OAuth connect.
 *
 *  Carried over from the old GitLab card with its substance intact (identity, scopes, visible
 *  projects, the per-project secure-dev checklist). What changed is its framing: it used to LEAD
 *  the page with a paragraph teaching the internal distinction between a global token and a
 *  project token, before anything said what the page was for. For most operators the correct
 *  action here is to skip it, so it is the optional last step now and says so plainly. */
export function GitLabDiscovery({ status }: { status?: GitlabStatus }) {
  const qc = useQueryClient();
  const [token, setToken] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [project, setProject] = useState("");

  const live = Boolean(status?.configured && status?.ok);
  const { data: vis } = useQuery({
    queryKey: ["gitlab-visibility"],
    queryFn: () => api.gitlabVisibility(),
    enabled: live,
  });
  const { data: checklist } = useQuery({
    queryKey: ["gitlab-checklist", project],
    queryFn: () => api.gitlabChecklist(project),
    enabled: !!project,
  });

  async function save() {
    setSaving(true);
    setMsg(null);
    try {
      const s = await api.saveGitlab({ token: token.trim() });
      setToken("");
      qc.setQueryData(["gitlab-status"], s);
      void qc.invalidateQueries({ queryKey: ["gitlab-visibility"] });
      setMsg(s.ok ? "Connected." : s.error ? `Couldn't verify that token: ${s.error}` : "Saved.");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col items-stretch gap-3">
      <p className="text-[12.5px] leading-relaxed text-muted-foreground">
        Only needed if you want to browse your groups and projects when creating one. Projects
        deliver with their own credential either way, so skipping this is the more zero-trust
        choice — and the one most people should make.
      </p>

      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[18rem] flex-1">
          <Field
            label={`Read token${status?.token_masked ? ` (saved: ${status.token_masked})` : ""}`}
            type="password"
            value={token}
            onChange={setToken}
            placeholder="glpat-… (scopes: api, write_repository)"
            mono
          />
        </div>
        <Button size="sm" disabled={saving || !token.trim()} onClick={() => void save()}>
          {saving ? "Saving…" : "Save & test"}
        </Button>
      </div>
      {msg && <p className="font-mono text-xs text-muted-foreground">{msg}</p>}

      {live && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="font-mono text-[11px] uppercase tracking-wide text-muted-foreground">
            user
          </dt>
          <dd>
            {status?.user?.name} (@{status?.user?.username})
            {status?.user?.is_admin ? " · admin" : ""}
          </dd>
          <dt className="font-mono text-[11px] uppercase tracking-wide text-muted-foreground">
            expires
          </dt>
          <dd>{status?.expires_at || "never (set an expiry)"}</dd>
          <dt className="font-mono text-[11px] uppercase tracking-wide text-muted-foreground">
            scopes
          </dt>
          <dd className="flex flex-wrap gap-2 font-mono text-xs">
            {RECOMMENDED.map((s) => {
              const has = (status?.scopes ?? []).includes(s);
              return (
                <span key={s} className={has ? "text-success" : "text-destructive"}>
                  {has ? "✓" : "✗"} {s}
                </span>
              );
            })}
          </dd>
        </dl>
      )}

      {vis && vis.projects.length > 0 && (
        <>
          <div className="flex items-center justify-between gap-2 pt-1">
            <h4 className="text-sm font-medium text-foreground">Visible projects</h4>
            <span className="font-mono text-[11px] text-muted-foreground/70">
              {vis.projects.length} projects · {vis.groups.length} groups
            </span>
          </div>
          <ul className="flex flex-col items-stretch gap-1">
            {vis.projects.map((p: GitlabProject) => (
              <li key={p.path}>
                <button
                  onClick={() => setProject(p.path)}
                  className="flex w-full items-center gap-2 rounded-md border-0 bg-transparent px-2 py-1.5 text-left transition-colors hover:bg-muted/30"
                >
                  <span className="min-w-0 flex-1 truncate font-mono text-[13px] text-foreground/90">
                    {p.path}
                  </span>
                  <Badge
                    className={cn(
                      "font-mono text-[10px] uppercase",
                      p.can_push ? TONE_BADGE.success : TONE_BADGE.neutral,
                    )}
                  >
                    {p.can_push ? "can push" : "read-only"}
                  </Badge>
                  <span className="font-mono text-[11px] text-primary">check ▸</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      {project && (
        <>
          <div className="flex items-center justify-between gap-2 pt-1">
            <h4 className="text-sm font-medium text-foreground">Secure-dev checklist</h4>
            <span className="font-mono text-xs text-muted-foreground">{project}</span>
          </div>
          <div className="flex flex-col gap-2">
            {(checklist?.checks ?? []).map((c, i) => (
              <Check key={i} {...c} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
