/* Pure derivations for the Runs (execution history + diagnostics) tab. Every
   value traces to a real API field. Run status, validation status, and
   approval status are separate facts — nothing here merges them into a single
   green/red binary. Unit-tested in runs-lib.test.ts. */

import type { HistoryRun, OutcomeVerdict, RunDetail, RunDiagnosis } from "../api/client";
import { gateReason, stopReason, stopSentence, TERMINATED } from "./plain";

/* ------------------------------------------------------------------- routing */

/** Link to a LIVE run. Project-scoped surfaces pass the project id so the run
 *  opens inside the project shell (`/projects/:id/runs/:runId`); global
 *  surfaces omit it and fall back to `/runs/:id`. */
export function liveRunHref(runId: string, projectId?: string | null): string {
  return projectId ? `/projects/${projectId}/runs/${runId}` : `/runs/${runId}`;
}

/** A readable, URL-safe slug from a run's task, for the commit-page URL tail
 *  (cosmetic — the run id remains authoritative). Empty string if nothing survives. */
export function slugifyTask(task: string): string {
  return task
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 50)
    .replace(/-+$/g, "");
}

/** Link to a run's DURABLE record (history), project-scoped when known. When a
 *  `task` is given, a cosmetic slug tail is appended (GitLab-commit style); the
 *  id still resolves the route, so bare `/history/:id` URLs keep working. */
export function historyRunHref(
  runId: string,
  projectId?: string | null,
  task?: string,
): string {
  const base = projectId ? `/projects/${projectId}/history/${runId}` : `/history/${runId}`;
  const slug = task ? slugifyTask(task) : "";
  return slug ? `${base}/${slug}` : base;
}

/* The attempt-level grouping (`groupProjectRuns`/`runsSummary`) lived here until the item
 * consolidation (de-firehose phase 2, lib/itemRuns.ts). Its residual-else counted every imperfect
 * ATTEMPT as "needs attention" — and branched on truthy `tests_passed`, the tri-state misuse
 * lib/validation.ts:1 outlaws. Deleted, not adapted. */

/** The run's SHORT NAME — the first line of `task`, which is the backlog item's title by
 *  construction: the launcher builds `task = title \n\n description \n\n criteria`
 *  (task_spec.py). The Firehose Audit's #1 finding was six surfaces using the whole paragraph as
 *  a title — the run pages rendered ~six lines of display type before any verdict. One derivation,
 *  zero data changes; the paragraph stays one disclosure away, never deleted. */
export function taskTitle(task: string | undefined): string {
  return (task ?? "").split("\n")[0].trim() || "Run";
}

/** Everything AFTER the title line — the description + acceptance criteria, for the disclosure. */
export function taskBody(task: string | undefined): string {
  const lines = (task ?? "").split("\n");
  return lines.slice(1).join("\n").trim();
}

/** Runs arrive newest-first from the API. */
export function latestRun(runs: HistoryRun[]): HistoryRun | undefined {
  return runs[0];
}

/* ------------------------------------------------------- validation verdict */

export type VerdictKind =
  | "pass"
  | "failed"
  | "no-tests" // legacy pre-planner rows only
  | "unavailable" // the planner found no honest offline validation
  | "unverified" // delivered without an automated validator (deliver-with-caveat, P3)
  | "no-evidence"
  | "pending";

export interface ValidationVerdict {
  kind: VerdictKind;
  label: string;
  helper?: string;
}

export interface ParsedValidationPlan {
  project_type?: string;
  reason?: string;
  steps?: { name?: string; cmd?: string[] }[];
  results?: {
    name?: string;
    exit_code?: number;
    timed_out?: boolean;
    ok?: boolean;
    output?: string;
  }[];
}

/** The planner's persisted plan (a `validation_plan` decision row), if any. */
export function parseValidationPlan(detail: RunDetail | undefined): ParsedValidationPlan | undefined {
  const row = lastMatch(detail?.decisions, (d) => d.kind === "validation_plan");
  if (!row) return undefined;
  try {
    const parsed: unknown = JSON.parse(row.content);
    return typeof parsed === "object" && parsed !== null ? (parsed as ParsedValidationPlan) : undefined;
  } catch {
    return undefined;
  }
}

