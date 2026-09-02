/* Pure derivation for the engine band (#63 engine-showcase composition): the
   7-agent roster, per-agent status/captions, and the edge state machine —
   exactly one `current` edge while live; a loop edge is current while being
   traversed, quiet once passed, `dead` if the run terminated on it. No React.
   Tested in engine-lib.test.ts. */

import type { RunControls, RunDetail, TranscriptEvent } from "../api/client";

export type AgentId =
  | "quincy"
  | "architect"
  | "proctor"
  | "forge"
  | "vera"
  | "rook"
  | "critic"
  | "you"
  | "drift";

/** `disabled` = the control is switched OFF for this run, so it will never run. Distinct from
 *  `pending` ("hasn't got there yet"), which is the distinction the roster could not previously
 *  make: a disabled control was simply absent, indistinguishable from one still to come. */
export type AgentStatus = "done" | "current" | "dead" | "pending" | "disabled";

export interface AgentState {
  id: AgentId;
  name: string;
  role: string;
  status: AgentStatus;
  /** One honest line under the name — what happened / is happening / why nothing yet. */
  caption: string;
}

export type EdgeState = "current" | "traversed" | "unreached" | "dead";

export interface EngineEdge {
  from: AgentId;
  to: AgentId;
  kind: "forward" | "back";
  state: EdgeState;
  /** Loop traversals (back edges only). */
  count?: number;
  /** Badge text for back edges ("tests failed ×2"). */
  label?: string;
}

/** Live signals from the stream; null/undefined = a sealed (durable-only) run. */
export interface EngineLive {
  status: string;
  phase: string;
  /** A gate interrupt is open — the run is parked on the human. */
  gateOpen: boolean;
}

export interface EngineInputs {
  events: TranscriptEvent[];
  detail?: RunDetail | null;
  live?: EngineLive | null;
  /** The control set the run STARTED with (run snapshot `controls`). Absent on older rows —
   *  fall back to the observed-event behaviour rather than claiming a control was off. */
  controls?: RunControls | null;
}

/** Graph node → band agent. Hygiene and scan fold into Vera ("the checks");
 *  the coder-owned loop nodes fold into Forge; gate + operator are You. */
export const NODE_AGENT: Record<string, AgentId> = {
  plan: "quincy",
  design: "architect",
  supervise: "quincy",
  author_tests: "proctor",
  implement: "forge",
  capture: "forge",
  fix: "forge",
  hygiene_fix: "forge",
  review_fix: "forge",
  quality_revise: "forge",
  reason: "forge",
  test: "vera",
  hygiene: "vera",
  scan: "vera",
  review: "rook",
  critic: "critic",
  gate: "you",
  deliver: "drift",
};

export const AGENT_META: Record<AgentId, { name: string; role: string }> = {
  quincy: { name: "The Chart-Maker", role: "plans the work" },
  architect: { name: "The Architect", role: "designs the approach" },
  proctor: { name: "The Assayer", role: "authors the acceptance tests" },
  forge: { name: "The Smith", role: "writes the code" },
  vera: { name: "The Engine", role: "runs the deterministic checks" },
  rook: { name: "The Tribune", role: "reviews independently" },
  critic: { name: "The Critic", role: "held-out veto" },
  you: { name: "Justice", role: "final authority — you" },
  drift: { name: "Mercury", role: "delivers" },
};

const BAD_TERMINAL = new Set(["incomplete", "error", "cancelled"]);
/** Loop nodes whose completion means the run is heading BACK to Forge. */
const LOOP_SOURCE: Record<string, AgentId> = {
  fix: "vera",
  hygiene_fix: "vera",
  review_fix: "rook",
  quality_revise: "rook",
};

interface Tally {
  updates: Map<string, { count: number; lastTs: number }>;
  lastUpdateNode: string | null;
  testRuns: number;
  testFails: number;
  lastTestPassed: boolean | null;
  hygieneFixes: number;
  reviewSendBacks: number; // review_fix + quality_revise completions
  interrupts: number;
}

function tally(events: TranscriptEvent[]): Tally {
  const t: Tally = {
    updates: new Map(),
    lastUpdateNode: null,
    testRuns: 0,
    testFails: 0,
    lastTestPassed: null,
    hygieneFixes: 0,
    reviewSendBacks: 0,
    interrupts: 0,
  };
  for (const e of events) {
    if (e.type === "interrupt") t.interrupts += 1;
    if (e.type !== "update") continue;
    const node = String(e.data?.node ?? e.node ?? "");
    if (!node) continue;
    const prev = t.updates.get(node) ?? { count: 0, lastTs: 0 };
    t.updates.set(node, { count: prev.count + 1, lastTs: e.ts });
    t.lastUpdateNode = node;
    const u = (e.data?.update ?? {}) as Record<string, unknown>;
    if (node === "test") {
      t.testRuns += 1;
      const passed = u.tests_passed;
      if (passed === false) t.testFails += 1;
      if (typeof passed === "boolean") t.lastTestPassed = passed;
    }
    if (node === "hygiene_fix") t.hygieneFixes += 1;
    if (node === "review_fix" || node === "quality_revise") t.reviewSendBacks += 1;
  }
  return t;
}

