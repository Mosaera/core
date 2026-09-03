// Typed client for the Mosaera API (same-origin: dev via Vite proxy, prod via
// FastAPI static serving).

import { adminFetch } from "./adminAuth";
import { apiFetch, withToken, type AuthUser } from "./auth";
import type { PriceEntry, Pricing } from "./cost";
import type { RunControls } from "./runProvenance";
import type { GeneralSettings } from "./settings";
import { deliveryApi } from "./delivery";
import type { RunDiagnosis } from "./diagnosis";
import { projectSetupApi } from "./projectSetup";

export type { RunDiagnosis } from "./diagnosis";
export type { RunControls } from "./runProvenance";
export type { GeneralSettings, ProfileCatalogue, ProfileEffect } from "./settings";
export type { ProjectSetup, SetupPatch } from "./projectSetup";
import { proofApi } from "./proof";

export interface RunSubmit {
  repo: string;
  task: string;
  max_iterations?: number | null;
  scan: boolean;
  sandbox?: string | null;
  test_cmd?: string | null;
}

export type AttachmentScope = "message_only" | "project_context";

/** An attachment that rode on a chat message (shown as a file card above it). */
export interface MessageAttachmentRef {
  id: string;
  filename: string;
  scope: AttachmentScope;
  size_bytes: number;
  mime_type?: string;
}

/** One context source a PM reply used (recorded from builder metadata). */
export interface MessageContextSource {
  source_type: string; // brief | backlog | runs | attachment
  source_id: string;
  title: string;
  included_as: string; // included_raw | truncated | chunks | summary | reference_only
  token_count: number;
}

/** A proposal stored beside its turn so the card survives a reload (0031); only OPEN ones return. */
export interface StoredProposal {
  id: number;
  kind: "changeset" | "charter";
  payload: unknown;
}

export interface ProjectMessage {
  id?: number; // row id, so a card can anchor to the turn that produced it
  role: string; // user | pm | note (note = engine row; content is the cause token)
  content: string;
  created_at: string | null;
  attachments?: MessageAttachmentRef[];
  context_sources?: MessageContextSource[];
  steps?: { kind: string; tool: string; arg: string; duration_ms?: number }[]; // what it looked up
  proposals?: StoredProposal[];
}

/** A project upload. Storage is server-side; this is metadata only. */
export interface Attachment {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  status: string; // processing | ready | failed
  error_message: string;
  token_estimate: number;
  scope: AttachmentScope;
  created_at: string | null;
  /** raw content exceeds the per-message budget — summary/excerpts will be used */
  large: boolean;
  /** 1-3 sentence summary generated at upload (empty until processing lands) */
  summary: string;
}

export interface BacklogItem {
  id: number;
  project_id: string;
  title: string;
  description: string;
  acceptance: string;
  status: string;
  position: number;
  iteration: string | null;
  created_at: string | null;
  /** Item ids this one depends on (can't start until each is delivered). */
  depends_on?: number[];
  /** Derived: dependency ids not yet delivered — the item is blocked while non-empty. */
  blocked_by?: number[];
  /** Soft lock (Quincy/operator hold): a normal run 409s while set; can be
   *  overridden. Distinct from the derived, non-overridable `blocked_by`. */
  locked?: boolean;
  /** Why the item is locked — shown as a caveat before an override run. */
  lock_reason?: string;
  /** Per-item stacked-MR delivery (ADR-0021/0102): the item's branch, its MR URL
   *  (empty until it delivers), and the MR's last-polled state (""|opened|merged|closed). */
  branch?: string;
  mr_url?: string;
  mr_state?: string;
  mr_target?: string; // the branch the MR actually targets (0028) — recorded, never recomputed
  /** Checkability verdict (ADR-0079/0080): CHECKABLE | PARTIALLY_CHECKABLE | UNDER_SPECIFIED.
   *  Only present on `todo` items — settled work isn't re-judged. */
  checkability?: string | null;
  /** Decidability verdict: DECIDABLE | UNDECIDABLE. The orthogonal axis — checkability asks
   *  whether a check can BIND, this asks whether the text fixes ONE answer. An item can be
   *  CHECKABLE and UNDECIDABLE, which is the shape that ships green over an invented answer.
   *  Only present on `todo` items — settled work isn't re-judged. */
  decidability?: string | null;
  /** Reachability verdict: REACHABLE | UNREACHABLE (F76, #78) — can the engine's toolset actually
   *  perform the work this acceptance demands? Served since the axis shipped; rendered since #121,
   *  because until then it surfaced only as a launch-time 409. */
  reachability?: string | null;
  /** Would this item's acceptance text pass today's intake bar? Unlike the two verdicts above
   *  this is computed for EVERY status, so work authored before those checks existed is
   *  visible. For settled work a `false` says the acceptance could not have gated it — NOT
   *  that the delivered code is wrong. */
  compliant?: boolean | null;
  /** Why `compliant` is false, one entry per failing axis; empty when it is true. */
  compliance_reasons?: string[];
  /** Structured acceptance claims derived from the acceptance text (serialized Claim rows). */
  claims?: BacklogClaim[];
  /** Quincy's OPEN intake question (ADR-0080 §1) — present only while unresolved; the
   *  item is not runnable until the operator resolves or dismisses it. */
  clarification?: ItemClarification | null;
  /** The full retained ask→answer exchange regardless of status (#63 ledger);
   *  null only when nothing was ever asked. */
  clarification_record?: ItemClarification | null;
}

