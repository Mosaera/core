/* Triage: every open backlog item bucketed by the ONE intervention it needs.
 *
 * The Overview used to report nouns — "9 in review", "13 need attention" — and left the operator
 * to infer the verb. That inference is the work, and the product made the human do it. This module
 * is the derivation behind the worklist: a first-match-wins ladder, one bucket per item, so the
 * counts sum to the open set and every row carries an action rather than a status.
 *
 * TOTALITY IS THE POINT. The ladder the design started with had six rungs and did not partition:
 * an item being actively worked fell into "Inspect" (its live run has no diagnosis yet), a
 * never-attempted item fell into "Inspect" (nothing to inspect — the verb is "run it"), and the
 * whole pre-gate failure population (give_up, stalled:*, iteration_limit, rode_to_cap) fell into
 * "Inspect" too, because those runs stop BEFORE the gate and so carry no gate reasons. Three of
 * the six real populations landed in the residual bucket with the wrong verb. The floor rungs
 * below exist for exactly that, and `triage()` is pinned by a test that asserts the partition.
 *
 * Reasons are classified with the SAME map the gate uses (`VERDICT_REASON_CLASS`, itself
 * double-locked against `mosaera_policies.gate.REASON_CLASS` by a Python AST test), so the
 * console can never invent a severity the engine does not recognise. */

import type { BacklogItem, HistoryRun } from "../api/client";
import { VERDICT_REASON_CLASS, dominantReason, type ReasonClass } from "./verdict";

export type TriageVerb =
  | "answer"
  | "review"
  | "respecify"
  | "environment"
  | "judge"
  | "blocked"
  | "run"
  | "inspect";

export interface TriageEntry {
  item: BacklogItem;
  verb: TriageVerb;
  /** The attempt the verdict was read from — null when the item has never been attempted. */
  run: HistoryRun | null;
  /** A short factual reason, derived from recorded fields. Never model prose. */
  note: string;
}

export interface TriageBucket {
  verb: TriageVerb;
  label: string;
  /** What the operator actually does, in the imperative. */
  action: string;
  severity: "red" | "amber" | "neutral";
  entries: TriageEntry[];
}

/** Ladder order IS the display order: the earlier a verb sits, the sooner it blocks the project. */
export const TRIAGE_ORDER: TriageVerb[] = [
  "answer",
  "review",
  "respecify",
  "environment",
  "judge",
  "blocked",
  "run",
  "inspect",
];

export const TRIAGE_META: Record<TriageVerb, Omit<TriageBucket, "verb" | "entries">> = {
  answer: {
    label: "Answer a question",
    action: "The engine is blocked on you — nothing about this item moves until it is answered.",
    severity: "red",
  },
  review: {
    label: "Review and accept",
    action: "Delivered work waiting on your judgment.",
    severity: "amber",
  },
  respecify: {
    label: "Re-specify",
    action: "The item is the defect, not the code. Retrying spends money on the same wall.",
    severity: "amber",
  },
  environment: {
    label: "Fix the environment",
    action: "A check never measured this code. Re-scoping cannot fix a check that did not run.",
    severity: "amber",
  },
  judge: {
    label: "Judge or re-scope",
    action: "The work was measured and found wanting.",
    severity: "amber",
  },
  blocked: {
    label: "Blocked",
    action: "Waiting on another item or a hold — not actionable yet.",
    severity: "neutral",
  },
  run: {
    label: "Run it",
    action: "Ready and never attempted.",
    severity: "neutral",
  },
  inspect: {
    label: "Inspect",
    action: "Stopped without recording a cause the console can classify.",
    severity: "neutral",
  },
};

/** Statuses that mean the item is finished and accepted — never triaged. */
const CLOSED = new Set(["done"]);

/** Park causes where the SPEC is the defect (intake or planning refused the item as written). */
const SPEC_CAUSES = new Set(["under_specified", "plan_unworkable"]);

/** Pre-gate stops: real failures that never reached the gate, so they carry no gate reasons.
 *  Without this set they fall to the residual bucket — which is what made the first ladder lie. */
const PRE_GATE_CAUSES = new Set(["give_up", "iteration_limit", "rode_to_cap"]);

function attemptsOf(runs: HistoryRun[], itemId: number): HistoryRun[] {
  return runs
    .filter((r) => r.item_id === itemId)
    .sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")));
}

/** The attempt whose verdict the ladder reads: the newest one that actually recorded a diagnosis,
 *  else the newest attempt. A CANCELLED run usually records nothing, so preferring a diagnosed
 *  attempt keeps a cancel from erasing the reason the item is stuck. */
function verdictRun(attempts: HistoryRun[]): HistoryRun | null {
  return attempts.find((r) => r.diagnosis) ?? attempts[0] ?? null;
}

function classOf(run: HistoryRun | null): ReasonClass | null {
  const reasons = run?.diagnosis?.gate_reasons ?? [];
  if (reasons.length === 0) return null;
  const token = dominantReason(reasons);
  return token ? (VERDICT_REASON_CLASS[token] ?? "objection") : null;
}

function reasonNote(run: HistoryRun | null): string {
  const reasons = run?.diagnosis?.gate_reasons ?? [];
  const token = reasons.length ? dominantReason(reasons) : null;
  return token ? token.replace(/_/g, " ") : "";
}

/**
 * Bucket every open item by the intervention it needs.
 *
 * `liveRunIds` — runs executing right now. An item being worked needs nobody, so it is EXCLUDED
 * rather than triaged; its latest run has no diagnosis yet and would otherwise read as "inspect"
 * while the team is mid-flight. An open question still outranks this: a live run does not make an
 * unanswered ask disappear (ADR-0107).
 */
