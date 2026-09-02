import { describe, expect, it } from "vitest";

import type { HistoryRun } from "../api/client";
import type { ProofAxis } from "../lib/proofAggregate";
import { deliveringRuns, projectProof, proofHeadline, proofTone } from "../lib/proofAggregate";

function run(over: Partial<HistoryRun> = {}): HistoryRun {
  return {
    id: "r1", task: "t", status: "APPROVED", tests_passed: true, iterations: 1,
    commit_sha: "abc", source: "s", branch: "b", project_id: "p1", item_id: 1,
    validation_status: "pass", termination_reason: "", created_at: "2026-08-10T00:00:00Z",
    receipt_id: "seal", ...over,
  } as HistoryRun;
}
const diag = (o: Record<string, unknown>) => ({ outcome: "clean_deliver", ...o }) as never;
const axis = (runs: HistoryRun[], key: string) =>
  projectProof(runs).axes.find((a) => a.key === key)!;

describe("delivering runs — one per item, the attempt that shipped", () => {
  it("collapses eight failed attempts plus a delivery into ONE delivery", () => {
    // The whole point of aggregating over deliveries: remediated parks cannot colour the picture.
    const attempts = Array.from({ length: 8 }, (_, i) =>
      run({ id: `p${i}`, status: "INCOMPLETE", created_at: `2026-08-0${i + 1}T00:00:00Z` }),
    );
    const shipped = run({ id: "win", created_at: "2026-08-09T00:00:00Z" });
    expect(deliveringRuns([...attempts, shipped])).toHaveLength(1);
    expect(deliveringRuns([...attempts, shipped])[0].id).toBe("win");
  });

  it("counts an ad-hoc delivery as its own unit", () => {
    expect(deliveringRuns([run({ item_id: null, id: "adhoc" })])).toHaveLength(1);
  });

  it("ignores items that never delivered", () => {
    expect(deliveringRuns([run({ status: "INCOMPLETE" })])).toHaveLength(0);
  });
});

describe("counting rules", () => {
  it("RULE 1 — an empty gate_reasons list is never counted as proof (green-by-vacancy)", () => {
    // 12 of 13 delivering runs on the live instance carry no gate reasons. If absence counted as
    // evidence, this project would render a perfect score over work nothing verified.
    const bare = run({ diagnosis: diag({ gate_reasons: [] }) });
    expect(axis([bare], "independence").proven).toBe(0);
    expect(axis([bare], "independence").unknown).toBe(1);
    expect(axis([bare], "independence").measured).toBe(0);
  });

  it("RULE 3 — the denominator is what was MEASURED, not what was delivered", () => {
    // `vouch` returned "" on every run before the instrument was wired. Counting those blanks as
    // failures would blame the engine for a field that did not exist yet.
    const recorded = run({ id: "a", diagnosis: diag({ vouch: "no_vouch:not_behavior_preserving" }) });
    const blank = run({ id: "b", item_id: 2, diagnosis: diag({ vouch: "" }) });
    const a = axis([recorded, blank], "independence");
    expect(a.failed).toBe(1);
    expect(a.unknown).toBe(1);
    expect(a.measured).toBe(1); // NOT 2 — one delivery never recorded an answer
    expect(proofHeadline(projectProof([recorded, blank]))).toBe(
      "0 of 1 deliveries were independently vouched",
    );
  });

  it("a real vouch is the only thing that turns independence green", () => {
    const vouched = run({ diagnosis: diag({ vouch: "structural_claims:c1,c2" }) });
    expect(axis([vouched], "independence").proven).toBe(1);
    expect(axis([vouched], "independence").failed).toBe(0);
  });

  it("checks read the recorded validation verdict, both directions", () => {
    expect(axis([run({ validation_status: "pass", tests_passed: true })], "checks").proven).toBe(1);
    expect(axis([run({ validation_status: "failed", tests_passed: false })], "checks").failed).toBe(1);
    // tri-state: null means the suite never reached a verdict, not that it failed.
    expect(
      axis([run({ validation_status: null, tests_passed: null })], "checks").unknown,
    ).toBe(1);
  });

  it("integrity needs BOTH an unmodified-tests verdict and a seal", () => {
    expect(axis([run({ diagnosis: diag({ tests_modified: false }) })], "integrity").proven).toBe(1);
    expect(axis([run({ diagnosis: diag({ tests_modified: true }) })], "integrity").failed).toBe(1);
    // Sealed but no verdict recorded, or a verdict with no seal: unknown, never proven.
    expect(axis([run({ diagnosis: diag({}) })], "integrity").unknown).toBe(1);
    expect(
      axis([run({ receipt_id: "", diagnosis: diag({ tests_modified: false }) })], "integrity").unknown,
    ).toBe(1);
  });
});

describe("headline", () => {
  it("says nothing has delivered rather than drawing an empty shape", () => {
    expect(proofHeadline(projectProof([]))).toBe("Nothing has delivered yet.");
  });

  it("distinguishes 'never recorded' from 'zero vouched'", () => {
    const blanks = [run({ diagnosis: diag({ vouch: "" }) })];
    expect(proofHeadline(projectProof(blanks))).toMatch(/independence not recorded/);
  });
});

describe("proofTone — a band, not a binary (owner, 2026-08-24)", () => {
  /* The previous rule had three states: all proven, none proven, and everything else. So 24 of 25
     and 1 of 25 were painted the same amber, and one imperfect run made an axis look like
     near-total failure. An axis nobody trusts is an axis nobody reads. */

  const axis = (proven: number, measured: number): ProofAxis => ({
    key: "checks", label: "Checks", note: "", proven, failed: measured - proven,
    unknown: 0, measured,
  });

  it("a single old failure in twenty-five does not repaint the axis", () => {
    expect(proofTone(axis(24, 25))).toBe("strong");
  });

  it("distinguishes mostly-proven from barely-proven", () => {
    expect(proofTone(axis(25, 25))).toBe("strong");
    expect(proofTone(axis(20, 25))).toBe("fair"); // 80%
    expect(proofTone(axis(12, 25))).toBe("weak"); // 48%
    expect(proofTone(axis(1, 25))).toBe("weak");
  });

  it("holds exactly at the thresholds", () => {
    expect(proofTone(axis(90, 100))).toBe("strong");
    expect(proofTone(axis(89, 100))).toBe("fair");
    expect(proofTone(axis(70, 100))).toBe("fair");
    expect(proofTone(axis(69, 100))).toBe("weak");
  });

  it("zero proven is weak, not a separate special case", () => {
    expect(proofTone(axis(0, 4))).toBe("weak");
  });

  it("UNMEASURED IS NOT A SCORE", () => {
    // "nothing was measured" is not a bad result — painting it as one is the absence-as-evidence
    // mistake this whole aggregate exists to avoid.
    expect(proofTone(axis(0, 0))).toBe("unmeasured");
  });
});