/** One derived acceptance claim (ADR-0079 Wave 1 schema, serialized). */
export interface BacklogClaim {
  id: string;
  item_id: number | null;
  text: string;
  provenance: string;
  oracle_kind: string;
  material: boolean;
}

/** One operation in a curator changeset (proposed, never auto-applied). Each op
 *  carries a `why` so the review panel can explain the change before approval. */
export type ChangesetOp =
  | {
      op: "add";
      title: string;
      description?: string;
      acceptance?: string;
      why: string;
    }
  | { op: "reorder"; ordered_ids: number[]; why: string }
  | {
      op: "enhance";
      id: number;
      title?: string;
      description?: string;
      acceptance?: string;
      why: string;
    }
  | { op: "lock"; id: number; reason: string }
  | { op: "unlock"; id: number; why?: string }
  | { op: "set_dependencies"; id: number; depends_on: number[]; why: string }
  | {
      op: "split";
      id: number;
      parts: { title: string; description?: string; acceptance?: string }[];
      why: string;
    }
  | {
      op: "merge";
      target: number;
      sources: number[];
      title?: string;
      description?: string;
      acceptance?: string;
      why: string;
    }
  | { op: "delete"; id: number; why?: string };

/** The three autonomy tiers (#42/ADR-0047 §1) — an ENUM, never free text; the UI renders a
 *  <Select>. Free ⊇ Business ⊇ Regulated; enforcement (posture_allows) is the ADR-0046 arc. */
export type CharterPosture = "free" | "business" | "regulated";

/** A charter Quincy PROPOSED in chat. The operator confirms this STRUCTURED value (red-team:
 *  the parsed posture is the truth, the chat prose is decoration). */
export interface CharterProposal {
  goal: string;
  constraints: string;
  posture: CharterPosture;
}

/** The TRUSTED, operator-authored project charter — the intake chat only ever PROPOSES it. */
export type Charter = CharterProposal & {
  project_id: string;
  created_at: string | null;
  updated_at: string | null;
};

/** The charter PUT body: posture OMITTED means "leave it as it is" — how a member saves intent
 *  without touching governance (ADR-0047 amendment 2026-08-18). */
export type CharterWrite = Omit<CharterProposal, "posture"> & { posture?: CharterPosture };

/** Advisory per-observation triage hint (recon-assigned, never from repo content); orders and
 *  colours the map. `info` is the neutral floor. */
export type MapSeverity = "info" | "low" | "medium" | "high" | "critical";

const SEVERITY_ORDER: MapSeverity[] = ["info", "low", "medium", "high", "critical"];

/** The ordinal of a severity (unknown → 0 = info, deny-by-default) — for max-severity ranking. */
export function severityRank(severity: string | undefined): number {
  const i = SEVERITY_ORDER.indexOf((severity ?? "info") as MapSeverity);
  return i < 0 ? 0 : i;
}

/** One UNTRUSTED recon observation about a map dimension (provenance-attributed data). */
export interface MapObservation {
  provenance: string;
  text: string;
  severity?: MapSeverity;
}

/** One dimension of the durable project map — tri-state, provenanced, with freshness. */
export interface MapDimension {
  dimension: string;
  status: "finding" | "clean" | "unavailable";
  fingerprint?: string | null;
  unavailable_reason?: string;
  computed_at: string | null;
  observations: MapObservation[];
}

/** GET /map: the map dimensions + the server-derived stale list (missing/unknown-fingerprint,
 *  full-set, deny-by-default) + the transient recon overlay. */
export interface ProjectMap {
  dimensions: MapDimension[];
  stale: string[];
  running?: boolean;
  error?: string;
}

export interface Project {
  id: string;
  name: string;
  source_repo: string;
  goal: string;
  brief: string;
  status: string;
  branch: string;
  mr_url: string;
  autonomous: boolean;
  has_gitlab_token: boolean;
  gitlab_token_masked: string;
  /** Whether the optional api-scoped token is set (ADR-0103) — presence only, never a value. */
  has_gitlab_api_token?: boolean;
  error: string;
  /** Per-project monthly spend ceilings; null = no cap (absent on older servers). */
  budget_usd?: number | null;
  budget_tokens?: number | null;
  created_at: string | null;
  backlog?: BacklogItem[];
  runs?: HistoryRun[];
}

