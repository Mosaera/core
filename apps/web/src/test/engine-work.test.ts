import { describe, expect, it } from "vitest";

import type { RunDetail, TranscriptEvent } from "../api/client";
import type { EngineInputs } from "../lib/engine";
import { deriveWork, planSteps } from "../lib/engineWork";

let seq = 0;
const ev = (
  type: TranscriptEvent["type"],
  node: string,
  data: Record<string, unknown>,
): TranscriptEvent => ({ seq: (seq += 1), type, node, ts: seq * 10, data: { node, ...data } });

const detail = (over: Partial<RunDetail> = {}): RunDetail =>
  ({
    id: "r1",
    task: "t",
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

describe("planSteps", () => {
  it("numbered or dashed plans become steps; freeform stays prose", () => {
    expect(planSteps("1. read the test\n2. fix the match\n- verify")).toHaveLength(3);
    expect(planSteps("just do the thing carefully")).toHaveLength(0);
  });
});

describe("deriveWork — per-agent honesty", () => {
  it("Quincy: plan steps + design from durable decisions", () => {
    const d = detail({
      decisions: [
        { kind: "plan", content: "1. do X\n2. do Y", created_at: null },
        { kind: "design", content: "one seam, no API change", created_at: null },
      ],
    });
    const w = deriveWork("quincy", { events: [], detail: d });
    expect(w.sections.map((s) => s.kind)).toContain("cot"); // the plan steps
    // The design belongs to the Architect now — its own seat, its own panel.
    const a = deriveWork("architect", { events: [], detail: d });
    const design = a.sections.find((s) => s.kind === "prose");
    expect(design?.kind === "prose" && design.text).toBe("one seam, no API change");
  });

  it("Forge: thoughts become chain-of-thought, activities become tool calls; live marks the tail active", () => {
    const events = [
      ev("thought", "implement", { text: "lower-case both sides" }),
      ev("activity", "implement", { kind: "file_written", detail: "notes.py", result: "42 chars" }),
      ev("activity", "implement", { kind: "file_read", detail: "tests/test_notes.py" }),
    ];
    const live = deriveWork("forge", {
      events,
      live: { status: "running", phase: "implement", gateOpen: false },
    });
    const cot = live.sections.find((s) => s.kind === "cot");
    expect(cot?.kind === "cot" && cot.items[cot.items.length - 1].state).toBe("active");
    const tools = live.sections.find((s) => s.kind === "tools");
    expect(tools?.kind === "tools" && tools.items[0]).toMatchObject({
      title: "wrote notes.py",
      settled: true,
    });
    // An activity with no result yet renders unsettled (still running).
    expect(tools?.kind === "tools" && tools.items[1].settled).toBe(false);
    // Sealed: nothing is "active".
    const sealed = deriveWork("forge", { events, detail: detail() });
    const sealedCot = sealed.sections.find((s) => s.kind === "cot");
    expect(sealedCot?.kind === "cot" && sealedCot.items.every((i) => i.state === "done")).toBe(true);
  });

  it("Vera: check runs count green and red honestly, terminal carries the output", () => {
    const events = [
      ev("update", "test", { update: { tests_passed: false, test_output: "1 failed" } }),
      ev("update", "test", { update: { tests_passed: true, test_output: "3 passed" } }),
    ];
    const w = deriveWork("vera", { events, detail: detail() });
    const tests = w.sections.find((s) => s.kind === "tests");
    expect(tests?.kind === "tests" && tests.passed).toBe(1);
    expect(tests?.kind === "tests" && tests.failed).toBe(1);
    expect(tests?.kind === "tests" && tests.rows[0].sub).toContain("sent back to Forge");
    const term = w.sections.find((s) => s.kind === "terminal");
    expect(term?.kind === "terminal" && term.text).toBe("3 passed");
  });

  it("You: decisions list with feedback; Drift: commit + seal + diff", () => {
    const d = detail({
      commit_sha: "abcd1234ef",
      receipt_id: "receipt01xyz",
      approvals: [
        { action: "deliver", approved: false, feedback: "tighten", created_at: null },
        { action: "deliver", approved: true, feedback: "", created_at: null },
      ],
      repo_changes: [{ diff: "--- a/x\n+++ b/x", commit_sha: "abcd1234ef", created_at: null }],
    });
    const you = deriveWork("you", { events: [], detail: d });
    const decisions = you.sections.find((s) => s.kind === "tools");
    expect(decisions?.kind === "tools" && decisions.items.map((i) => i.title)).toEqual([
      "deliver — sent back",
      "deliver — approved",
    ]);
    const drift = deriveWork("drift", { events: [], detail: d });
    const delivery = drift.sections.find((s) => s.kind === "tools");
    expect(delivery?.kind === "tools" && delivery.items[0].title).toBe("commit abcd1234");
    expect(delivery?.kind === "tools" && delivery.items[1].title).toBe("receipt sealed");
  });

  it("pending agents state plainly why there is nothing — never an invented placeholder", () => {
    const inputs: EngineInputs = {
      events: [],
      live: { status: "running", phase: "plan", gateOpen: false },
    };
    const critic = deriveWork("critic", inputs);
    expect(critic.sections).toEqual([
      { kind: "empty", reason: expect.stringContaining("judges only the final evidence") },
    ]);
    const drift = deriveWork("drift", inputs);
    expect(drift.sections[0]).toMatchObject({ kind: "empty" });
    const sealedDrift = deriveWork("drift", { events: [], detail: detail({ status: "INCOMPLETE" }) });
    expect(sealedDrift.sections[0]).toEqual({ kind: "empty", reason: "Nothing was delivered." });
  });

  it("Quincy carries the clarification exchange from ledger rows", () => {
    const rows = [
      {
        kind: "clarification" as const,
        ts: null,
        record: {
          claim_text: "search matches any locale",
          why_unbindable: "no test names the locale rules",
          proposals: [],
          status: "resolved",
          resolution: "unicode casefold",
          asked_at: "2026-08-04T02:18:00Z",
          resolved_at: "2026-08-04T02:19:00Z",
        },
        interactive: false,
      },
    ];
    const w = deriveWork("quincy", { events: [], detail: detail() }, rows as never);
    const q = w.sections.find((s) => s.kind === "prose" && s.title.startsWith("Question"));
    expect(q?.kind === "prose" && q.text).toContain("search matches any locale");
    expect(q?.kind === "prose" && q.text).toContain("→ unicode casefold");
  });
});
