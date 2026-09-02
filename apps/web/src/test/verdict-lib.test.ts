/* Pins on the ONE verdict derivation. The headline of a trust surface is composed from the
 * gate's deterministic tokens — these tests are the reason it stays that way. */
import { describe, expect, it } from "vitest";

import { GATE_REASON } from "../lib/plain";
import {
  deriveVerdict,
  dominantReason,
  VERDICT_REASON_CLASS,
  type VerdictInput,
} from "../lib/verdict";

const claim = (verdict: string, material = true) => ({
  id: "c1",
  text: "keeps the API",
  provenance: "ENTAILED",
  oracleKind: "test",
  material,
  verdict,
  oracleRef: "t::x",
});

const base = (over: Partial<VerdictInput>): VerdictInput => ({
  delivered: true,
  atGate: false,
  claims: [claim("satisfied")],
  reasons: [],
  humanOverride: false,
  validationStrength: "suite",
  ...over,
});

describe("the class mirror", () => {
  it("classifies every token GATE_REASON knows — a new reason cannot land unclassified", () => {
    // Guard (1) of two: guard (2) is the Python AST test comparing every CLASS against
    // mosaera_policies.gate.REASON_CLASS, the source of truth. Both exist because a drifted
    // class makes the HEADLINE wrong, which on a gate is an honesty bug of the first order.
    expect(Object.keys(VERDICT_REASON_CLASS).sort()).toEqual(Object.keys(GATE_REASON).sort());
  });
});

describe("the severity ladder", () => {
  it("tamper outranks everything; not_run outranks objection outranks shortfall", () => {
    expect(dominantReason(["validation_failed", "critic_vetoed", "tests_tampered"])).toBe(
      "tests_tampered",
    );
    expect(dominantReason(["validation_failed", "security_stale"])).toBe("security_stale");
    expect(dominantReason(["validation_failed", "critic_vetoed"])).toBe("critic_vetoed");
    expect(dominantReason(["iteration_limit", "validation_failed"])).toBe("validation_failed");
  });
});

describe("the puncture rule — bad news reaches the headline", () => {
  it("tamper + every claim satisfied + human override can NEVER read as proven", () => {
    const v = deriveVerdict(base({ reasons: ["tests_tampered"], humanOverride: true }));
    expect(v.state).toBe("delivered-unproven");
    expect(v.tone).toBe("destructive");
    expect(v.reason?.token).toBe("tests_tampered");
  });

  it("stale security evidence + green tests can NEVER read as proven — ADR-0108, one layer up", () => {
    // The backend spent three red-team rounds making stale evidence stop vouching at the gate;
    // this pin is the UI half of the same invariant.
    const v = deriveVerdict(base({ reasons: ["security_stale"], humanOverride: true }));
    expect(v.state).not.toBe("proven");
  });

  it("an unverified delivery is never proven", () => {
    expect(deriveVerdict(base({ validationUnverified: true })).state).toBe("delivered-unproven");
  });

  it("a shallow-strength delivery is never proven", () => {
    expect(deriveVerdict(base({ validationStrength: "shallow" })).state).toBe(
      "delivered-unproven",
    );
  });

  it("no material claims is never proven — nothing was checked against a stated promise", () => {
    expect(deriveVerdict(base({ claims: [claim("satisfied", false)] })).state).toBe(
      "delivered-unproven",
    );
  });
});

describe("the clean case and the fallbacks", () => {
  it("a clean suite delivery with all claims satisfied is proven", () => {
    const v = deriveVerdict(base({}));
    expect(v.state).toBe("proven");
    expect(v.tone).toBe("success");
  });

  it("empty reasons on a stopped run fall back to the diagnosis stop channels — model prose is a BODY, never the headline over a token", () => {
    const v = deriveVerdict(
      base({
        delivered: false,
        reasons: [],
        diagnosis: { give_up_reason: "blocked: cannot modify the protected test" },
      }),
    );
    expect(v.state).toBe("not-proven");
    expect(v.reason?.token).toBe(""); // no deterministic token existed
    expect(v.reason?.text).toContain("blocked");
  });

  it("every secondary reason survives — ADR-0082 requires them in the summary layer", () => {
    const v = deriveVerdict(
      base({ delivered: false, reasons: ["tests_tampered", "validation_failed", "oracle_unverified"] }),
    );
    expect(v.reason?.token).toBe("tests_tampered");
    expect(v.secondary.map((r) => r.token).sort()).toEqual(
      ["oracle_unverified", "validation_failed"].sort(),
    );
  });
});