/** Monthly budget snapshot for a project: caps, spend this calendar cycle, and
 *  warn (≥80%) / over (≥100%) flags. Powers the Settings spend meter. */
export interface ProjectBudgetStatus {
  budget_usd: number | null;
  budget_tokens: number | null;
  spent_usd: number;
  spent_tokens: number;
  cycle_start: string;
  resets_at: string;
  pct: number;
  warn: boolean;
  over: boolean;
  reason: string;
}

// The gate contract lives in ./gate — imported for local use AND re-exported, so every
// existing `import { GatePayload } from "../api/client"` keeps working.
import type { ClarificationResolveBody, ItemClarification } from "./clarification";
import type { GatePayload, RunClaimRow } from "./gate";
export type { ClarificationResolveBody, ItemClarification } from "./clarification";

export type {
  ClaimDisposition,
  GateDecision,
  GateOutcome,
  GatePayload,
  OutcomeVerdict,
  RunClaimRow,
} from "./gate";

export type RunMode = "guided" | "autonomous" | "high_assurance";

/** One row of a cost breakdown — tokens and $ are separate figures (a free
 *  local model has real tokens but $0). Keyed by agent or by model. */
import type { CostBreakdownRow, RunCost } from "./cost";

export type { CostBreakdownRow, RunCost } from "./cost";

/** Aggregated token/$ spend across a project's runs (durable rollups). */
export interface ProjectCost {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  usd: number;
  /** Imputed on-box spend, kept apart from `usd` exactly as in RunCost. */
  shadow_usd?: number;
  calls: number;
  runs_metered: number;
  runs_total: number;
  by_agent: CostBreakdownRow[];
  by_model: CostBreakdownRow[];
}

/** Deterministic-first discipline metrics (#22). Ratios are null until there's
 *  metered/delivered run history to compute them from (honest empty state). */
export interface ProjectMetrics {
  runs_metered: number;
  delivered_items: number;
  total_calls: number;
  total_det_ops: number;
  delivered_calls: number;
  calls_per_delivered_item: number | null;
  det_llm_ratio: number | null;
  /** p50/p95 of the synchronous PM-chat model call (#22, metric 3); null until
   *  samples exist. latency_samples counts them (can be > 0 with zero runs). */
  latency_samples: number;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  by_agent: { agent: string; calls: number }[];
}

export interface RunSnapshot {
  /** ADR-0101 live interaction mode: "ask" | "accept" | "auto". */
  interaction_mode?: string;
  run_id: string;
  status: string;
  phase?: string;
  /** Per-run approval posture (guided | autonomous | high_assurance). */
  mode?: RunMode;
  started_at?: number | null;
  pending_interrupt: { id: string; value: GatePayload } | null;
  approved: boolean | null;
  report_path: string | null;
  commit_sha: string | null;
  /** Why a run ended without delivering (status "incomplete"); null otherwise. */
  termination_reason?: string | null;
  /** The structured record behind that reason (#75). Null until the run is terminal. */
  diagnosis?: RunDiagnosis | null;
  /** Live token/cost rollup for this run (absent on older servers). */
  cost?: RunCost;
  /** Per-run spend ceilings {usd|tokens|tool_calls: cap}; null when no budget set. */
  budget?: Record<string, number> | null;
  /** The control set the run STARTED with — captured once, never re-read, so a knob flipped
   *  later cannot retroactively re-describe a finished run. Absent on older servers/rows: the
   *  roster then falls back to inferring from observed events. */
  controls?: RunControls | null;
  /** Intent profiles the run STARTED with (ADR-0122) — so it reads as an observation about THIS
   *  run, not the promise a label makes. Unset omitted; absent on older rows. */
  profiles?: Record<string, string> | null;
}


export interface ActiveRun {
  run_id: string;
  status: string;
  task: string;
  phase?: string;
  started_at?: number | null;
  project_id?: string | null;
  item_id?: number | null;
}

