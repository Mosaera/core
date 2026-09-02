import { describe, expect, it } from "vitest";

import type { BacklogItem, HistoryRun } from "../api/client";
import {
  TRIAGE_ORDER,
  needsYou,
  thrashing,
  triage,
  triageBuckets,
  type TriageVerb,
} from "../lib/triage";

function item(over: Partial<BacklogItem> = {}): BacklogItem {
  return {
    id: 1, project_id: "p1", title: "An item", description: "", acceptance: "",
    design: "", design_key: "", status: "todo", position: 1, iteration: 0,
    locked: false, lock_reason: "", branch: "", mr_url: "", mr_state: "", mr_target: "",
    clarification: null, clarification_record: null, created_at: "2026-08-01T00:00:00Z",
    depends_on: [], blocked_by: [], ...over,
  } as BacklogItem;
}

function run(over: Partial<HistoryRun> = {}): HistoryRun {
  return {
    id: "r1", task: "t", status: "INCOMPLETE", tests_passed: false, iterations: 1,
    commit_sha: "", source: "s", branch: "b", project_id: "p1", item_id: 1,
    validation_status: null, termination_reason: "", created_at: "2026-08-02T00:00:00Z",
    ...over,
  } as HistoryRun;
}

const diag = (over: Record<string, unknown>) => ({ outcome: "honest_park", ...over }) as never;

/* The ladder as a table. Each row is one population the console must name correctly; the six-rung
 * design this replaced put rows 6, 7 and 8 into "inspect" with the wrong verb. */
const CASES: { name: string; item: BacklogItem; runs: HistoryRun[]; verb: TriageVerb }[] = [
  {
    name: "an open ask outranks everything (ADR-0107)",
    item: item({ status: "in_review", clarification: { axis: "reachability" } as never }),
    runs: [run({ diagnosis: diag({ gate_reasons: ["validation_failed"] }) })],
    verb: "answer",
  },
  {
    name: "delivered work awaiting the human",
    item: item({ status: "in_review" }),
    runs: [run({ status: "APPROVED" })],
    verb: "review",
  },
  {
    name: "the spec refused the item — Quincy's job",
    item: item(),
    runs: [run({ diagnosis: diag({ park_cause: "under_specified" }) })],
    verb: "respecify",
  },
  {
    name: "a check that never ran is configuration, not craft",
    item: item(),
    runs: [run({ diagnosis: diag({ gate_reasons: ["security_not_attempted"] }) })],
    verb: "environment",
  },
  {
    name: "measured and found wanting",
    item: item(),
    runs: [run({ diagnosis: diag({ gate_reasons: ["claim_behavioral_failed"] }) })],
    verb: "judge",
  },
  {
    name: "tamper is judged, never filed as an ordinary objection",
    item: item(),
    runs: [run({ diagnosis: diag({ gate_reasons: ["tests_tampered"] }) })],
    verb: "judge",
  },
  {
    name: "a pre-gate stop carries no gate reasons and must NOT land in the residual",
    item: item(),
    runs: [run({ diagnosis: diag({ park_cause: "give_up", gate_reasons: [] }) })],
    verb: "judge",
  },
  {
    name: "a planning stall is the same population",
    item: item(),
    runs: [run({ diagnosis: diag({ park_cause: "stalled:plan", gate_reasons: [] }) })],
    verb: "judge",
  },
  {
    name: "held by a dependency",
    item: item({ blocked_by: [7] }),
    runs: [],
    verb: "blocked",
  },
  {
    name: "a soft PM hold",
    item: item({ locked: true, lock_reason: "waiting on design" }),
    runs: [],
    verb: "blocked",
  },
  {
    name: "never attempted is 'run it', not 'inspect it'",
    item: item(),
    runs: [],
    verb: "run",
  },
  {
    name: "stopped with nothing recorded stays honest about not knowing",
    item: item(),
    runs: [run({ status: "CANCELLED" })],
    verb: "inspect",
  },
];

