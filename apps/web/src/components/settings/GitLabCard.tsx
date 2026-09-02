import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { api, type CheckRow, type GitlabProject, type GitlabStatus } from "../../api/client";
import { ConsoleLabel, EmptyNote, SeverityDot } from "../overview/bits";
import { GitLabDialog } from "./gitlab/GitLabDialog";
import { SettingsSection } from "./SettingsSection";
import { TONE_BADGE } from "../StatusBadge";

const RECOMMENDED_SCOPES = ["api", "write_repository"];

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

/** The instance-wide OAuth application, in READ-ONLY summary. It is configured from the same
 *  dialog a project uses (settings/gitlab/GitLabDialog) — one surface, one set of instructions,
 *  reachable from either place. This entry point exists so an admin with no projects yet still
 *  has a way in; the flow itself belongs on the project. */
function OAuthAppSummary({ status }: { status?: GitlabStatus }) {
  const [open, setOpen] = useState(false);
  const configured = Boolean(status?.oauth_configured);
  const host = status?.url ? new URL(status.url).host : undefined;
  return (
    <div className="flex flex-col items-stretch gap-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">OAuth application</h3>
        <Badge
          className={cn(
            "font-mono text-[10px] uppercase",
            configured ? TONE_BADGE.success : TONE_BADGE.neutral,
          )}
        >
          {configured ? "configured" : "not configured"}
        </Badge>
      </div>
      <p className="text-[12.5px] leading-relaxed text-muted-foreground">
        Registered once for this instance; it is what lets each project connect by authorizing
        instead of pasting a token. Set it up from any project&rsquo;s{" "}
        <b className="text-foreground">Settings → Integration</b>, or here.
        {status?.oauth_client_id_masked ? (
          <>
            {" "}
            Application ID{" "}
            <span className="font-mono text-foreground/90">{status.oauth_client_id_masked}</span>.
          </>
        ) : null}
      </p>
      <Button size="sm" variant="outline" className="w-fit" onClick={() => setOpen(true)}>
        {configured ? "Change OAuth app" : "Set up OAuth app"}
      </Button>
      <GitLabDialog open={open} onOpenChange={setOpen} status={status} host={host} />
    </div>
  );
}

/** The GitLab integration: an OPTIONAL global token that powers the discovery view and
 *  legacy one-off runs (projects use their own scoped tokens). Connection + identity +
 *  visible projects + a per-project secure-dev checklist. */