export interface ParsedGateDecision {
  action: string; // deliver | revise | require_human
  reasons: string[];
  verdict: string; // reviewer verdict — APPROVE | REQUEST_CHANGES | BLOCK | CONFLICT | UNKNOWN
  testsPassed: boolean | null;
  humanOverride: boolean;
  validationStrength: string; // suite | shallow | none | unknown (ADR-0034)
}

/** The delivery gate's recorded decision (a `gate_decision` decision row — a
 *  stable `k=v; ` string written by mosaera_core.persist). Surfaces the
 *  governance-visible fact that a human overrode flagged signals to deliver.
 *  Booleans are Python-str ("True"/"False"/"None") on the wire. */
export function parseGateDecision(detail: RunDetail | undefined): ParsedGateDecision | undefined {
  const row = lastMatch(detail?.decisions, (d) => d.kind === "gate_decision");
  if (!row) return undefined;
  const kv = new Map<string, string>();
  for (const part of row.content.split(";")) {
    const eq = part.indexOf("=");
    if (eq > 0) kv.set(part.slice(0, eq).trim(), part.slice(eq + 1).trim());
  }
  const tp = kv.get("tests_passed");
  return {
    action: kv.get("action") ?? "",
    reasons: (kv.get("reasons") ?? "")
      .split(",")
      .map((r) => r.trim())
      .filter(Boolean),
    verdict: kv.get("verdict") ?? "",
    testsPassed: tp === "True" ? true : tp === "False" ? false : null,
    humanOverride: kv.get("human_override") === "True",
    // What a passing validation was actually worth on this run (ADR-0034): "suite" (a real
    // test suite ran), "shallow" (it only parses — compileall/typecheck/HTML check), "none"
    // (nothing executed), "unknown" (no plan reached the gate). Older runs have no such key.
    validationStrength: kv.get("validation_strength") ?? "unknown",
  };
}

/** The newest decision row of a kind, or "". The generic accessor for persisted
 *  run artifacts (plan / design / review / summary / scan / …). */
/** The newest matching element (decisions arrive oldest-first; a re-persisted run —
 *  e.g. the ADR-0078 giveup capture followed by a resumed deliver — appends fresher rows). */
export function lastMatch<T>(arr: T[] | undefined, pred: (t: T) => boolean): T | undefined {
  if (!arr) return undefined;
  for (let i = arr.length - 1; i >= 0; i--) if (pred(arr[i])) return arr[i];
  return undefined;
}

export function decisionOf(detail: RunDetail | undefined, kind: string): string {
  return lastMatch(detail?.decisions, (d) => d.kind === kind)?.content ?? "";
}

/** Durable-row statuses → the live status vocabulary the hero/badges speak. */
export const DURABLE_STATUS: Record<string, string> = {
  APPROVED: "completed",
  "NOT APPROVED": "incomplete",
  INCOMPLETE: "incomplete",
  CANCELLED: "cancelled",
  ERROR: "error",
  RUNNING: "running",
  AWAITING_APPROVAL: "awaiting_approval",
};

/* ------------------------------------------------------------------ quality */

/** Advisory code-quality of a run's changed files, produced by the deterministic
 *  engine (mosaera_core.quality) and persisted as a `quality` decision. Display
 *  only — never a gate (Phase 1). Absent when the change touched no python. */
export interface QualityDim {
  name: string;
  score: number | null; // 0..100, or null when a tool couldn't run (N/A)
  detail: string;
}
export interface QualityScore {
  composite: number;
  dimensions: QualityDim[];
}

export function parseQuality(detail: RunDetail | undefined): QualityScore | null {
  const raw = lastMatch(detail?.decisions, (d) => d.kind === "quality")?.content ?? "";
  if (!raw) return null;
  try {
    const q = JSON.parse(raw) as QualityScore;
    if (typeof q.composite === "number" && Array.isArray(q.dimensions)) return q;
  } catch {
    // malformed decision — treat as absent rather than crash the run page
  }
  return null;
}