describe("triage ladder", () => {
  for (const c of CASES) {
    it(c.name, () => {
      const [entry] = triage([c.item], c.runs);
      expect(entry?.verb).toBe(c.verb);
    });
  }

  it("excludes work in flight — it needs nobody", () => {
    expect(triage([item({ status: "in_progress" })], [run({ status: "RUNNING" })])).toHaveLength(0);
    // ...but an open ask on the same item still surfaces: a live run does not answer a question.
    const asking = item({ status: "in_progress", clarification: { axis: "checkability" } as never });
    expect(triage([asking], [run({ status: "RUNNING" })])[0]?.verb).toBe("answer");
  });

  it("excludes finished work", () => {
    expect(triage([item({ status: "done" })], [run({ status: "APPROVED" })])).toHaveLength(0);
  });

  it("PARTITIONS the open set — every open item lands in exactly one bucket", () => {
    // The property the first six-rung ladder failed: three real populations fell into the
    // residual bucket with the wrong verb, which is how a worklist quietly becomes a report.
    const items = CASES.map((c, i) => ({ ...c.item, id: i + 1 }));
    const runs = CASES.flatMap((c, i) => c.runs.map((r) => ({ ...r, id: `r${i}`, item_id: i + 1 })));
    const entries = triage(items, runs);
    expect(entries).toHaveLength(items.length);
    expect(new Set(entries.map((e) => e.item.id)).size).toBe(items.length);
    const bucketed = triageBuckets(entries).reduce((n, b) => n + b.entries.length, 0);
    expect(bucketed).toBe(entries.length);
  });

  it("orders buckets by urgency and counts only actionable ones as needing you", () => {
    const items = CASES.map((c, i) => ({ ...c.item, id: i + 1 }));
    const runs = CASES.flatMap((c, i) => c.runs.map((r) => ({ ...r, id: `r${i}`, item_id: i + 1 })));
    const buckets = triageBuckets(triage(items, runs));
    const order = buckets.map((b) => b.verb);
    expect(order).toEqual(TRIAGE_ORDER.filter((v) => order.includes(v)));
    // blocked / run / inspect are real states but not calls to action.
    const verbs = new Set(needsYou(triage(items, runs)).map((e) => e.verb));
    expect(verbs.has("blocked")).toBe(false);
    expect(verbs.has("run")).toBe(false);
    expect(verbs.has("inspect")).toBe(false);
    expect(verbs.has("answer")).toBe(true);
  });

  it("reads the newest DIAGNOSED attempt, so a later cancel cannot erase the reason", () => {
    const runs = [
      run({ id: "old", created_at: "2026-08-01T00:00:00Z", diagnosis: diag({ park_cause: "under_specified" }) }),
      run({ id: "new", created_at: "2026-08-05T00:00:00Z", status: "CANCELLED" }),
    ];
    expect(triage([item()], runs)[0]?.verb).toBe("respecify");
  });
});

describe("thrash detector", () => {
  const sig = (reasons: string[], id: string, at: string) =>
    run({ id, created_at: at, diagnosis: diag({ gate_reasons: reasons }) });
  const WALL = ["validation_failed", "reviewer_unknown", "security_unverified"];

  it("fires when consecutive attempts fail the IDENTICAL way", () => {
    const [hit] = thrashing(
      [item()],
      [sig(WALL, "a", "2026-08-03T00:00:00Z"), sig(WALL, "b", "2026-08-02T00:00:00Z")],
    );
    expect(hit?.repeats).toBe(2);
    expect(hit.signature).toEqual(WALL);
  });

  it("is order-insensitive within a signature — the same wall reported in a different order", () => {
    const [hit] = thrashing(
      [item()],
      [sig(WALL, "a", "2026-08-03T00:00:00Z"), sig([...WALL].reverse(), "b", "2026-08-02T00:00:00Z")],
    );
    expect(hit?.repeats).toBe(2);
  });

  it("does NOT fire on differing signatures — progress is not thrash", () => {
    expect(
      thrashing(
        [item()],
        [sig(WALL, "a", "2026-08-03T00:00:00Z"), sig(["iteration_limit"], "b", "2026-08-02T00:00:00Z")],
      ),
    ).toHaveLength(0);
  });

  it("EXCLUDES the empty signature — two pre-gate parks share nothing meaningful", () => {
    // A park that never reaches the gate records no reasons. Matching empty-to-empty would make
    // the detector fire hardest on exactly the runs where a shared signature proves nothing.
    expect(
      thrashing(
        [item()],
        [sig([], "a", "2026-08-03T00:00:00Z"), sig([], "b", "2026-08-02T00:00:00Z")],
      ),
    ).toHaveLength(0);
  });

  it("counts only the CONSECUTIVE newest run of identical failures", () => {
    const [hit] = thrashing(
      [item()],
      [
        sig(WALL, "new", "2026-08-05T00:00:00Z"),
        sig(WALL, "mid", "2026-08-04T00:00:00Z"),
        sig(["something_else"], "old", "2026-08-03T00:00:00Z"),
        sig(WALL, "older", "2026-08-02T00:00:00Z"),
      ],
    );
    expect(hit?.repeats).toBe(2);
    expect(hit?.attempts).toBe(4);
  });
});