export function triage(
  items: BacklogItem[],
  runs: HistoryRun[],
  liveRunIds: ReadonlySet<string> = new Set(),
): TriageEntry[] {
  const out: TriageEntry[] = [];
  for (const item of items) {
    if (CLOSED.has(item.status)) continue;

    const attempts = attemptsOf(runs, item.id);
    const run = verdictRun(attempts);
    const cause = String(run?.diagnosis?.park_cause ?? "");
    const cls = classOf(run);
    const held = Boolean(item.locked) || (item.blocked_by ?? []).length > 0;

    // 1 · An open ask outranks everything, including work in flight (ADR-0107).
    if (item.clarification) {
      out.push({ item, verb: "answer", run, note: item.clarification.axis ?? "open question" });
      continue;
    }
    // 2 · In flight: needs nobody. Excluded, not bucketed.
    if (attempts.some((r) => r.status === "RUNNING" || liveRunIds.has(r.id))) continue;
    // 3 · Delivered, awaiting the human.
    if (item.status === "in_review") {
      out.push({ item, verb: "review", run, note: "awaiting your review" });
      continue;
    }
    // 4 · The spec refused the item — Quincy's job, not another attempt.
    if (SPEC_CAUSES.has(cause)) {
      out.push({ item, verb: "respecify", run, note: cause.replace(/_/g, " ") });
      continue;
    }
    // 5 · A check never measured the code: configuration, not craft.
    if (cls === "not_run") {
      out.push({ item, verb: "environment", run, note: reasonNote(run) });
      continue;
    }
    // 6 · Measured and found wanting — including the pre-gate stops, which record a cause but
    //     never reach the gate and so carry no reasons to classify.
    if (cls === "tamper" || cls === "objection" || cls === "shortfall") {
      out.push({ item, verb: "judge", run, note: reasonNote(run) });
      continue;
    }
    if (PRE_GATE_CAUSES.has(cause) || cause.startsWith("stalled:")) {
      out.push({ item, verb: "judge", run, note: cause.replace(/_/g, " ") });
      continue;
    }
    // 7 · Held by a dependency or a soft lock: real, but not actionable now.
    if (held) {
      out.push({
        item,
        verb: "blocked",
        run,
        note: item.locked
          ? (item.lock_reason ?? "on hold")
          : `waiting on #${(item.blocked_by ?? []).join(", #")}`,
      });
      continue;
    }
    // 8 · Never attempted: the verb is "run it", not "inspect it".
    if (attempts.length === 0) {
      out.push({ item, verb: "run", run: null, note: "never attempted" });
      continue;
    }
    // 9 · Honest residual: it says it cannot classify rather than inventing a cause.
    out.push({ item, verb: "inspect", run, note: cause ? cause.replace(/_/g, " ") : "no recorded cause" });
  }
  return out;
}

/** Non-empty buckets, in ladder order. */
export function triageBuckets(entries: TriageEntry[]): TriageBucket[] {
  return TRIAGE_ORDER.map((verb) => ({
    verb,
    ...TRIAGE_META[verb],
    entries: entries.filter((e) => e.verb === verb),
  })).filter((b) => b.entries.length > 0);
}

export interface ThrashSignal {
  item: BacklogItem;
  /** Consecutive most-recent attempts that failed the SAME way. */
  repeats: number;
  /** Total attempts on the item. */
  attempts: number;
  /** The shared signature, as reason tokens. */
  signature: string[];
}

/**
 * Items whose most recent attempts failed in the IDENTICAL way — the engine walking into the same
 * wall. Measured on the live instance: item #113 returned
 * `validation_failed, reviewer_unknown, security_unverified, claim_behavioral_failed` on attempt 1
 * and again on attempt 3, and was retried eight times over 27 hours; the clarification that would
 * unblock it — three proposals, answerable in under a minute — was not raised until a day later.
 * A page that says "failed 3× with the same signature" earns its place on attempt two.
 *
 * The EMPTY signature is excluded deliberately: a pre-gate park records no gate reasons, so two
 * consecutive stalls would "share" an empty set and the detector would fire hardest on exactly the
 * runs where a shared signature proves nothing.
 */
export function thrashing(
  items: BacklogItem[],
  runs: HistoryRun[],
  minRepeats = 2,
): ThrashSignal[] {
  const out: ThrashSignal[] = [];
  for (const item of items) {
    if (CLOSED.has(item.status)) continue;
    const attempts = attemptsOf(runs, item.id).filter((r) => r.diagnosis);
    const sig = (r: HistoryRun) => [...(r.diagnosis?.gate_reasons ?? [])].sort().join("|");
    const newest = attempts[0];
    if (!newest || !sig(newest)) continue; // no signature = nothing to match on
    let repeats = 1;
    for (let i = 1; i < attempts.length; i += 1) {
      if (sig(attempts[i]) !== sig(newest)) break;
      repeats += 1;
    }
    if (repeats >= minRepeats) {
      out.push({
        item,
        repeats,
        attempts: attemptsOf(runs, item.id).length,
        signature: [...(newest.diagnosis?.gate_reasons ?? [])],
      });
    }
  }
  return out.sort((a, b) => b.repeats - a.repeats || b.attempts - a.attempts);
}

/** Items whose verb demands the operator act now (the count the page leads with). */
export function needsYou(entries: TriageEntry[]): TriageEntry[] {
  return entries.filter((e) => TRIAGE_META[e.verb].severity !== "neutral");
}