/** Targeted quality-revise attempts (Phase 2), newest-last, for the trail note. */
export function qualityRevises(detail: RunDetail | undefined): string[] {
  return (detail?.decisions ?? []).filter((d) => d.kind === "quality_revise").map((d) => d.content);
}

/* ------------------------------------------------------------------ receipt */

/** The durable delivery receipt (ADR-0071 amendment): everything a human's
 *  approval priced, normalized from either data source. */
export interface ParsedReceipt {
  action: string;
  reasons: string[];
  reviewerVerdict: string;
  testsPassed: boolean | null;
  oracleVerified: boolean | null; // null = the row predates the field
  validationStrength: string;
  unsatisfiedClaims: string[];
  humanOverride: boolean;
  oracleVouchedBy: string;
  oracleResidual: string;
  testsMutationCaught: boolean | null;
}

/** The recorded receipt: prefer the machine-readable `receipt` decision row
 *  (JSON, written since #63); fall back to the flat `gate_decision` string for
 *  older runs (which never carried the residual/vouch/mutation fields). */
export function parseReceipt(detail: RunDetail | undefined): ParsedReceipt | undefined {
  const row = lastMatch(detail?.decisions, (d) => d.kind === "receipt");
  if (row) {
    try {
      const r: unknown = JSON.parse(row.content);
      if (typeof r === "object" && r !== null) {
        const o = r as Record<string, unknown>;
        return {
          action: typeof o.action === "string" ? o.action : "",
          reasons: Array.isArray(o.reasons) ? o.reasons.map(String) : [],
          reviewerVerdict: typeof o.reviewer_verdict === "string" ? o.reviewer_verdict : "",
          testsPassed: typeof o.tests_passed === "boolean" ? o.tests_passed : null,
          oracleVerified: typeof o.oracle_verified === "boolean" ? o.oracle_verified : null,
          validationStrength:
            typeof o.validation_strength === "string" ? o.validation_strength : "unknown",
          unsatisfiedClaims: Array.isArray(o.unsatisfied_claims)
            ? o.unsatisfied_claims.map(String)
            : [],
          humanOverride: o.human_override === true,
          oracleVouchedBy: typeof o.oracle_vouched_by === "string" ? o.oracle_vouched_by : "",
          oracleResidual: typeof o.oracle_residual === "string" ? o.oracle_residual : "",
          testsMutationCaught:
            typeof o.tests_mutation_caught === "boolean" ? o.tests_mutation_caught : null,
        };
      }
    } catch {
      /* malformed receipt row → fall through to the flat-string contract */
    }
  }
  const flat = parseGateDecision(detail);
  if (!flat) return undefined;
  return {
    action: flat.action,
    reasons: flat.reasons,
    reviewerVerdict: flat.verdict,
    testsPassed: flat.testsPassed,
    oracleVerified: null,
    validationStrength: flat.validationStrength,
    unsatisfiedClaims: [],
    humanOverride: flat.humanOverride,
    oracleVouchedBy: "",
    oracleResidual: "",
    testsMutationCaught: null,
  };
}

/** The critic's verdict (#61) from the durable `critic` decision row. */
export function parseCriticVerdict(detail: RunDetail | undefined): OutcomeVerdict | undefined {
  const row = lastMatch(detail?.decisions, (d) => d.kind === "critic");
  if (!row) return undefined;
  try {
    const parsed: unknown = JSON.parse(row.content);
    return typeof parsed === "object" && parsed !== null ? (parsed as OutcomeVerdict) : undefined;
  } catch {
    return undefined;
  }
}

/** Honest validation verdict from real evidence only.
 *
 *  Backend facts this relies on: the graph's test node always runs when
 *  reached (test_cmd defaults to `pytest -q`) and persist writes a TestResult
 *  row whenever test output exists — so an EMPTY test_results[] proves the
 *  run never reached the test node, and pytest's "no tests ran" / exit code 5
 *  output identifies a repo with no test suite (heuristic shared with the
 *  /history/:id summary). tests_passed alone cannot make these distinctions —
 *  cards stay generic; only this fetched-detail verdict refines them. */
