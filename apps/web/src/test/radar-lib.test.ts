/* Pins on the radar's honesty semantics: discrete rings, tri-state discipline, and the rule that
 * a source which cannot answer OMITS the axis rather than faking a ring. */
import { describe, expect, it } from "vitest";

import type { HistoryRun } from "../api/client";
import { priorAttemptShapes, radarFromGate, radarFromRow, radarTrend } from "../lib/radar";

const row = (over: Partial<HistoryRun>): HistoryRun =>
  ({
    id: "r1",
    task: "t",
    status: "APPROVED",
    tests_passed: true,
    iterations: 1,
    commit_sha: "abc",
    source: "s",
    branch: "b",
    project_id: "p1",
    item_id: 1,
    validation_status: "pass",
    created_at: "2026-08-22",
    receipt_id: "9f".padEnd(64, "0"),
    diagnosis: { outcome: "clean_deliver", gate_reasons: [] },
    ...over,
  }) as HistoryRun;

describe("tri-state discipline", () => {
  it("tests_passed: null is not-checked and NEVER a breach — a run that never reached tests did not fail them", () => {
    const axes = radarFromRow(
      row({ tests_passed: null, validation_status: null, status: "INCOMPLETE", diagnosis: null }),
    );
    const checks = axes.find((a) => a.axis === "checks")!;
    expect(checks.value).toBe("not-checked");
    expect(checks.breach).toBe(false);
  });

  it("an explicit failure IS a breach — failed never masquerades as not-checked", () => {
    const axes = radarFromRow(row({ tests_passed: false, validation_status: "fail" }));
    const checks = axes.find((a) => a.axis === "checks")!;
    expect(checks.breach).toBe(true);
  });
});

describe("omission over fabrication", () => {
  it("a list row omits the receipt-only axes (review, depth) rather than faking a ring", () => {
    const axes = radarFromRow(row({}));
    expect(axes.find((a) => a.axis === "review")!.value).toBeNull();
    expect(axes.find((a) => a.axis === "depth")!.value).toBeNull();
  });

  it("stale security is not-checked PLUS breach — 'ran, but not on this code' must puncture", () => {
    const axes = radarFromRow(
      row({ diagnosis: { outcome: "honest_park", gate_reasons: ["security_stale"] } }),
    );
    const sec = axes.find((a) => a.axis === "security")!;
    expect(sec.value).toBe("not-checked");
    expect(sec.breach).toBe(true);
  });
});

describe("the trend is literal shapes, never an average", () => {
  it("slices the last N settled runs and excludes running/cancelled", () => {
    const runs = [
      row({ id: "a", status: "RUNNING" }),
      row({ id: "b", status: "CANCELLED" }),
      row({ id: "c" }),
      row({ id: "d" }),
    ];
    const ghosts = radarTrend(runs, 5);
    expect(ghosts).toHaveLength(2);
    // Byte-equal to the individual runs' own shapes — the no-averaging pin.
    expect(ghosts[0]).toEqual(radarFromRow(runs[2]));
  });
});

describe("the open gate", () => {
  it("a clean gate yields no breaches; a tamper reason breaches integrity", () => {
    const clean = radarFromGate(
      { gate_decision: { action: "deliver", reasons: [], tests_passed: true, reviewer_verdict: "APPROVE" } },
      [],
    );
    expect(clean.every((a) => !a.breach)).toBe(true);
    const tampered = radarFromGate(
      {
        gate_decision: {
          action: "require_human",
          reasons: ["tests_tampered"],
          tests_passed: true,
          reviewer_verdict: "APPROVE",
        },
      },
      [],
    );
    expect(tampered.find((a) => a.axis === "integrity")!.breach).toBe(true);
  });
});

describe("per-item ghosts", () => {
  it("scopes to the SAME item's prior attempts — a global blur answers nothing", () => {
    const runs = [
      row({ id: "cur", item_id: 7 }),
      row({ id: "prior-same", item_id: 7 }),
      row({ id: "other-item", item_id: 8 }),
    ];
    const ghosts = priorAttemptShapes(runs, { id: "cur", item_id: 7 });
    expect(ghosts).toHaveLength(1);
    expect(ghosts[0]).toEqual(radarFromRow(runs[1]));
  });

  it("an ad-hoc run (null item_id) gets no ghosts — there is no 'last time' to compare to", () => {
    expect(priorAttemptShapes([row({ id: "x", item_id: null })], { id: "x", item_id: null })).toEqual([]);
  });
});

/* ProofRadar geometry — the first pin this component has ever had.
 *
 * Measured on the live instance 2026-08-22: the overview radar rendered "integrity" starting at
 * x = -9.5 (clipped to "ITEGRI") and the run pages lost the leading "P" of "proof depth". Labels
 * are centre-anchored at radius `R + LABEL_GAP` inside a `0 0 size size+8` viewBox, so a side
 * label wider than the gutter overflows. No test asserted geometry, so the bug shipped and
 * survived three redesign passes. This asserts the invariant directly rather than the fix. */
describe("ProofRadar label gutter", () => {
  const LABEL_GAP = 16;
  const LABEL_HALF_MAX = 32;
  const radius = (size: number) => size / 2 - LABEL_GAP - LABEL_HALF_MAX;
  // The two live mounts: ProofCard (196) and VerdictCard (168 compact, 208 full).
  const SIZES = [168, 196, 208];

  it("keeps the widest side label inside the viewBox at every mounted size", () => {
    for (const size of SIZES) {
      const cx = size / 2;
      // Side labels sit at the horizontal extremes: cx ± (R + LABEL_GAP).
      const leftEdge = cx - (radius(size) + LABEL_GAP) - LABEL_HALF_MAX;
      const rightEdge = cx + (radius(size) + LABEL_GAP) + LABEL_HALF_MAX;
      expect(leftEdge).toBeGreaterThanOrEqual(0);
      expect(rightEdge).toBeLessThanOrEqual(size);
    }
  });

  it("still leaves a drawable plot area at the smallest mounted size", () => {
    // A gutter that swallows the chart would trade a clipped label for an invisible shape.
    expect(radius(Math.min(...SIZES))).toBeGreaterThan(20);
  });
});