/** The run's FULL cast, known from the start.
 *
 *  This used to add Proctor and Critic only once their node had run — the roster grew as work
 *  landed, so a role that was switched off looked identical to one that simply hadn't been
 *  reached, and neither was on screen. When `controls` is present (the run snapshot records the
 *  set it started with) an optional role is always listed, and `agentStatus` marks it `disabled`
 *  when its knob is off.
 *
 *  Older rows carry no `controls`; those keep the observed-event behaviour, because claiming a
 *  control was "off" from its silence would be the same guess in the other direction. */
export function engineRoster(inputs: EngineInputs): AgentId[] {
  const t = tally(inputs.events);
  const decided = new Set((inputs.detail?.decisions ?? []).map((d) => d.kind));
  const c = inputs.controls;
  const ran = (node: string, kind?: string) =>
    t.updates.has(node) || inputs.live?.phase === node || (kind ? decided.has(kind) : false);

  const roster: AgentId[] = ["quincy", "architect"];
  if (c ? c.tester_enabled !== undefined || ran("author_tests") : ran("author_tests"))
    roster.push("proctor");
  roster.push("forge", "vera", "rook");
  if (c ? c.critic_enabled !== undefined || ran("critic", "critic") : ran("critic", "critic"))
    roster.push("critic");
  roster.push("you", "drift");
  return roster;
}

/** Is this agent's control switched OFF for this run? Only ever true for the optional roles, and
 *  only when the run actually recorded its control set. A role that ran is never "disabled",
 *  whatever the knob says now — the evidence of it running outranks the flag. */
export function agentDisabled(id: AgentId, inputs: EngineInputs): boolean {
  const c = inputs.controls;
  if (!c) return false;
  const t = tally(inputs.events);
  const decided = new Set((inputs.detail?.decisions ?? []).map((d) => d.kind));
  if (id === "proctor")
    return c.tester_enabled === false && !t.updates.has("author_tests");
  if (id === "critic")
    return c.critic_enabled === false && !t.updates.has("critic") && !decided.has("critic");
  return false;
}

/** The agent the run is on right now (live only): the stream phase, falling back
 *  to the newest event's node. One-tick lag is accepted — there is no node-start
 *  event, so "current" trails reality by at most one emission. */
export function currentAgent(inputs: EngineInputs): AgentId | null {
  if (!inputs.live) return null;
  // A PARKED run (delivery/budget gate) is waiting on the PERSON, whatever the last
  // node phase says. Mid-run WRITE approvals must NOT set `gateOpen` — the stage
  // stays with the asking agent (the workbench passes gateOpen only for real parks).
  if (inputs.live.gateOpen) return "you";
  // Two signals, two lags: `update` events are COMPLETION records (they name the node
  // just finished), while `thought`/`activity` events come from the node actually
  // running. So a running-node signal newer than the last completion is the truth
  // ("design is working" while the coder asked to write — measured live 2026-08-13);
  // otherwise the phase (which tracks completions) is the best available.
  for (let i = inputs.events.length - 1; i >= 0; i -= 1) {
    const e = inputs.events[i];
    const agent = NODE_AGENT[String(e.data?.node ?? e.node ?? "")];
    if (!agent) continue;
    if (e.type === "thought" || e.type === "activity") return agent;
    if (e.type === "update") break; // completions from here back — phase leads
  }
  const byPhase = NODE_AGENT[inputs.live.phase];
  if (byPhase) return byPhase;
  for (let i = inputs.events.length - 1; i >= 0; i -= 1) {
    const node = String(inputs.events[i].data?.node ?? inputs.events[i].node ?? "");
    const agent = NODE_AGENT[node];
    if (agent) return agent;
  }
  return "quincy";
}

