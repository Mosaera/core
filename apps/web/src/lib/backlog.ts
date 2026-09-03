/* Pure derivations for the Backlog board. Every value traces to a real API
   field — no fabricated priority/estimate/source. Unit-tested in
   backlog-lib.test.ts. */

import type { LucideIcon } from "lucide-react";
import { AlertTriangle, CheckCircle2, Eye, ListTodo, PlayCircle } from "lucide-react";

import type { BacklogItem, HistoryRun } from "../api/client";
import type { BacklogCounts, Severity } from "./overview";

/** Split the single `acceptance` text blob into displayable criteria.
 *  Bulleted/numbered lines are stripped of their markers; a plain blob falls
 *  back to one criterion per non-empty line. The count is always the array
 *  length — never invented. */
export function acceptanceCriteria(text: string): string[] {
  const trimmed = text.trim();
  // F67 (#95): some items store their criteria as a PYTHON LIST REPR on a single line —
  // `['pyproject.toml exists…', 'src/budget_tracker/__init__.py is present (empty).']`. The
  // newline split below leaves that as one "criterion" and the operator reads brackets, quotes and
  // escapes on the card. Seen live driving LedgerCLI (case study #2, 2026-08-23). Unwrap it into
  // the strings it plainly contains; anything unrecognised falls through to the line parser rather
  // than being mangled.
  if (trimmed.startsWith("[") && trimmed.endsWith("]")) {
    const quoted = [...trimmed.matchAll(/'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"/g)]
      .map((m) => (m[1] ?? m[2] ?? "").replace(/\\(['"\\])/g, "$1").trim())
      .filter(Boolean);
    if (quoted.length > 0) return quoted;
  }
  const lines = trimmed
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  return lines.map((l) =>
    l
      .replace(/^[-*•]\s*(\[[ xX]\]\s*)?/, "")
      .replace(/^\d+[.)]\s*/, "")
      .trim(),
  ).filter(Boolean);
}

/** Toolbar one-liner: "5 items · 1 in progress · 1 needs review". Zero
 *  segments are omitted so the line only says things that are true. */
export function backlogSummary(counts: BacklogCounts): string {
  const parts = [`${counts.total} ${counts.total === 1 ? "item" : "items"}`];
  if (counts.inProgress > 0) parts.push(`${counts.inProgress} in progress`);
  if (counts.inReview > 0) parts.push(`${counts.inReview} needs review`);
  if (counts.done > 0) parts.push(`${counts.done} done`);
  return parts.join(" · ");
}

export interface ColumnMeta {
  key: string;
  label: string;
  /** One-line status meaning shown under the column label. */
  meaning: string;
  icon: LucideIcon;
  tone: "neutral" | "amber" | "green";
  emptyTitle: string;
  emptyHint: string;
}

export const BACKLOG_COLUMNS: ColumnMeta[] = [
  {
    key: "todo",
    label: "To do",
    meaning: "Queued for the agent",
    icon: ListTodo,
    tone: "neutral",
    emptyTitle: "Nothing queued",
    emptyHint: "Add an item, or ask the PM to plan the next batch.",
  },
  {
    key: "in_progress",
    label: "In progress",
    meaning: "Agent is working",
    icon: PlayCircle,
    tone: "neutral",
    emptyTitle: "Nothing running",
    emptyHint: "Run a to-do item to put the agent to work.",
  },
  {
    key: "in_review",
    label: "In review",
    meaning: "Waiting for your approval",
    icon: Eye,
    tone: "amber",
    emptyTitle: "Nothing waiting on you",
    emptyHint: "Finished runs land here for your approval.",
  },
  {
    key: "done",
    label: "Done",
    meaning: "Approved and delivered",
    icon: CheckCircle2,
    tone: "green",
    emptyTitle: "Nothing approved yet",
    emptyHint: "Items you approve in review collect here.",
  },
  {
    // Resilient sweep (ADR-0023): the autonomous sweep deferred this item (it got stuck)
    // and kept delivering the rest. It needs a human/PM to re-scope or unblock it.
    key: "deferred",
    label: "Deferred",
    meaning: "Auto-skipped — needs attention",
    icon: AlertTriangle,
    tone: "amber",
    emptyTitle: "Nothing deferred",
    emptyHint: "Items the autonomous sweep couldn't complete land here.",
  },
];

/** Item-status → badge severity (amber is reserved for review). */
export const ITEM_BADGE: Record<string, { label: string; severity: Severity | "neutral" }> = {
  todo: { label: "To do", severity: "neutral" },
  in_progress: { label: "In progress", severity: "neutral" },
  in_review: { label: "Needs review", severity: "amber" },
  done: { label: "Done", severity: "green" },
  deferred: { label: "Deferred", severity: "amber" },
};

/** Persisted runs launched from this item (exact item_id link; runs arrive
 *  newest-first from the API, order is preserved). */
export function runsForItem(runs: HistoryRun[], item: BacklogItem): HistoryRun[] {
  return runs.filter((r) => r.item_id === item.id);
}

/** An item is blocked while any dependency it declares isn't yet delivered
 *  (blocked_by is the server-derived set of unmet dependency ids). */
export function isBlocked(item: BacklogItem): boolean {
  return (item.blocked_by?.length ?? 0) > 0;
}

/** A soft lock (Quincy/operator hold): a normal run is refused, but the item
 *  can be unlocked or run early with an explicit override. */
export function isLocked(item: BacklogItem): boolean {
  return !!item.locked;
}

/** react-router location state used to hand a composer draft to the PM tab. */
export interface PmPrefillState {
  pmPrefill: string;
}

export function askPmPrefill(item: BacklogItem): string {
  return `Regarding the backlog item "${item.title}": `;
}

/** Request-edits handoff carries the full item context so the PM
 *  conversation starts grounded (empty sections omitted). */
export function requestEditsPrefill(item: BacklogItem): string {
  const parts = [`The backlog item "${item.title}" needs changes before I can approve it.`];
  if (item.description.trim()) parts.push(`Current description:\n${item.description.trim()}`);
  if (item.acceptance.trim()) parts.push(`Acceptance criteria:\n${item.acceptance.trim()}`);
  parts.push("Requested changes:\n");
  return parts.join("\n\n");
}

export const REPRIORITIZE_PREFILL =
  "Review the backlog priorities and suggest a better order or changes.";
