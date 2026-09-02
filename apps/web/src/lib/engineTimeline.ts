/* Pure derivation for the timeline strip: the run's moments in time order, each
   owned by a band agent so a dot click selects its panel. Detours (failed checks,
   send-backs) are marked; a live run ends in a `now` moment, a dead one in `stop`.
   Tested in engine-lib.test.ts. */

import { AGENT_META, currentAgent, NODE_AGENT, type AgentId, type EngineInputs } from "./engine";

export type MomentKind = "moment" | "human" | "detour" | "now" | "stop";

export interface TimelineMoment {
  ts: number;
  label: string;
  agent: AgentId;
  kind: MomentKind;
}

const BAD_TERMINAL = new Set(["incomplete", "error", "cancelled"]);

function updateMoment(node: string, u: Record<string, unknown>, testRun: number): {
  label: string;
  kind: MomentKind;
} | null {
  switch (node) {
    case "plan":
      return { label: "Planned", kind: "moment" };
    case "design":
      return { label: "Designed", kind: "moment" };
    case "author_tests":
      return { label: "Acceptance tests authored", kind: "moment" };
    case "capture":
      return { label: "Built", kind: "moment" };
    case "test": {
      const passed = u.tests_passed;
      if (passed === false) return { label: `Checks failed (run ${testRun})`, kind: "detour" };
      if (passed === true) return { label: `Checks green (run ${testRun})`, kind: "moment" };
      return null;
    }
    case "review": {
      const verdict = /VERDICT:\s*(\w+)/i.exec(String(u.review ?? ""))?.[1]?.toUpperCase();
      if (verdict && verdict !== "APPROVE" && verdict !== "APPROVED")
        return { label: "Review: sent back", kind: "detour" };
      return { label: "Review: approved", kind: "moment" };
    }
    case "critic": {
      const ov = u.outcome_verdict as { vetoed?: boolean } | null | undefined;
      if (ov && typeof ov === "object")
        return ov.vetoed
          ? { label: "Critic: vetoed", kind: "detour" }
          : { label: "Critic: no veto", kind: "moment" };
      return null;
    }
    case "deliver":
      return { label: "Delivered", kind: "moment" };
    default:
      return null;
  }
}

export function deriveTimeline(inputs: EngineInputs): TimelineMoment[] {
  const moments: TimelineMoment[] = [];
  let testRun = 0;
  for (const e of inputs.events) {
    const node = String(e.data?.node ?? e.node ?? "");
    if (e.type === "interrupt") {
      moments.push({ ts: e.ts, label: "Paused for you", agent: "you", kind: "human" });
      continue;
    }
    if (e.type !== "update") continue;
    if (node === "test") testRun += 1;
    const u = (e.data?.update ?? {}) as Record<string, unknown>;
    const m = updateMoment(node, u, testRun);
    if (m) moments.push({ ts: e.ts, agent: NODE_AGENT[node] ?? "quincy", ...m });
  }
  // Operator answers carry only coarse created_at stamps — fold them in when parseable.
  for (const a of inputs.detail?.approvals ?? []) {
    if (!a.created_at) continue;
    const ts = Date.parse(a.created_at);
    if (Number.isNaN(ts)) continue;
    moments.push({
      ts,
      label: a.approved ? "You approved" : "You sent it back",
      agent: "you",
      kind: a.approved ? "human" : "detour",
    });
  }
  moments.sort((a, b) => a.ts - b.ts);

  const last = moments[moments.length - 1];
  if (inputs.live) {
    const cur = currentAgent(inputs) ?? "quincy";
    moments.push({
      ts: (last?.ts ?? Date.now()) + 1,
      label: `now · ${AGENT_META[cur].name}`,
      agent: cur,
      kind: "now",
    });
  } else {
    const status = (inputs.detail?.status ?? "").toLowerCase();
    const bad =
      BAD_TERMINAL.has(status) || status.startsWith("not approved") || status === "error";
    if (bad && last) {
      moments.push({ ts: last.ts + 1, label: "Stopped", agent: last.agent, kind: "stop" });
    }
  }
  return moments;
}

/** Compact caption for the strip's right edge ("now · Rook reviewing" / "delivered ·
 *  sealed" / "stopped · honest park"). */
export function timelineCaption(inputs: EngineInputs): { text: string; tone: "live" | "ok" | "stop" } {
  if (inputs.live) {
    const cur = currentAgent(inputs) ?? "quincy";
    return { text: `now · ${AGENT_META[cur].name} ${AGENT_META[cur].role}`, tone: "live" };
  }
  const status = (inputs.detail?.status ?? "").toLowerCase();
  if (status === "approved" || status === "completed" || inputs.detail?.commit_sha)
    return {
      text: inputs.detail?.receipt_id ? "delivered · sealed" : "delivered",
      tone: "ok",
    };
  const reason = inputs.detail?.termination_reason;
  return { text: reason ? `stopped · ${reason}` : "stopped", tone: "stop" };
}
