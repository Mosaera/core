/* The audit-event vocabulary as human, attributable rows. The engine writes
   `audit_events` (run lifecycle, per-node steps, gate decisions, MR lifecycle);
   this turns each `{event, detail}` into an actor + sentence + tone for the
   project Activity log. Node steps reuse the workbench's actor personas
   (Quincy/Forge/Vera/Rook/Ledger/Drift) so attribution stays consistent. */

import { actorFor } from "../components/runs/runActors";

export type ActivitySeverity = "green" | "amber" | "red" | "muted";
export type ActivityGroup = "lifecycle" | "gate" | "mr";

export interface DescribedEvent {
  group: ActivityGroup;
  /** Persona/source, or "" when the sentence stands alone. */
  actor: string;
  text: string;
  severity: ActivitySeverity;
}

const RUN_EVENTS: Record<string, { text: string; severity: ActivitySeverity }> = {
  "run.started": { text: "Run started", severity: "muted" },
  "run.completed": { text: "Run completed", severity: "green" },
  "run.cancelled": { text: "Run cancelled", severity: "amber" },
  "run.timeout": { text: "Run timed out", severity: "red" },
  "run.error": { text: "Run errored", severity: "red" },
};

const GATE_EVENTS: Record<string, { text: string; severity: ActivitySeverity }> = {
  // detail varies (a tool like `write_file`, or `deliver`), so the wording stays
  // generic and appends it — never assumes it was a delivery.
  "auto-approved": { text: "auto-approved", severity: "green" },
  "auto-denied": { text: "auto-denied", severity: "amber" },
  "auto-park": { text: "parked the run for review", severity: "amber" },
  interrupt: { text: "paused for human approval", severity: "amber" },
};

/* The ESCALATE arm's own vocabulary. Without these rows `escalate-arm.suppressed` fell to the
   verbatim fallback below — group `lifecycle`, no actor, severity `muted` — i.e. the lowest-emphasis
   row in the same bucket as every routine node step. A withheld question rendered as noise, which
   made the North Star's `Unsuppressible Ask` ("recorded and visible") false in its second half. */
const ESCALATE_EVENTS: Record<string, { text: string; severity: ActivitySeverity }> = {
  "escalate-arm.suppressed": { text: "withheld a question from you", severity: "amber" },
  "escalate-arm.asked": { text: "raised a question on the item", severity: "amber" },
  // The write THREW: the arm meant to ask and the operator got nothing. Red at least as loud as a
  // withheld one — this was the same muted-fallback defect, one event over (red team R3).
  "escalate-arm.ask-failed": { text: "could not raise its question", severity: "red" },
  // Not a suppression: you already answered, and it declined to ask again. Muted on purpose —
  // asking once is a question, asking every sweep is pressure toward lowering the bar.
  "escalate-arm.affirmed": { text: "did not re-ask — you already answered", severity: "muted" },
};

const MR_EVENTS: Record<string, { text: string; severity: ActivitySeverity }> = {
  "mr.opened": { text: "opened a merge request", severity: "green" },
  "mr.failed": { text: "could not open a merge request", severity: "red" },
};

/** Map one persisted audit event to a rendered row. Unknown events are shown
 *  verbatim rather than dropped — an audit log stays honest about what it holds. */
export function describeEvent(event: string, detail: string): DescribedEvent {
  if (event === "node") {
    // detail = the graph node name (plan/implement/test/review/gate/...).
    const a = actorFor(detail);
    return { group: "lifecycle", actor: a.actor, text: a.done, severity: "muted" };
  }
  const run = RUN_EVENTS[event];
  if (run) {
    return {
      group: "lifecycle",
      actor: "",
      text: detail ? `${run.text} — ${detail}` : run.text,
      severity: run.severity,
    };
  }
  const gate = GATE_EVENTS[event];
  if (gate) {
    return {
      group: "gate",
      actor: "Justice",
      text: detail ? `${gate.text} (${detail})` : gate.text,
      severity: gate.severity,
    };
  }
  const esc = ESCALATE_EVENTS[event];
  if (esc) {
    return {
      group: "gate",
      actor: "Justice",
      text: detail ? `${esc.text} — ${detail}` : esc.text,
      severity: esc.severity,
    };
  }
  const mr = MR_EVENTS[event];
  if (mr) {
    return {
      group: "mr",
      actor: "Mercury",
      text: detail ? `${mr.text}: ${detail}` : mr.text,
      severity: mr.severity,
    };
  }
  return {
    group: "lifecycle",
    actor: "",
    text: detail ? `${event}: ${detail}` : event,
    severity: "muted",
  };
}

export const ACTIVITY_FILTERS: { id: "all" | ActivityGroup; label: string }[] = [
  { id: "all", label: "All" },
  { id: "lifecycle", label: "Lifecycle" },
  { id: "gate", label: "Gate" },
  { id: "mr", label: "Merge" },
];

/** A one-word outcome for a run, from its events — so a collapsed run group
 *  still says what happened. Terminal facts win over intermediate ones (a run
 *  that parked then completed reads as "completed"). */
export function runHeadline(events: { event: string }[]): {
  label: string;
  severity: ActivitySeverity;
} {
  const has = (e: string) => events.some((x) => x.event === e);
  if (has("run.error")) return { label: "errored", severity: "red" };
  if (has("run.timeout")) return { label: "timed out", severity: "red" };
  if (has("run.cancelled")) return { label: "cancelled", severity: "amber" };
  if (has("run.completed")) return { label: "completed", severity: "green" };
  if (has("auto-park") || has("interrupt")) return { label: "parked", severity: "amber" };
  return { label: "in progress", severity: "muted" };
}