/** Where a dead run died: the agent owning the newest event (sealed, bad status). */
function deathAgent(inputs: EngineInputs): AgentId | null {
  const status = (inputs.detail?.status ?? "").toLowerCase();
  const liveStatus = inputs.live?.status ?? "";
  const bad =
    BAD_TERMINAL.has(liveStatus) ||
    status === "incomplete" ||
    status === "error" ||
    status === "cancelled" ||
    status.startsWith("not approved");
  if (!bad) return null;
  for (let i = inputs.events.length - 1; i >= 0; i -= 1) {
    const node = String(inputs.events[i].data?.node ?? inputs.events[i].node ?? "");
    const agent = NODE_AGENT[node];
    if (agent) return agent;
  }
  return "quincy";
}

/** Did the run actually reach the DELIVERY gate? A mid-run write approval is a
 *  human decision but not a gate visit — an `interrupt` event alone proves only
 *  that someone was asked something, not that the checkpoint was reached. */
function gateReached(t: Tally, detail: RunDetail | undefined): boolean {
  if (t.updates.has("gate")) return true;
  return (detail?.approvals ?? []).some((a) => (a.action || "deliver") === "deliver");
}

const clock = (ts: number): string =>
  new Date(ts).toLocaleTimeString(undefined, { hour12: false, hour: "2-digit", minute: "2-digit" });

function captionFor(
  id: AgentId,
  status: AgentStatus,
  t: Tally,
  inputs: EngineInputs,
): string {
  const detail = inputs.detail;
  const plural = (n: number, s: string) => `${n} ${s}${n === 1 ? "" : "s"}`;
  // Name the knob, so "why is nothing here?" is answerable from the screen.
  if (status === "disabled") {
    if (id === "proctor") return "off — tester_enabled";
    if (id === "critic") return "off — critic_enabled";
    return "off";
  }
  switch (id) {
    case "quincy": {
      if (status === "current") return "planning…";
      const u = t.updates.get("plan");
      if (u) return `planned · ${clock(u.lastTs)}`;
      return status === "pending" ? "not started" : "planned";
    }
    case "architect": {
      if (status === "current") return "designing…";
      const u = t.updates.get("design");
      if (u) return `designed · ${clock(u.lastTs)}`;
      return status === "pending" ? "waits for the plan" : "designed";
    }
    case "proctor": {
      if (status === "current") return "authoring tests…";
      return t.updates.has("author_tests") ? "acceptance tests authored" : "waits for the design";
    }
    case "forge": {
      if (status === "current") return "building…";
      if (status === "dead") return "stopped mid-build";
      const builds = 1 + t.testFails + t.hygieneFixes + t.reviewSendBacks;
      if (!t.updates.has("test") && !t.updates.has("capture") && status === "pending")
        return "waits for the plan";
      return plural(builds, "build");
    }
    case "vera": {
      if (status === "current") return "running the checks…";
      if (t.lastTestPassed === true) return `green on run ${t.testRuns}`;
      if (t.lastTestPassed === false)
        return status === "dead" ? `red on run ${t.testRuns}` : `red on run ${t.testRuns}`;
      return "waits for a build";
    }
    case "rook": {
      if (status === "current") return "reviewing…";
      if (t.reviewSendBacks > 0 && !t.updates.has("review")) return "waits for green checks";
      if (t.updates.has("review"))
        return t.reviewSendBacks > 0 ? `approved after ×${t.reviewSendBacks}` : "reviewed";
      return "waits for green checks";
    }
    case "critic": {
      if (status === "current") return "judging the evidence…";
      const ov = lastCriticVerdict(inputs);
      if (ov) return ov.vetoed ? "vetoed" : "no veto";
      return "waits for the Tribune";
    }
    case "you": {
      if (inputs.live?.gateOpen) return "needs you now";
      const answers = (detail?.approvals ?? []).length;
      if (gateReached(t, detail ?? undefined)) return plural(answers || 1, "decision");
      // Write approvals are real decisions, but they are NOT the delivery gate —
      // saying "gate evaluated" here would claim a checkpoint that never happened.
      if (answers > 0) return `${plural(answers, "write approval")} · gate not reached`;
      return "gate not reached";
    }
    case "drift": {
      if (status === "current") return "delivering…";
      if (detail?.receipt_id) return "sealed";
      if (t.updates.has("deliver") || detail?.commit_sha) return "delivered";
      return "nothing delivered";
    }
  }
}

function lastCriticVerdict(inputs: EngineInputs): { vetoed: boolean } | null {
  for (let i = inputs.events.length - 1; i >= 0; i -= 1) {
    const e = inputs.events[i];
    if (e.type !== "update") continue;
    if (String(e.data?.node ?? e.node ?? "") !== "critic") continue;
    const ov = (e.data?.update as Record<string, unknown> | undefined)?.outcome_verdict as
      | { vetoed?: boolean }
      | null
      | undefined;
    if (ov && typeof ov === "object") return { vetoed: ov.vetoed === true };
    return null;
  }
  return null;
}

