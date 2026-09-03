import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { api, type Project, type ProjectBudgetStatus, type ProjectCost } from "../../api/client";
import { deliveryApi } from "../../api/delivery";
import { CharterCard } from "../overview/CharterCard";
import { BudgetBar, ConsoleLabel } from "../overview/bits";
import { GitHubConnection } from "./github/GitHubConnection";
import { PublishProject } from "./PublishProject";
import { GitLabConnection } from "./gitlab/GitLabConnection";
import { SettingsSection } from "./SettingsSection";

const SUBSECTIONS = [
  { slug: "general", label: "General" },
  { slug: "charter", label: "Charter" },
  { slug: "integration", label: "Integration" },
  { slug: "danger", label: "Danger zone" },
];

/** Project-scoped settings, in the same sectioned enterprise layout as the global
 *  Settings: a left nav rail + a detail pane. General (monthly budget) · Integration
 *  (whichever forge this project is actually on) · Danger zone (delete).
 *
 *  The pane lives in `?pane=` rather than local state so it can be LINKED TO: the OAuth callback
 *  lands the operator straight on Integration, and the delivery CTAs point at the pane that fixes
 *  what they're complaining about. Before this it was `useState`, so every link opened General. */
export function ProjectSettingsWorkspace({ project }: { project: Project }) {
  const [params, setParams] = useSearchParams();
  const requested = params.get("pane") || "";
  const section = SUBSECTIONS.some((s) => s.slug === requested) ? requested : "general";
  const setSection = (slug: string) => {
    // `replace` so the rail doesn't stack history entries, and the existing keys (?oauth=…) ride
    // along untouched — the connect banner survives a pane switch.
    const next = new URLSearchParams(params);
    next.set("pane", slug);
    setParams(next, { replace: true });
  };
  return (
    <div className="flex w-full items-start gap-8">
      <nav
        aria-label="Project settings sections"
        className="sticky top-[72px] flex w-44 shrink-0 flex-col items-stretch gap-0.5 self-start"
      >
        <div className="mb-2 flex flex-col px-2">
          <h1 className="text-lg font-semibold tracking-tight">Settings</h1>
          <span className="truncate font-mono text-[11px] text-muted-foreground">
            {project.source_repo}
          </span>
        </div>
        {SUBSECTIONS.map((s) => (
          <button
            key={s.slug}
            onClick={() => setSection(s.slug)}
            className={cn(
              "rounded-md border-0 bg-transparent px-2 py-1.5 text-left text-sm transition-colors",
              section === s.slug
                ? "bg-primary/15 font-medium text-primary"
                : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
            )}
          >
            {s.label}
          </button>
        ))}
      </nav>

      <div className="min-w-0 flex-1">
        {section === "general" && (
          <div className="flex flex-col gap-6">
            <LimitsCard project={project} />
            <LifetimeUsageCard project={project} />
          </div>
        )}
        {section === "charter" && <CharterCard projectId={project.id} />}
        {section === "integration" && <IntegrationPane project={project} />}
        {section === "danger" && <DangerZoneCard project={project} />}
      </div>
    </div>
  );
}

/** The Integration pane, routed by the forge this project's source actually lives on.
 *
 *  Until now this pane rendered the GitLab card unconditionally, so a GitHub-backed project was
 *  shown GitLab token prose that could never apply to it — while the Delivery page one screen
 *  over already branched on the same capability record (ADR-0112). This closes that gap: the two
 *  surfaces now answer the provider question the same way, from the same source.
 *
 *  While the capability query is genuinely IN FLIGHT this renders nothing rather than a card —
 *  defaulting to GitLab here used to flash the GitLab card for every project, local ones
 *  included, for the one request's duration (F8/F9/F10). Once the query SETTLES — success or a
 *  failed request, e.g. an older server without the endpoint — it falls back to GitLab, the
 *  behaviour every project had before ADR-0112, so nothing regresses for the forge that was
 *  always assumed. */
