import { describe, expect, it } from "vitest";

import type { RunDetail, TranscriptEvent } from "../api/client";
import {
  currentAgent,
  defaultSelection,
  deriveAgents,
  deriveEdges,
  engineRoster,
  type EngineInputs,
} from "../lib/engine";
import { deriveTimeline, timelineCaption } from "../lib/engineTimeline";

let seq = 0;
const upd = (node: string, update: Record<string, unknown> = {}, ts = (seq += 10)): TranscriptEvent => ({
  seq: (seq += 1),
  type: "update",
  node,
  ts,
  data: { node, update },
});
const interrupt = (ts = (seq += 10)): TranscriptEvent => ({
  seq: (seq += 1),
  type: "interrupt",
  node: null,
  ts,
  data: {},
});

const detail = (over: Partial<RunDetail> = {}): RunDetail =>
  ({
    id: "r1",
    task: "make the failing test pass",
    status: "APPROVED",
    tests_passed: true,
    iterations: 1,
    commit_sha: "",
    source: "",
    branch: "run/r1",
    project_id: null,
    item_id: null,
    created_at: null,
    decisions: [],
    test_results: [],
    repo_changes: [],
    approvals: [],
    ...over,
  }) as RunDetail;

/** A clean delivered run: plan → design → build → green test → review approve → gate → deliver. */
const CLEAN: TranscriptEvent[] = [
  upd("plan", { plan: "1. do X" }),
  upd("design", { design: "one seam" }),
  upd("capture", {}),
  upd("test", { tests_passed: true }),
  upd("review", { review: "VERDICT: APPROVE" }),
  interrupt(),
  upd("gate", { approved: true }),
  upd("deliver", {}),
];

/** A loop run: two failed test runs (fix loop) and one review send-back. */
const LOOPY: TranscriptEvent[] = [
  upd("plan", { plan: "1. do X" }),
  upd("capture", {}),
  upd("test", { tests_passed: false }),
  upd("fix", { iteration: 2 }),
  upd("capture", {}),
  upd("test", { tests_passed: false }),
  upd("fix", { iteration: 3 }),
  upd("capture", {}),
  upd("test", { tests_passed: true }),
  upd("review", { review: "VERDICT: REQUEST_CHANGES" }),
  upd("review_fix", { review_revises: 1 }),
  upd("capture", {}),
  upd("test", { tests_passed: true }),
  upd("review", { review: "VERDICT: APPROVE" }),
];

describe("engineRoster — conditional agents", () => {
  it("Proctor and Critic appear only when their node actually ran", () => {
    expect(engineRoster({ events: CLEAN })).toEqual([
      "quincy", "architect", "forge", "vera", "rook", "you", "drift",
    ]);
    const withBoth = [...CLEAN, upd("author_tests", { authored_tests: ["t"] }), upd("critic", { outcome_verdict: null })];
    expect(engineRoster({ events: withBoth })).toEqual([
      "quincy", "architect", "proctor", "forge", "vera", "rook", "critic", "you", "drift",
    ]);
  });

  it("a durable critic decision proves the critic ran (sealed run, no events)", () => {
    const d = detail({ decisions: [{ kind: "critic", content: "{}", created_at: null }] });
    expect(engineRoster({ events: [], detail: d })).toContain("critic");
  });
});