export function GitLabCard() {
  const qc = useQueryClient();
  const { data: status } = useQuery({ queryKey: ["gitlab-status"], queryFn: () => api.gitlabStatus() });
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [project, setProject] = useState("");

  useEffect(() => {
    if (status?.url && !url) setUrl(status.url);
  }, [status, url]);

  const configured = status?.configured;
  const { data: vis } = useQuery({
    queryKey: ["gitlab-visibility"],
    queryFn: () => api.gitlabVisibility(),
    enabled: !!configured && !!status?.ok,
  });
  const { data: checklist } = useQuery({
    queryKey: ["gitlab-checklist", project],
    queryFn: () => api.gitlabChecklist(project),
    enabled: !!project,
  });

  useEffect(() => {
    if (!project && vis?.projects?.length) {
      const pushable = vis.projects.find((p) => p.can_push) ?? vis.projects[0];
      setProject(pushable.path);
    }
  }, [vis, project]);

  async function save() {
    setSaving(true);
    setMsg(null);
    try {
      const body: { url?: string; token?: string } = { url: url.trim() };
      if (token.trim()) body.token = token.trim();
      const s = await api.saveGitlab(body);
      setToken("");
      qc.setQueryData(["gitlab-status"], s);
      qc.invalidateQueries({ queryKey: ["gitlab-visibility"] });
      setMsg(
        s.ok
          ? "Connected."
          : s.error
            ? `Couldn't verify this token (${s.error}). That's fine — this global token is ` +
              `optional; your projects use their own scoped tokens. Leave it blank if you like.`
            : "Saved.",
      );
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  const connTone = configured
    ? status?.ok
      ? TONE_BADGE.success
      : TONE_BADGE.amber
    : TONE_BADGE.neutral;
  const connLabel = configured ? (status?.ok ? "connected" : "configured") : "not configured";

  return (
    <SettingsSection
      title="GitLab"
      description={
        <p className="text-sm leading-relaxed text-muted-foreground">
          <b className="text-foreground">Optional.</b> This global token powers only the discovery
          view (browse your groups/projects) and legacy one-off runs.{" "}
          <b className="text-foreground">Projects use their own scoped token</b> (set per project,{" "}
          <span className="font-mono text-xs">write_repository</span> only) — so leaving this blank
          is fine and more zero-trust. Stored server-side, never shown again.
        </p>
      }
    >
      <div className="flex flex-col items-stretch gap-3">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-foreground">Connection</h3>
          <Badge className={cn("font-mono text-[10px] uppercase", connTone)}>{connLabel}</Badge>
        </div>
        <div className="flex flex-col gap-1">
          <ConsoleLabel>GitLab URL</ConsoleLabel>
          <Input
            aria-label="GitLab URL"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://gitlab.example.com"
            className="text-sm"
          />
        </div>
        <div className="flex flex-col gap-1">
          <ConsoleLabel>Token {status?.token_masked ? `(saved: ${status.token_masked})` : ""}</ConsoleLabel>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              type="password"
              aria-label="GitLab token"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder={configured ? "leave blank to keep the saved token" : "glpat-… (scopes: api, write_repository)"}
              className="w-72 font-mono text-xs"
            />
            <Button size="sm" onClick={() => void save()} disabled={saving}>
              {saving ? "Saving…" : "Save & test"}
            </Button>
          </div>
        </div>
        {msg && <p className="font-mono text-xs text-muted-foreground">{msg}</p>}
        <p className="font-mono text-[11px] leading-relaxed text-muted-foreground/70">
          The token is write-only (never returned) and stored at .mosaera/settings.json (0600).
        </p>
      </div>

      <OAuthAppSummary status={status} />

      {configured && status?.ok && (
        <div className="flex flex-col items-stretch gap-3">
          <h3 className="text-sm font-semibold text-foreground">Identity &amp; token</h3>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="font-mono text-[11px] uppercase tracking-wide text-muted-foreground">user</dt>
            <dd>
              {status.user?.name} (@{status.user?.username}){status.user?.is_admin ? " · admin" : ""}
            </dd>
            <dt className="font-mono text-[11px] uppercase tracking-wide text-muted-foreground">scopes</dt>
            <dd>{(status.scopes ?? []).join(", ") || "—"}</dd>
            <dt className="font-mono text-[11px] uppercase tracking-wide text-muted-foreground">expires</dt>
            <dd>{status.expires_at || "never (set an expiry)"}</dd>
            <dt className="font-mono text-[11px] uppercase tracking-wide text-muted-foreground">recommended</dt>
            <dd className="flex flex-wrap gap-2 font-mono text-xs">
              {RECOMMENDED_SCOPES.map((s) => {
                const has = (status.scopes ?? []).includes(s);
                return (
                  <span key={s} className={has ? "text-success" : "text-destructive"}>
                    {has ? "✓" : "✗"} {s}
                  </span>
                );
              })}
            </dd>
          </dl>
        </div>
      )}

      {vis && (
        <div className="flex flex-col items-stretch gap-3">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-foreground">Visible projects</h3>
            <span className="font-mono text-[11px] text-muted-foreground/70">
              {vis.projects.length} projects · {vis.groups.length} groups
            </span>
          </div>
          {vis.projects.length === 0 ? (
            <EmptyNote>No projects visible to this token.</EmptyNote>
          ) : (
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
          )}
        </div>
      )}

      {project && (
        <div className="flex flex-col items-stretch gap-3">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-foreground">Secure-dev checklist</h3>
            <span className="font-mono text-xs text-muted-foreground">{project}</span>
          </div>
          <div className="flex flex-col gap-2">
            {(checklist?.checks ?? []).map((c, i) => (
              <Check key={i} {...c} />
            ))}
          </div>
        </div>
      )}
    </SettingsSection>
  );
}