function IntegrationPane({ project }: { project: Project }) {
  const { data: capability, isPending } = useQuery({
    queryKey: ["delivery-capability", project.id],
    queryFn: () => deliveryApi.projectDeliveryCapability(project.id),
  });
  if (isPending) return null;
  const provider = capability?.provider ?? "gitlab";

  if (provider === "github") return <GitHubConnection project={project} capability={capability} />;
  if (provider === "gitlab") return <GitLabConnection project={project} />;

  // An "unknown" provider means the source is not on a forge — usually a local path. Both
  // providers can create a repository and push this project into it now (ADR-0120/0125), so the
  // card offers whichever this instance can actually perform rather than favouring one.
  return <PublishProject project={project} />;
}

/** Monthly spend meter + caps. The window auto-resets on the 1st; the caps stop
 *  an autonomous sweep between items (per-run caps handle mid-run). */
function LimitsCard({ project }: { project: Project }) {
  const qc = useQueryClient();
  const { data: status } = useQuery<ProjectBudgetStatus>({
    queryKey: ["project-budget", project.id],
    queryFn: () => api.projectBudget(project.id),
  });
  const [usd, setUsd] = useState(project.budget_usd != null ? String(project.budget_usd) : "");
  const [tokens, setTokens] = useState(
    project.budget_tokens != null ? String(project.budget_tokens) : "",
  );
  const [saved, setSaved] = useState(false);

  const save = useMutation({
    mutationFn: () =>
      api.setProjectBudget(project.id, {
        budget_usd: usd.trim() ? Number(usd) : null,
        budget_tokens: tokens.trim() ? Math.round(Number(tokens)) : null,
      }),
    onSuccess: (resp) => {
      qc.setQueryData(["project", project.id], resp);
      qc.invalidateQueries({ queryKey: ["project-budget", project.id] });
      setSaved(true);
    },
  });

  const resets = status?.resets_at ? fmtDate(status.resets_at) : null;
  const hasCap = status && (status.budget_usd != null || status.budget_tokens != null);

  return (
    <SettingsSection
      title="Monthly budget"
      description={
        <p className="text-sm leading-relaxed text-muted-foreground">
          Caps this project's autonomous spend per calendar month
          {resets ? ` (resets ${resets})` : ""}. Leave a field blank for no cap. At 100% the
          autonomous sweep pauses between items.
        </p>
      }
    >
      {hasCap && status && (
        <div className="flex flex-col gap-2 rounded-md bg-muted/30 p-2.5">
          <ConsoleLabel>Spent this cycle</ConsoleLabel>
          {status.budget_tokens != null && (
            <BudgetBar label="Tokens" spent={status.spent_tokens} cap={status.budget_tokens} />
          )}
          {status.budget_usd != null && (
            <BudgetBar label="Spend ($)" spent={status.spent_usd} cap={status.budget_usd} />
          )}
        </div>
      )}

      <div className="grid grid-cols-[1fr_1fr] gap-3">
        <div className="flex flex-col gap-1">
          <ConsoleLabel>Tokens / month</ConsoleLabel>
          <Input
            aria-label="Monthly token budget"
            inputMode="numeric"
            placeholder="e.g. 1000000"
            className="font-mono text-xs"
            value={tokens}
            onChange={(e) => {
              setTokens(e.target.value);
              setSaved(false);
            }}
          />
        </div>
        <div className="flex flex-col gap-1">
          <ConsoleLabel>Spend / month ($)</ConsoleLabel>
          <Input
            aria-label="Monthly spend budget"
            inputMode="decimal"
            placeholder="e.g. 25"
            className="font-mono text-xs"
            value={usd}
            onChange={(e) => {
              setUsd(e.target.value);
              setSaved(false);
            }}
          />
        </div>
      </div>

      <p className="text-[11px] leading-relaxed text-muted-foreground/60">
        Local models are free — the $ cap applies only to paid/cloud models; the token cap applies
        to every run.
      </p>

      <div className="flex items-center gap-2">
        <Button size="sm" variant="secondary" disabled={save.isPending} onClick={() => save.mutate()}>
          Save budget
        </Button>
        {saved && <span className="text-xs text-success">Budget saved.</span>}
      </div>
      {save.isError && (
        <p role="alert" className="text-xs text-destructive">
          {save.error instanceof Error ? save.error.message : String(save.error)}
        </p>
      )}
    </SettingsSection>
  );
}