describe("deriveAgents — status honesty", () => {
  it("live: the streamed phase is current, never done", () => {
    const inputs: EngineInputs = {
      events: CLEAN.slice(0, 5),
      live: { status: "running", phase: "review", gateOpen: false },
    };
    const agents = deriveAgents(inputs);
    expect(agents.find((a) => a.id === "rook")?.status).toBe("current");
    expect(agents.find((a) => a.id === "vera")?.status).toBe("done");
    expect(agents.find((a) => a.id === "drift")?.status).toBe("pending");
    expect(agents.find((a) => a.id === "drift")?.caption).toBe("nothing delivered");
  });

  it("sealed dead run: the agent owning the newest event is dead, downstream stays pending", () => {
    const events = [upd("plan", { plan: "p" }), upd("capture", {}), upd("test", { tests_passed: false })];
    const agents = deriveAgents({ events, detail: detail({ status: "INCOMPLETE" }) });
    expect(agents.find((a) => a.id === "vera")?.status).toBe("dead");
    expect(agents.find((a) => a.id === "rook")?.status).toBe("pending");
    expect(agents.find((a) => a.id === "you")?.caption).toBe("gate not reached");
  });

  it("sealed delivered run: everything reached is done, You counts decisions", () => {
    const d = detail({
      commit_sha: "abc12345",
      receipt_id: "sealed01",
      approvals: [{ action: "deliver", approved: true, feedback: "", created_at: null }],
    });
    const agents = deriveAgents({ events: CLEAN, detail: d });
    expect(agents.every((a) => a.status === "done")).toBe(true);
    expect(agents.find((a) => a.id === "you")?.caption).toBe("1 decision");
    expect(agents.find((a) => a.id === "drift")?.caption).toBe("sealed");
  });

  it("a live open gate reads needs-you", () => {
    const agents = deriveAgents({
      events: [...CLEAN.slice(0, 5), interrupt()],
      live: { status: "awaiting_approval", phase: "gate", gateOpen: true },
    });
    expect(agents.find((a) => a.id === "you")?.status).toBe("current");
    expect(agents.find((a) => a.id === "you")?.caption).toBe("needs you now");
  });
});

describe("deriveEdges — the edge state machine", () => {
  it("live mid-run: exactly one current edge, the one entering the current agent", () => {
    const edges = deriveEdges({
      events: CLEAN.slice(0, 5),
      live: { status: "running", phase: "review", gateOpen: false },
    });
    const current = edges.filter((e) => e.state === "current");
    expect(current).toHaveLength(1);
    expect(current[0]).toMatchObject({ from: "vera", to: "rook", kind: "forward" });
    expect(edges.find((e) => e.to === "drift")?.state).toBe("unreached");
  });

  it("live in the fix loop: the back edge is the current one, forward edges stay quiet", () => {
    const events = LOOPY.slice(0, 4); // ...test failed, fix completed → run is heading back
    const edges = deriveEdges({ events, live: { status: "running", phase: "implement", gateOpen: false } });
    const current = edges.filter((e) => e.state === "current");
    expect(current).toHaveLength(1);
    expect(current[0]).toMatchObject({ from: "vera", to: "forge", kind: "back" });
  });

  it("sealed: loop edges lose focus (traversed) and carry their counts", () => {
    const edges = deriveEdges({ events: LOOPY, detail: detail({ status: "APPROVED" }) });
    const back = edges.filter((e) => e.kind === "back");
    expect(back).toHaveLength(2);
    expect(back.find((e) => e.from === "vera")).toMatchObject({
      state: "traversed", count: 2, label: "checks failed ×2",
    });
    expect(back.find((e) => e.from === "rook")).toMatchObject({
      state: "traversed", count: 1, label: "changes requested ×1",
    });
    expect(edges.filter((e) => e.state === "current")).toHaveLength(0);
  });

  it("parked in the loop: the back edge is dead, not current, not traversed", () => {
    const events = LOOPY.slice(0, 4); // died right after a fix attempt
    const edges = deriveEdges({ events, detail: detail({ status: "INCOMPLETE" }) });
    expect(edges.find((e) => e.kind === "back")?.state).toBe("dead");
  });

  it("operator send-backs draw the You→Quincy return with a count", () => {
    const d = detail({
      approvals: [
        { action: "deliver", approved: false, feedback: "tighten it", created_at: null },
        { action: "deliver", approved: true, feedback: "", created_at: null },
      ],
    });
    const edges = deriveEdges({ events: CLEAN, detail: d });
    expect(edges.find((e) => e.from === "you" && e.kind === "back")).toMatchObject({
      to: "quincy", count: 1, label: "sent back by you ×1",
    });
  });
});