export function validationVerdict(
  detail: RunDetail | undefined,
  run: HistoryRun,
): ValidationVerdict {
  if (run.status === "RUNNING") {
    return { kind: "pending", label: "Validation pending", helper: "The run is still executing." };
  }
  if (!detail) {
    return { kind: "pending", label: "Loading validation record…" };
  }
  // The planner's verdict wins when present (validation_status set by P0-2+).
  if (detail.validation_status === "unavailable") {
    const plan = parseValidationPlan(detail);
    return {
      kind: "unavailable",
      label: "Validation unavailable",
      helper:
        plan?.reason ??
        "The planner found no way to validate this project in the offline sandbox.",
    };
  }
  if (detail.validation_status === "unverified") {
    return {
      kind: "unverified",
      label: "Delivered unverified",
      helper:
        "No automated validator for this project type — the reviewer approved it, but it " +
        "was not validated automatically.",
    };
  }
  if (detail.test_results.length === 0) {
    return {
      kind: "no-evidence",
      label: "No validation evidence recorded",
      helper: "This run has no stored validation output.",
    };
  }
  // Legacy pre-planner rows only: pytest exit-5 meant "no suite".
  if (
    detail.validation_status == null &&
    /no tests ran|exit code 5/i.test(detail.test_results[0].output)
  ) {
    return {
      kind: "no-tests",
      label: "No test suite detected",
      helper: "The validation command found no tests to run.",
    };
  }
  const failed =
    detail.validation_status === "failed" ||
    detail.test_results.some((r) => !r.passed) ||
    (detail.validation_status == null && !detail.tests_passed);
  if (failed) {
    return {
      kind: "failed",
      label: "Validation failed",
      helper:
        run.status === "APPROVED"
          ? "The agent completed and was approved, but validation did not pass. Review the run output before merging."
          : undefined,
    };
  }
  return { kind: "pass", label: "Tests pass" };
}

/* --------------------------------------------------------------- PM prefill */

export function explainRunPrefill(run: HistoryRun): string {
  return (
    `Explain the run "${run.task}" (${run.id}). ` +
    `What did the agent do, what changed, and what was the outcome?`
  );
}

/** Deliberately says "validation did not pass", never "failing tests" — the
 *  validation workflow is not mature enough to blame the implementation. */
export function diagnoseValidationPrefill(run: HistoryRun): string {
  return (
    `The run "${run.task}" (${run.id}) completed but its validation did not pass. ` +
    `Diagnose the likely cause and propose what to check or fix before merging.`
  );
}

/** The park handoff: point Quincy at WHY the run stopped (the PM's server context
 *  already carries the full diagnosis — this states the facts and the intent).
 *  Works diagnosis-less for pre-diagnosis rows: first line + the ask. */
export function parkedRunPrefill(
  run: Pick<HistoryRun, "id" | "task" | "status">,
  diagnosis?: RunDiagnosis | null,
): string {
  const lead = diagnosis ? stopSentence(diagnosis) : TERMINATED[run.status.toUpperCase()];
  const lines = [
    `The run "${run.task}" (${run.id}) stopped without delivering.${lead ? ` ${lead}` : ""}`,
  ];
  const reason = stopReason(diagnosis);
  if (reason) lines.push(`Why it stopped: ${reason.text}`);
  const gates = diagnosis?.gate_reasons ?? [];
  if (gates.length > 0) lines.push(`Blocked at the gate by: ${gates.map(gateReason).join("; ")}`);
  const unverified = diagnosis?.unsatisfied_claims?.length ?? 0;
  if (unverified > 0) {
    lines.push(`${unverified} claim${unverified === 1 ? "" : "s"} were never verified.`);
  }
  lines.push("Propose how to unblock: re-scope, split, or drop — and update the backlog item.");
  return lines.join("\n");
}