export interface HistoryRun {
  id: string;
  task: string;
  status: string;
  /** TRI-STATE: null = the run never reached a test phase (cancelled early, intake refused,
   *  errored). It was declared `boolean` here while the API returned null, which made
   *  `tests_passed ? "pass" : "fail"` look safe and rendered every testless run as a red
   *  "TESTS FAIL" — see run 20260806-205850-033b61, refused at intake having spent 0 tokens.
   *  Never branch on this directly; derive labels from `runOutcome` (lib/validation.ts). */
  tests_passed: boolean | null;
  iterations: number;
  commit_sha: string;
  source: string;
  branch: string;
  project_id: string | null;
  item_id: number | null;
  /** Honest tri-state: "pass" | "failed" | "unavailable"; null/absent = pre-planner row. */
  validation_status?: string | null;
  /** Why a run ended without delivering (status "INCOMPLETE"); null otherwise. */
  termination_reason?: string | null;
  created_at: string | null;
  /** The seal (#63, migration 0020). Null = pre-0020 row / never finalized / no receipt —
   *  render null honestly; NEVER proxy the live engine version for a null stamp. */
  finished_at?: string | null;
  engine_version?: string | null;
  receipt_id?: string | null;
  /** How the run ended, structured (#75, migration 0022). Null = pre-0022 row / in flight. */
  diagnosis?: RunDiagnosis | null;
}

export interface RunDetail extends HistoryRun {
  decisions: { kind: string; content: string; created_at: string | null }[];
  test_results: { passed: boolean; output: string; created_at: string | null }[];
  repo_changes: { diff: string; commit_sha: string; created_at: string | null }[];
  approvals: { action: string; approved: boolean; feedback: string; created_at: string | null }[];
  /** Durable token/cost rollup for this run (null on pre-accounting rows). */
  cost?: RunCost | null;
  /** The durable claim ledger (run_claims, ADR-0079); absent on older servers. */
  claims?: RunClaimRow[];
}

/** One row of a project's persisted audit trail (an `audit_events` record,
 *  joined to its run's task). */
export interface ActivityEvent {
  run_id: string;
  event: string;
  detail: string;
  created_at: string | null;
  task: string;
}

