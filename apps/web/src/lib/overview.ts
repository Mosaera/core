/* Pure derivations for the Project Overview dashboard. Every value traces to a
   real API field — no fabricated metrics. Unit-tested in overview-lib.test.ts. */

import type { ActiveRun, BacklogItem, HistoryRun, Project, ProjectMessage } from "../api/client";
import { OUTCOME_META, runOutcome } from "./validation";

export interface BacklogCounts {
  total: number;
  todo: number;
  inProgress: number;
  inReview: number;
  done: number;
}

export function backlogCounts(items: BacklogItem[]): BacklogCounts {
  const by = (s: string) => items.filter((i) => i.status === s).length;
  return {
    total: items.length,
    todo: by("todo"),
    inProgress: by("in_progress"),
    inReview: by("in_review"),
    done: by("done"),
  };
}

export type Phase = "Intake" | "Planning" | "Building" | "Review" | "Merge" | "Delivered";

// The intake/initialize phase: only the Start tab is shown until the backlog is
// built (status flips to active). `ready` = the intake conversation is open.
export const INITIALIZING_STATUSES = ["draft", "drafting", "ready"];
export function isInitializing(status: string): boolean {
  return INITIALIZING_STATUSES.includes(status);
}

export function derivePhase(project: Project, activeRun?: ActiveRun): Phase {
  // draft/drafting = cloning; ready = intake conversation open (still Intake).
  if (isInitializing(project.status)) return "Intake";
  if (project.status === "merged") return "Delivered";
  if (project.status === "in_review") return "Merge";
  // active
  const counts = backlogCounts(project.backlog ?? []);
  if (activeRun) return "Building";
  if (counts.total === 0) return "Planning";
  if (counts.inReview > 0 && counts.todo === 0 && counts.inProgress === 0) return "Review";
  return "Building";
}

/** Newest timestamp across the project's own record, runs, backlog and messages. */
export function lastActivityAt(project: Project, messages: ProjectMessage[] = []): Date | null {
  const stamps: (string | null | undefined)[] = [
    project.created_at,
    ...(project.runs ?? []).map((r) => r.created_at),
    ...(project.backlog ?? []).map((i) => i.created_at),
    ...messages.map((m) => m.created_at),
  ];
  const times = stamps
    .filter((s): s is string => Boolean(s))
    .map((s) => new Date(s).getTime())
    .filter((t) => !Number.isNaN(t));
  return times.length ? new Date(Math.max(...times)) : null;
}