describe("selection defaults", () => {
  it("live follows the work; sealed defaults to You", () => {
    expect(
      defaultSelection({ events: CLEAN.slice(0, 4), live: { status: "running", phase: "review", gateOpen: false } }),
    ).toBe("rook");
    expect(defaultSelection({ events: CLEAN, detail: detail() })).toBe("you");
  });

  it("currentAgent is null when sealed (no live state)", () => {
    expect(currentAgent({ events: CLEAN, detail: detail() })).toBeNull();
  });
});

describe("deriveTimeline — honest moments", () => {
  it("a loopy run records detours, keeps time order, and ends where it ended", () => {
    const moments = deriveTimeline({ events: LOOPY, detail: detail({ status: "APPROVED", commit_sha: "abc" }) });
    const labels = moments.map((m) => m.label);
    expect(labels).toContain("Checks failed (run 1)");
    expect(labels).toContain("Checks failed (run 2)");
    expect(labels).toContain("Review: sent back");
    expect(labels).toContain("Review: approved");
    expect(moments.every((m, i) => i === 0 || moments[i - 1].ts <= m.ts)).toBe(true);
    expect(moments.filter((m) => m.kind === "stop")).toHaveLength(0);
  });

  it("live runs end in a now moment owned by the current agent", () => {
    const moments = deriveTimeline({
      events: CLEAN.slice(0, 4),
      live: { status: "running", phase: "review", gateOpen: false },
    });
    const last = moments[moments.length - 1];
    expect(last.kind).toBe("now");
    expect(last.agent).toBe("rook");
  });

  it("dead runs end in a stop moment; the caption never says delivered", () => {
    const inputs: EngineInputs = {
      events: [upd("plan", { plan: "p" }), upd("test", { tests_passed: false })],
      detail: detail({ status: "INCOMPLETE", termination_reason: "no_progress" }),
    };
    const moments = deriveTimeline(inputs);
    expect(moments[moments.length - 1].kind).toBe("stop");
    const cap = timelineCaption(inputs);
    expect(cap.tone).toBe("stop");
    expect(cap.text).toContain("no_progress");
    expect(cap.text.toLowerCase()).not.toContain("deliver");
  });

  it("a sealed receipt reads delivered · sealed", () => {
    const cap = timelineCaption({
      events: CLEAN,
      detail: detail({ commit_sha: "abc", receipt_id: "r" }),
    });
    expect(cap).toEqual({ text: "delivered · sealed", tone: "ok" });
  });
});

describe("edges are crossed only when their target was reached", () => {
  it("a run that died at the first agent never traversed the edge leaving it", () => {
    const events = [upd("plan", { plan: "p" })];
    const edges = deriveEdges({ events, detail: detail({ status: "ERROR", commit_sha: "" }) });
    // The Chart-Maker is dead; nothing downstream started — no wire was crossed.
    expect(edges.find((e) => e.from === "quincy" && e.to === "architect")?.state).toBe("unreached");
    expect(edges.every((e) => e.state !== "traversed")).toBe(true);
  });
});

describe("a write approval is not the delivery gate", () => {
  const askedToWrite: TranscriptEvent[] = [
    upd("plan", { plan: "p" }),
    upd("design", { design: "d" }),
    interrupt(), // an edit_file tool approval — the human was asked, mid-run
  ];

  it("an open write approval never marks the gate as reached", () => {
    const inputs: EngineInputs = {
      events: askedToWrite,
      live: { status: "awaiting_approval", phase: "design", gateOpen: false },
    };
    const you = deriveAgents(inputs).find((a) => a.id === "you")!;
    expect(you.status).toBe("pending");
    expect(you.caption).toBe("gate not reached");
    // ...so the wire into You is uncrossed, and Drift stays untouched.
    const edges = deriveEdges(inputs);
    expect(edges.find((e) => e.to === "you")?.state).toBe("unreached");
  });

  it("answered write approvals are counted as decisions, but still not a gate visit", () => {
    const d = detail({
      status: "RUNNING",
      approvals: [{ action: "edit_file", approved: true, feedback: "", created_at: null }],
    });
    const you = deriveAgents({ events: askedToWrite, detail: d, live: { status: "running", phase: "implement", gateOpen: false } })
      .find((a) => a.id === "you")!;
    expect(you.status).toBe("pending");
    expect(you.caption).toBe("1 write approval · gate not reached");
  });

  it("a deliver answer (or a gate node) does mark it reached", () => {
    const d = detail({
      approvals: [
        { action: "edit_file", approved: true, feedback: "", created_at: null },
        { action: "deliver", approved: true, feedback: "", created_at: null },
      ],
    });
    const you = deriveAgents({ events: askedToWrite, detail: d }).find((a) => a.id === "you")!;
    expect(you.status).toBe("done");
    expect(you.caption).toBe("2 decisions");
  });
});