/** First/last event timestamps for an agent's own nodes — the span it worked. */
export function agentSpan(inputs: EngineInputs, id: AgentId): { first: number; last: number } | null {
  let first: number | null = null;
  let last: number | null = null;
  for (const e of inputs.events) {
    const node = String(e.data?.node ?? e.node ?? "");
    if (NODE_AGENT[node] !== id) continue;
    if (typeof e.ts !== "number" || e.ts <= 0) continue;
    if (first === null || e.ts < first) first = e.ts;
    if (last === null || e.ts > last) last = e.ts;
  }
  return first !== null && last !== null ? { first, last } : null;
}

/** Sealed default selection is You (the decision record); live follows the work. */
export function defaultSelection(inputs: EngineInputs): AgentId {
  return currentAgent(inputs) ?? "you";
}

export function deriveAgents(inputs: EngineInputs): AgentState[] {
  const roster = engineRoster(inputs);
  const t = tally(inputs.events);
  const cur = currentAgent(inputs);
  const dead = inputs.live ? null : deathAgent(inputs);
  const reached = new Set<AgentId>();
  for (const node of t.updates.keys()) {
    const a = NODE_AGENT[node];
    if (a) reached.add(a);
  }
  if (gateReached(t, inputs.detail ?? undefined)) reached.add("you");
  if (inputs.detail?.commit_sha) reached.add("drift");
  // Never show a done-tick for the agent the stream still reports current.
  return roster.map((id) => {
    let status: AgentStatus;
    if (cur === id) status = "current";
    else if (dead === id) status = "dead";
    else if (reached.has(id)) status = "done";
    // Checked AFTER done/current: evidence that a role ran outranks a knob that now reads off.
    else if (agentDisabled(id, inputs)) status = "disabled";
    else status = "pending";
    return { id, ...AGENT_META[id], status, caption: captionFor(id, status, t, inputs) };
  });
}

/** All edges with their deterministic states. Forward edges join adjacent roster
 *  agents; back edges exist only when their loop actually ran. */
export function deriveEdges(inputs: EngineInputs): EngineEdge[] {
  const roster = engineRoster(inputs);
  const t = tally(inputs.events);
  const cur = currentAgent(inputs);
  const dead = inputs.live ? null : deathAgent(inputs);
  const agents = deriveAgents(inputs);
  const statusOf = new Map(agents.map((a) => [a.id, a.status]));

  // Is the run currently (or terminally) ON a loop edge? True when the newest
  // update is a loop node — the run has left the source and not yet re-entered.
  const loopNow = t.lastUpdateNode ? LOOP_SOURCE[t.lastUpdateNode] : undefined;
  const focus = cur ?? dead; // the agent the run is on (live) or died on (sealed)
  const onLoop =
    loopNow !== undefined && (focus === "forge" || focus === "vera" || focus === "rook");

  const edges: EngineEdge[] = [];
  for (let i = 0; i < roster.length - 1; i += 1) {
    const from = roster[i];
    const to = roster[i + 1];
    let state: EdgeState;
    const toS = statusOf.get(to)!;
    if (focus === to && !onLoop && (cur !== null || dead !== null)) {
      state = dead === to ? "dead" : "current";
    } else if (toS !== "pending") {
      // An edge counts as crossed only when its TARGET was reached — a run that
      // died at Quincy never traversed the edge leaving Quincy.
      state = "traversed";
    } else {
      state = "unreached";
    }
    edges.push({ from, to, kind: "forward", state });
  }

  const back: { from: AgentId; count: number; label: string }[] = [];
  const testLoops = t.testFails + t.hygieneFixes;
  if (testLoops > 0)
    back.push({ from: "vera", count: testLoops, label: `checks failed ×${testLoops}` });
  if (t.reviewSendBacks > 0)
    back.push({
      from: "rook",
      count: t.reviewSendBacks,
      label: `changes requested ×${t.reviewSendBacks}`,
    });
  const denials = (inputs.detail?.approvals ?? []).filter((a) => !a.approved).length;
  if (denials > 0) {
    edges.push({
      from: "you",
      to: "quincy",
      kind: "back",
      state: "traversed",
      count: denials,
      label: `sent back by you ×${denials}`,
    });
  }
  for (const b of back) {
    let state: EdgeState = "traversed";
    if (onLoop && loopNow === b.from) state = dead !== null ? "dead" : "current";
    edges.push({ from: b.from, to: "forge", kind: "back", state, count: b.count, label: b.label });
  }
  return edges;
}