function fmtDate(iso: string): string | null {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d.toLocaleDateString();
}

function DangerZoneCard({ project }: { project: Project }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [confirmText, setConfirmText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const armed = confirmText.trim() === project.id;

  async function deleteProject() {
    setErr(null);
    setBusy(true);
    try {
      await api.deleteProject(project.id);
      qc.invalidateQueries({ queryKey: ["projects"] });
      navigate("/");
    } catch (e) {
      // 409 while a run is active lands here — surfaced inline, never alert().
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <SettingsSection
      tone="danger"
      title="Danger zone"
      description={
        <p className="text-sm leading-relaxed text-muted-foreground">
          Deleting this project removes its record, backlog, and PM conversation from the
          database, and deletes the local clone. Past runs are kept in history but unlinked
          from the project. Deletion is blocked while a run is active.
        </p>
      }
    >
      <div className="flex flex-col gap-2">
        <ConsoleLabel>
          Type <span className="text-foreground">{project.id}</span> to confirm
        </ConsoleLabel>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            aria-label="Confirm project id"
            placeholder={project.id}
            className="w-72 font-mono text-xs"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
          />
          <Button
            size="sm"
            variant="destructive"
            disabled={!armed || busy}
            onClick={() => void deleteProject()}
          >
            Delete project
          </Button>
        </div>
      </div>
      {err && (
        <p role="alert" className="text-xs text-destructive">
          {err}
        </p>
      )}
    </SettingsSection>
  );
}

const usdFmt = (n: number) => `$${n.toFixed(2)}`;

/** Lifetime usage (moved from the overview Budgets card, 2026-08-22 redundancy audit): the
 *  all-time `/cost` accounting — spend, tokens, model calls, avg per metered run, and the
 *  metered-runs honesty note. This is the product's one render of the lifetime figures. */
function LifetimeUsageCard({ project }: { project: Project }) {
  const { data: cost } = useQuery<ProjectCost>({
    queryKey: ["project-cost", project.id],
    queryFn: () => api.projectCost(project.id),
  });
  // Local models are unpriced: an all-$0 column is noise, so dollars only render once any exist.
  const dollarsMatter = Boolean(cost && cost.usd > 0);
  const avgPerRun = cost && cost.runs_metered > 0 ? cost.usd / cost.runs_metered : null;
  return (
    <SettingsSection
      title="Lifetime usage"
      description={
        <p className="text-sm leading-relaxed text-muted-foreground">
          All-time metered usage across this project's runs.
        </p>
      }
    >
      {cost ? (
        <dl className="grid max-w-xs grid-cols-2 gap-x-3 gap-y-1 font-mono text-[12.5px]">
          {dollarsMatter && (
            <>
              <dt className="text-muted-foreground">Spend</dt>
              <dd className="text-right tabular-nums">{usdFmt(cost.usd)}</dd>
            </>
          )}
          <dt className="text-muted-foreground">Tokens</dt>
          <dd className="text-right tabular-nums">{cost.total_tokens.toLocaleString()}</dd>
          <dt className="text-muted-foreground">Model calls</dt>
          <dd className="text-right tabular-nums">{cost.calls.toLocaleString()}</dd>
          {dollarsMatter && avgPerRun != null && (
            <>
              <dt className="text-muted-foreground">Avg / run</dt>
              <dd className="text-right tabular-nums">{usdFmt(avgPerRun)}</dd>
            </>
          )}
        </dl>
      ) : (
        <p className="font-mono text-[13px] text-muted-foreground">—</p>
      )}
      {cost && cost.runs_total > cost.runs_metered && (
        <p className="font-mono text-[11px] text-muted-foreground/60">
          {cost.runs_metered}/{cost.runs_total} runs metered — unmetered runs cost nothing on
          record, which is not the same as free.
        </p>
      )}
    </SettingsSection>
  );
}