export async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${detail ? `: ${detail}` : ""}`);
  }
  return res.json() as Promise<T>;
}

export type KnobValue = number | string | boolean | null;

/** One operational setting: its effective value + where it came from. `source: "env"`
 *  means an env var pins it (read-only in the UI); "stored" = set in the UI; "default". */
export interface KnobView {
  value: KnobValue;
  source: "env" | "stored" | "profile" | "default";
  clamped_by?: string | null; // a knob that overrides this one on SOME runs; still editable
  kind: string; // int | float | opt_int | opt_float | bool | str | opt_str
  env: string; // the env var that overrides it
  choices?: string[] | null; // supported values → the UI renders a dropdown
  // ADR-0122. `derived_from` names the intent profile that owns this knob, and is reported even
  // when env or a stored value OUTRANKS the profile — that is exactly when an operator needs to
  // see their profile is not in effect here. `source` says which layer won; this says which
  // profile is in play. Independent of `clamped_by`, a run-time override rather than a layer.
  derived_from?: string | null;
  visibility?: "core" | "developer" | "internal";
  /** What this knob DOES, in a sentence. A summary listing knob IDENTIFIERS predicts nothing
   *  for the reader, which is what made the profiles read as theatre (ADR-0122 §5). */
  effect?: string | null;
}


/** One durable run event (a `run_events` row). `ts` is a SERVER epoch-ms stamp — the
 *  only honest per-step clock (decision created_at values cluster at persist time). */
export interface TranscriptEvent {
  seq: number;
  type: "activity" | "thought" | "update" | "interrupt" | "escalation";
  node: string | null;
  ts: number;
  data: Record<string, unknown> | null;
}

export interface RunTranscriptResponse {
  run_id: string;
  status: string | null;
  termination_reason: string | null;
  task: string;
  events: TranscriptEvent[];
}

export const api = {
  submitRun: (body: RunSubmit) =>
    apiFetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<RunSnapshot>),

  activeRuns: () => apiFetch("/api/runs").then(json<{ runs: ActiveRun[] }>),

  getRun: (id: string) => apiFetch(`/api/runs/${id}`).then(json<RunSnapshot>),

  approve: (
    id: string,
    approve: boolean,
    feedback = "",
    authorizeTests: string[] = [],
    optionId?: string,
  ) =>
    apiFetch(`/api/runs/${id}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        approve,
        feedback,
        authorize_tests: authorizeTests,
        option_id: optionId ?? null,
      }),
    }).then(json<RunSnapshot>),

  runDetail: (id: string) => apiFetch(`/api/history/${id}`).then(json<RunDetail>),

  activity: (projectId: string, limit = 200) =>
    apiFetch(`/api/projects/${projectId}/activity?limit=${limit}`).then(
      json<{ events: ActivityEvent[] }>,
    ),

  projectCost: (projectId: string) =>
    apiFetch(`/api/projects/${projectId}/cost`).then(json<ProjectCost>),


  projectMetrics: (projectId: string) =>
    apiFetch(`/api/projects/${projectId}/metrics`).then(json<ProjectMetrics>),

  config: () =>
    apiFetch("/api/config").then(
      json<{
        version: string; // engine version (ADR-0055) — shown in the header
        // Maturity channel (ADR-0088) — alpha | beta | rc | stable. Optional so a header
        // against an older API still renders the version instead of blanking.
        maturity?: string;
        gitlab: boolean;
        admin_required: boolean;
        max_iterations_ceiling: number;
      }>,
    ),

  // Validate the admin token (X-Mosaera-Admin via adminFetch) — the unlock probe.
  adminVerify: () => adminFetch("/api/admin/verify").then(json<{ ok: boolean }>),

  // --- general / operational settings (budgets, iterations, breaker, loops, sandbox) ---
  getGeneralSettings: () =>
    apiFetch("/api/settings/general").then(json<GeneralSettings>),
  saveGeneralSettings: (values: Record<string, KnobValue>) =>
    adminFetch("/api/settings/general", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values }),
    }).then(json<GeneralSettings>),

  // --- users (admin-managed accounts) ---
  listUsers: () =>
    adminFetch("/api/auth/users").then(json<{ users: AuthUser[]; max_users: number }>),
  createUser: (username: string, password: string, is_admin = false) =>
    adminFetch("/api/auth/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, is_admin }),
    }).then(json<{ user: AuthUser }>),
  deleteUser: (id: number) =>
    adminFetch(`/api/auth/users/${id}`, { method: "DELETE" }).then(json<{ ok: boolean }>),

  patchUrl: (id: string) => withToken(`/api/runs/${id}/patch`),

  openMr: (id: string) =>
    apiFetch(`/api/runs/${id}/open-mr`, { method: "POST" }).then(json<{ opened: boolean; url: string }>),

  getModels: () => apiFetch("/api/models").then(json<{ sources: ModelSource[] }>),

  getPricing: () => apiFetch("/api/pricing").then(json<Pricing>),

  savePricing: (prices: Record<string, PriceEntry>) =>
    adminFetch("/api/pricing", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prices }),
    }).then(json<Pricing>),

  getProviders: () => apiFetch("/api/providers").then(json<ProvidersState>),

  saveProviders: (body: ProvidersUpdate) =>
    adminFetch("/api/providers", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<ProvidersState>),

  /** Validate a hosted provider's key and list the models it grants (BYOM live
   *  discovery). Pass the just-typed key to test before saving; omit it to use the
   *  saved/env key. Returns {ok:false, error} (never throws) on a bad/unreachable key. */
  testProvider: (provider: string, api_key?: string, base_url?: string) =>
    adminFetch("/api/providers/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, api_key, base_url }),
    }).then(json<{ ok: boolean; count: number; models: string[]; error?: string }>),

  getCostModes: () => apiFetch("/api/cost-modes").then(json<CostModesState>),

  saveCostModes: (body: CostModesUpdate) =>
    adminFetch("/api/cost-modes", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<CostModesState>),

  estimate: (projectId: string, costMode: string) =>
    apiFetch(`/api/projects/${projectId}/estimate?cost_mode=${encodeURIComponent(costMode)}`).then(
      json<CostEstimate>,
    ),

  gitlabStatus: () => apiFetch("/api/gitlab/status").then(json<GitlabStatus>),

  features: () =>
    apiFetch("/api/features").then(json<{ delete_tool_enabled: boolean }>),

  setDeleteTool: (enabled: boolean) =>
    adminFetch("/api/features/delete-tool", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }).then(json<{ delete_tool_enabled: boolean }>),

  saveGitlab: (body: { url?: string; token?: string; oauth_client_id?: string; oauth_client_secret?: string; base_url?: string }) =>
    adminFetch("/api/gitlab/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<GitlabStatus>),

  gitlabVisibility: () => apiFetch("/api/gitlab/visibility").then(json<GitlabVisibility>),

  gitlabChecklist: (project: string) =>
    apiFetch(`/api/gitlab/checklist?project=${encodeURIComponent(project)}`).then(
      json<{ project: string; checks: CheckRow[] }>,
    ),

  listProjects: () => apiFetch("/api/projects").then(json<{ projects: Project[] }>),

  createProject: (body: { name: string; source_repo: string; gitlab_token?: string }) =>
    apiFetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<Project>),

  setAutonomous: (id: string, on: boolean) =>
    apiFetch(`/api/projects/${id}/autonomous`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ on }),
    }).then(json<Project>),

  startAutonomous: (id: string) =>
    apiFetch(`/api/projects/${id}/start`, { method: "POST" }).then(json<{ status: string }>),

  setProjectBudget: (id: string, body: { budget_usd: number | null; budget_tokens: number | null }) =>
    apiFetch(`/api/projects/${id}/budget`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<Project>),

  projectBudget: (id: string) =>
    apiFetch(`/api/projects/${id}/budget`).then(json<ProjectBudgetStatus>),

  // each token arg: undefined = unchanged, "" = clear, value = set — independent (ADR-0103)
  setProjectToken: (id: string, token?: string, apiToken?: string) =>
    adminFetch(`/api/projects/${id}/token`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...(token === undefined ? {} : { token }), ...(apiToken === undefined ? {} : { api_token: apiToken }) }) }).then(json<Project>),

  deleteProject: (id: string) =>
    apiFetch(`/api/projects/${id}`, { method: "DELETE" }).then(json<{ deleted: string }>),

  cancelRun: (id: string) =>
    apiFetch(`/api/runs/${id}/cancel`, { method: "POST" }).then(json<{ cancelled: string }>),

  setRunMode: (id: string, mode: string) =>
    apiFetch(`/api/runs/${id}/mode`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    }).then(json<{ run_id: string; mode: string; previous: string; currently_parked: boolean; effective: "immediate" | "next_gate" }>),

  runReport: (id: string) =>
    apiFetch(`/api/runs/${id}/report`).then(json<{ markdown: string }>),

  /** The durable per-step event stream (run_events — server-ms timestamps); falls back
   *  to the live session server-side. The ledger's chronological spine. */
  transcript: (id: string) =>
    apiFetch(`/api/runs/${id}/transcript`).then(json<RunTranscriptResponse>),

  projectFiles: (id: string) =>
    apiFetch(`/api/projects/${id}/files`).then(json<{ files: string[] }>),
  projectPatchUrl: (id: string) => withToken(`/api/projects/${id}/patch`),
  projectFileUrl: (id: string, path: string) =>
    // Per-segment encoding: FastAPI's {path:path} decodes it; keeps spaces/#
    // in produced-file paths downloadable.
    withToken(`/api/projects/${id}/files/${path.split("/").map(encodeURIComponent).join("/")}`),

  // Delivery calls (projectDiff/projectMrStatus/openItemMr/mergeProject + branches) live in
  // api/delivery.ts (ADR-0103 — this file was at the god-file ceiling) and are spread in below.

  // sessionId scopes the transcript to one PM thread (issue #30); omitted → whole project.
  /** Records the operator's accept/dismiss ONLY — applying keeps its own validator and gates. */
  resolveProposal: (id: string, proposalId: number, status: "accepted" | "dismissed") =>
    apiFetch(`/api/projects/${id}/messages/proposals/${proposalId}/${status}`, {
      method: "POST",
    }).then(json<{ ok: boolean }>),

  projectMessages: (id: string, sessionId?: string) =>
    apiFetch(
      `/api/projects/${id}/messages${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ""}`,
    ).then(json<{ messages: ProjectMessage[] }>),

  sendMessage: (id: string, text: string, attachmentIds: string[] = [], sessionId?: string) =>
    apiFetch(`/api/projects/${id}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        attachments: attachmentIds.map((attachment_id) => ({ attachment_id })),
        session_id: sessionId ?? null,
      }),
    }).then(
      json<{
        reply: string;
        changeset: ChangesetOp[];
        charter_proposal?: CharterProposal | null;
        /** The backlog item Quincy just raised an intake question on (stored server-side). */
        clarified_item?: BacklogItem | null;
      }>,
    ),

  uploadAttachment: (id: string, file: File, scope: AttachmentScope) => {
    const form = new FormData();
    form.append("file", file);
    form.append("scope", scope);
    return apiFetch(`/api/projects/${id}/attachments`, { method: "POST", body: form }).then(
      json<Attachment>,
    );
  },

  listAttachments: (id: string) =>
    apiFetch(`/api/projects/${id}/attachments`).then(json<{ attachments: Attachment[] }>),

  getAttachment: (id: string, attachmentId: string) =>
    apiFetch(`/api/projects/${id}/attachments/${attachmentId}`).then(json<Attachment>),

  patchAttachmentScope: (id: string, attachmentId: string, scope: AttachmentScope) =>
    apiFetch(`/api/projects/${id}/attachments/${attachmentId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scope }),
    }).then(json<Attachment>),

  attachmentThumbnailUrl: (id: string, attachmentId: string) =>
    withToken(`/api/projects/${id}/attachments/${attachmentId}/thumbnail`),

  attachmentImageUrl: (id: string, attachmentId: string) =>
    withToken(`/api/projects/${id}/attachments/${attachmentId}/image`),

  attachmentFileUrl: (id: string, attachmentId: string) =>
    withToken(`/api/projects/${id}/attachments/${attachmentId}/file`),

  attachmentContent: (id: string, attachmentId: string) =>
    apiFetch(`/api/projects/${id}/attachments/${attachmentId}/content`).then(
      json<{ text: string; note: string }>,
    ),

  transcribeStatus: () =>
    apiFetch("/api/transcribe/status").then(
      json<{ enabled: boolean; state: string; model: string; prefer: string }>,
    ),

  transcribeAudio: (blob: Blob) => {
    const form = new FormData();
    form.append("audio", blob, "recording.webm");
    return apiFetch("/api/transcribe", { method: "POST", body: form }).then(
      json<{ text: string; duration_seconds: number; model: string; language: string }>,
    );
  },

  deleteAttachment: (id: string, attachmentId: string) =>
    apiFetch(`/api/projects/${id}/attachments/${attachmentId}`, { method: "DELETE" }).then(
      json<{ deleted: string }>,
    ),

  getProject: (id: string) => apiFetch(`/api/projects/${id}`).then(json<Project>),

  approveProject: (id: string) =>
    apiFetch(`/api/projects/${id}/approve`, { method: "POST" }).then(json<Project>),

  // --- onboarding: durable map + trusted charter (#42/ADR-0047) ---

  /** The durable project map + server-derived stale list + recon overlay. Open read. */
  getProjectMap: (id: string) =>
    apiFetch(`/api/projects/${id}/map`).then(json<ProjectMap>),

  /** Kick off a background recon sweep over the clone (re-runnable). */
  triggerRecon: (id: string) =>
    apiFetch(`/api/projects/${id}/recon`, { method: "POST" }).then(json<{ status: string }>),

  /** The trusted charter (honest defaults when unset). Open read. */
  getCharter: (id: string) => apiFetch(`/api/projects/${id}/charter`).then(json<Charter>),

  /** Write the trusted charter. The gate is PER FIELD (ADR-0047 amendment 2026-08-18):
   *  goal/constraints are member-writable; CHANGING posture still needs an admin. */
  putCharter: (id: string, body: CharterWrite) =>
    adminFetch(`/api/projects/${id}/charter`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<Charter>),

  addBacklogItem: (id: string, body: { title: string; description?: string; acceptance?: string }) =>
    apiFetch(`/api/projects/${id}/backlog`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<BacklogItem>),

  patchBacklogItem: (id: string, itemId: number, body: Partial<BacklogItem>) =>
    apiFetch(`/api/projects/${id}/backlog/${itemId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<BacklogItem>),

  setItemDependencies: (id: string, itemId: number, dependsOn: number[]) =>
    apiFetch(`/api/projects/${id}/backlog/${itemId}/dependencies`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ depends_on: dependsOn }),
    }).then(json<BacklogItem>),

  /** Persist a complete new order (all item ids). */
  reorderBacklog: (id: string, orderedIds: number[]) =>
    apiFetch(`/api/projects/${id}/backlog/reorder`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ordered_ids: orderedIds }),
    }).then(json<{ backlog: BacklogItem[] }>),

  /** Soft-lock or unlock a single item (optionally with a reason). */
  /** Resolve an intake clarification (ADR-0080): accept a proposal / edited text, or reject. */
  resolveClarification: (
    id: string,
    itemId: number,
    body: ClarificationResolveBody,
  ) =>
    apiFetch(`/api/projects/${id}/backlog/${itemId}/clarification/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<BacklogItem>),

  setItemLock: (id: string, itemId: number, locked: boolean, reason?: string) =>
    apiFetch(`/api/projects/${id}/backlog/${itemId}/lock`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ locked, ...(reason !== undefined ? { reason } : {}) }),
    }).then(json<BacklogItem>),

  /** Ask Quincy to propose a curation changeset — PROPOSE only, nothing applied. */
  curateBacklog: (id: string, instruction?: string) =>
    apiFetch(`/api/projects/${id}/backlog/curate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction }),
    }).then(json<{ changeset: ChangesetOp[] }>),

  /** Apply an approved changeset (400 on any invalid op). */
  applyChangeset: (id: string, changeset: ChangesetOp[]) =>
    apiFetch(`/api/projects/${id}/backlog/curate/apply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ changeset }),
    }).then(json<{ backlog: BacklogItem[] }>),

  generateBacklog: (id: string) =>
    apiFetch(`/api/projects/${id}/backlog/generate`, { method: "POST" }).then(json<{ status: string }>),

  runBacklogItem: (
    id: string,
    itemId: number,
    mode: RunMode = "guided",
    limits?: {
      max_iterations?: number | null;
      budget_tokens?: number | null;
      budget_usd?: number | null;
      cost_mode?: string | null;
    },
    /** Run a soft-locked/dep-blocked item early (a locked run 409s otherwise). */
    override?: boolean,
  ) =>
    apiFetch(`/api/projects/${id}/backlog/${itemId}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, ...limits, ...(override ? { override: true } : {}) }),
    }).then(json<RunSnapshot>),

  // stats = per-file numstat (null counts = binary); remote_synced = is the branch tip
  // on origin? null/absent = honest unknown (ADR-0102). Both absent on older servers.
  ...projectSetupApi, // ADR-0113: projectSetup / saveProjectSetup
  ...deliveryApi, // ADR-0103: projectDiff / projectMrStatus / mergeProject / openItemMr / branches
  ...proofApi, // ADR-0109: projectProof (the receipt-backed project aggregate)
};

// Re-exported so existing `from "./client"` importers keep working unchanged.
export type { PriceEntry, Pricing };

/** Bindable models grouped by provider (Ollama live via /api/tags; hosted BYOM providers
 *  contribute curated suggestions). Powers the pricing and role-model pickers. */
export interface ModelSource {
  source: string;
  models: string[];
  served?: string[]; // subset of `models` CONFIRMED usable now; absent = an older server
}

/** A model provider the UI can offer (BYOM #21). Keys are write-only — the API
 *  returns only `key_masked`, never the raw key. */
export interface Provider {
  id: string;
  local: boolean; // runs locally, needs no API key (Ollama)
  env_key: string | null; // native API-key env var for the no-UI path
  suggestions: string[];
  configured: boolean; // has a key (stored or via env) or is local
  has_key: boolean; // a key is stored server-side
  uses_env_key: boolean; // configured via its native env var, not the UI
  key_masked: string; // "…last4" hint, never the value
  base_url: string | null;
  on_box: boolean; // operator declared this loopback endpoint on-box (ADR-0024)
}

/** Which provider+model backs each agent role. */
export interface RoleBinding {
  provider: string;
  model: string;
}

/** Per-role display metadata from the server's agent registry (mosaera_core.team),
 *  so the Settings UI renders a row per role — including any newly added agent —
 *  without a hardcoded role list. */
export interface RoleMeta {
  role: string;
  label: string; // functional name: PM / Coder / Reviewer / …
  display_name: string; // persona: Quincy / Forge / Rook / …
  remit: string;
}

export interface ProvidersState {
  providers: Provider[];
  roles: Record<string, RoleBinding>;
  role_meta: RoleMeta[];
  sources: ModelSource[];
}

/** Partial update to provider creds and/or role bindings. */
export interface ProvidersUpdate {
  providers?: Record<string, { api_key?: string; base_url?: string; on_box?: boolean }>;
  roles?: Record<string, RoleBinding>;
}

/** A role's binding under a cost-mode (#7): the explicit override (if any) plus
 *  the effective binding (override, else the base BYOM fallback). */
export interface CostModeRole {
  provider: string | null; // explicit override provider, else null (falls back)
  model: string | null;
  effective_provider: string;
  effective_model: string;
  overridden: boolean;
}

export type CostRoleMap = Record<string, CostModeRole>;

export interface CostModesState {
  modes: Record<string, CostRoleMap>;
  default_cost_mode: string;
  available: string[]; // ordered mode ids: economy, balanced, premium
  role_meta: RoleMeta[];
  sources: ModelSource[];
}

/** Full replacement of cost-mode profiles + optionally the default mode. */
export interface CostModesUpdate {
  modes: Record<string, Record<string, RoleBinding>>;
  default_cost_mode?: string;
}

/** Conditioned per-mode cost projection for a project (#7). `available:false`
 *  until there's run history to project from. */
export interface CostEstimate {
  cost_mode: string;
  available: boolean;
  runs_metered: number;
  projected_usd?: number;
  per_role?: {
    role: string;
    provider: string;
    model: string;
    avg_input_tokens: number;
    avg_output_tokens: number;
    usd: number;
  }[];
}

export interface GitlabStatus {
  configured: boolean;
  url: string;
  token_masked?: string;
  ok?: boolean;
  error?: string;
  user?: { username: string; name: string; is_admin: boolean };
  scopes?: string[];
  expires_at?: string | null;
  oauth_configured?: boolean; // ADR-0104 OAuth app config (UI-settable); presence only, never the secret
  oauth_client_id_masked?: string | null;
  oauth_secret_set?: boolean; base_url?: string | null; oauth_note?: string; oauth_env_pinned?: boolean; // env_pinned = set via env, read-only in UI
}

export interface GitlabProject {
  path: string;
  access_level: number;
  can_push: boolean;
  default_branch: string | null;
}

export interface GitlabVisibility {
  groups: { path: string; name: string }[];
  projects: GitlabProject[];
  error?: string | null;
}

export interface CheckRow {
  label: string;
  ok: boolean;
  detail: string;
}