describe("a parked run is waiting on the person, not the last node", () => {
  const parked: EngineInputs = {
    events: CLEAN.slice(0, 5), // ...through the review update
    // The snapshot phase lags at `review` while the gate interrupt is already open.
    live: { status: "awaiting_approval", phase: "review", gateOpen: true },
  };

  it("You is current — Rook is done, not still working", () => {
    expect(currentAgent(parked)).toBe("you");
    const agents = deriveAgents(parked);
    expect(agents.find((a) => a.id === "you")).toMatchObject({
      status: "current",
      caption: "needs you now",
    });
    expect(agents.find((a) => a.id === "rook")?.status).toBe("done");
  });

  it("the animated edge points AT you, and the panel opens on your decision", () => {
    const current = deriveEdges(parked).filter((e) => e.state === "current");
    expect(current).toHaveLength(1);
    expect(current[0]).toMatchObject({ to: "you", kind: "forward" });
    expect(defaultSelection(parked)).toBe("you");
  });
});

/* The roster used to GROW as work landed: Proctor and Critic were pushed only once their node had
   run, so a role switched off looked identical to one not yet reached, and neither was on screen.
   `controls` (the set the run started with) makes the full cast knowable at t=0.
   Live evidence, 2026-08-06: critic_enabled sat at its highest proven liveness rung and OFF on the
   production instance, and nothing said so. */
describe("the roster is the run's full cast, known from the start", () => {
  const controls = (over: Partial<EngineInputs["controls"]> = {}) => ({
    tester_enabled: true,
    critic_enabled: true,
    ...over,
  });

  it("lists Proctor and Critic before either has run", () => {
    const roster = engineRoster({ events: [upd("plan", { plan: "p" })], controls: controls() });
    expect(roster).toContain("proctor");
    expect(roster).toContain("critic");
  });

  it("marks a switched-off role `disabled`, not absent — and names the knob", () => {
    const agents = deriveAgents({
      events: [upd("plan", { plan: "p" })],
      controls: controls({ critic_enabled: false }),
    });
    const critic = agents.find((a) => a.id === "critic");
    expect(critic?.status).toBe("disabled");
    expect(critic?.caption).toBe("off — critic_enabled");
  });

  it("distinguishes disabled from not-yet-reached — the whole point", () => {
    const agents = deriveAgents({
      events: [upd("plan", { plan: "p" })],
      controls: controls({ critic_enabled: true }),
    });
    expect(agents.find((a) => a.id === "critic")?.status).toBe("pending");
  });

  it("evidence that a role RAN outranks a knob that now reads off", () => {
    const agents = deriveAgents({
      events: [upd("plan", { plan: "p" }), upd("author_tests", {})],
      controls: controls({ tester_enabled: false }),
    });
    expect(agents.find((a) => a.id === "proctor")?.status).toBe("done");
  });

  it("without `controls` (older rows) keeps the observed-event behaviour", () => {
    // Never claim a control was off from its silence — that is the same guess, inverted.
    expect(engineRoster({ events: [upd("plan", { plan: "p" })] })).not.toContain("critic");
    expect(engineRoster({ events: [upd("critic", {})] })).toContain("critic");
  });
});