export function timeAgo(date: Date | null, now: Date = new Date()): string {
  if (!date) return "—";
  const s = Math.max(0, Math.floor((now.getTime() - date.getTime()) / 1000));
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} hr ago`;
  const d = Math.floor(h / 24);
  return d === 1 ? "1 day ago" : `${d} days ago`;
}

export type Severity = "red" | "amber" | "green";

export interface AttentionItem {
  severity: Severity;
  /** Concise directive — a headline, not a log line. */
  text: string;
  /** The full underlying fact (raw error / task), for tooltips. */
  detail?: string;
  /** project section slug to route to, if any */
  to?: string;
  fact?: string;
}

function latestRun(project: Project): HistoryRun | undefined {
  return (project.runs ?? [])[0]; // runs arrive newest-first from the API
}

/** Honest one-liner for a run that needs attention (validation vocabulary,
 *  never "tests failed" for an unavailable/errored run). */
const ATTENTION_PHRASE: Record<string, string> = {
  errored: "errored",
  "validation-failed": "validation failed",
  "validation-unavailable": "validation was unavailable",
  "not-approved": "was not approved",
};

export function attentionItems(project: Project, mrState: string | null): AttentionItem[] {
  const out: AttentionItem[] = [];
  // Directives, not log lines: a budget pause reads as its consequence and routes to where
  // the cap is edited. Other project errors keep their raw text (no better headline exists).
  if (project.error) {
    const budget = /budget/i.test(project.error);
    out.push({
      // A configured cap doing its job is a PAUSE (amber), not a failure. True errors stay red.
      severity: budget ? "amber" : "red",
      text: budget ? "Monthly budget exceeded — autonomous mode paused" : project.error,
      detail: project.error,
      to: budget ? "settings" : undefined,
    });
  }
  const run = latestRun(project);
  if (run) {
    const outcome = runOutcome(run);
    const meta = OUTCOME_META[outcome];
    if (meta.attention) {
      out.push({
        severity: meta.severity,
        text: `Last run ${ATTENTION_PHRASE[outcome] ?? meta.label.toLowerCase()} — needs your look`,
        detail: run.task,
        to: "runs",
      });
    }
  }
  const counts = backlogCounts(project.backlog ?? []);
  if (counts.inReview > 0) {
    out.push({
      severity: "amber",
      text: `${counts.inReview} item${counts.inReview === 1 ? "" : "s"} waiting for review`,
      to: "backlog",
      fact: "in_review",
    });
  }
  if (project.mr_url && project.status === "in_review") {
    out.push({
      severity: "amber",
      text: `Merge request ${mrState ? `(${mrState}) ` : ""}awaiting review and merge`,
      to: "changes",
    });
  }
  return out;
}

export interface NextAction {
  title: string;
  reason: string;
  impact: string;
  cta: { label: string; kind: "route" | "external"; to: string } | null;
  /** Shared fact key with attentionItems — the strip and the next action can derive from the
   *  same project fact via different routes; the dedupe matches on this, not the destination. */
  fact?: string;
}

/** The PROJECT-level move, when there is one — intake, an open MR, or the post-merge next sprint.
 *  The item-level branches ("review item N", "look at the last run", "run the next item") moved
 *  into `lib/triage.ts` on 2026-08-22: they are per-item verbs, and this function could only ever
 *  name ONE of them however many kinds of stuck work existed. Returns null when the project's own
 *  lifecycle asks for nothing. */
export function lifecycleAction(project: Project): NextAction | null {
  const counts = backlogCounts(project.backlog ?? []);
  if (project.status === "draft" || project.status === "drafting") {
    return {
      title: "Setting up the project",
      reason: "Quincy is cloning the repository to get its bearings.",
      impact: "Once it's cloned you'll shape the project together in the Start chat.",
      cta: null,
    };
  }
  if (project.status === "ready") {
    return {
      title: "Shape the project with Quincy",
      reason: "The repo is cloned — tell Quincy what to build in the Start chat.",
      impact: "When you're ready, Build the backlog turns the conversation into work items.",
      cta: { label: "Open Start", kind: "route", to: "start" },
    };
  }
  if (project.status === "merged") {
    return {
      title: "Plan the next sprint with the PM",
      reason: "The merge request landed; delivered work is on the source branch.",
      impact: "Keeps momentum by turning the next objectives into backlog items.",
      cta: { label: "Open PM", kind: "route", to: "pm" },
    };
  }
  // Waiting-on-you outranks run-next: reviews and open MRs need the customer.
  if (project.mr_url && project.status === "in_review") {
    return {
      title: "Review and merge the open MR",
      reason: "An open merge request is carrying the project's accumulated changes.",
      impact: "Merging delivers the work and moves the project toward Done.",
      cta: { label: "Open merge request", kind: "external", to: project.mr_url },
    };
  }
  if (counts.total === 0) {
    return {
      title: "Building the backlog",
      reason: "Quincy is decomposing your intake conversation into work items.",
      impact: "The board fills in as items are created — no action needed.",
      cta: null,
    };
  }
  return null;
}

export type ActivityKind = "run" | "item" | "message" | "project";

export interface ActivityEvent {
  at: Date;
  text: string;
  kind: ActivityKind;
  /** amber marks attention-worthy events (failed/denied runs); neutral otherwise */
  tone: "neutral" | "amber";
}

export function activityFeed(
  project: Project,
  messages: ProjectMessage[] = [],
  limit = 8,
): ActivityEvent[] {
  const events: ActivityEvent[] = [];
  const push = (
    at: string | null | undefined,
    text: string,
    kind: ActivityKind,
    tone: "neutral" | "amber" = "neutral",
  ) => {
    if (!at) return;
    const d = new Date(at);
    if (!Number.isNaN(d.getTime())) events.push({ at: d, text, kind, tone });
  };
  for (const r of project.runs ?? []) {
    const label =
      r.status === "RUNNING"
        ? "Run started"
        : r.status === "APPROVED"
          ? "Run completed"
          : r.status === "NOT APPROVED"
            ? "Run needs attention"
            : r.status === "CANCELLED"
              ? "Run cancelled"
              : `Run ${r.status.toLowerCase()}`;
    const attention = OUTCOME_META[runOutcome(r)].attention;
    push(r.created_at, `${label}: ${r.task.slice(0, 70)}`, "run", attention ? "amber" : "neutral");
  }
  for (const i of project.backlog ?? []) {
    push(i.created_at, `Backlog item added: ${i.title.slice(0, 70)}`, "item");
  }
  for (const m of messages) {
    // Three roles, not two: a `note` row records a turn that did NOT complete, and the old
    // ternary's else-branch filed it under "Stakeholder message to the PM" — attributing an
    // engine failure to the operator on the project timeline.
    if (m.role === "note") {
      push(m.created_at, "A PM reply didn't complete", "message", "amber");
      continue;
    }
    push(m.created_at, m.role === "pm" ? "PM replied in chat" : "Stakeholder message to the PM", "message");
  }
  push(project.created_at, "Project created", "project");
  events.sort((a, b) => b.at.getTime() - a.at.getTime());
  return events.slice(0, limit);
}

/** Last PM-authored chat message, for the "Latest from the PM" excerpt. */
export function latestPmNote(messages: ProjectMessage[]): string | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "pm" && messages[i].content.trim()) return messages[i].content.trim();
  }
  return null;
}

export const STATUS_BADGE: Record<string, { label: string; severity: Severity | "neutral" }> = {
  draft: { label: "Intake", severity: "neutral" },
  drafting: { label: "Intake", severity: "neutral" },
  ready: { label: "Intake", severity: "neutral" },
  active: { label: "Active", severity: "green" },
  in_review: { label: "In review", severity: "amber" },
  merged: { label: "Delivered", severity: "green" },
};
