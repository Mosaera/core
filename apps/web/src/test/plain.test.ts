import { describe, expect, it } from "vitest";

import {
  claimVerdict,
  CRITIC_VERDICT,
  GATE_REASON,
  gateReason,
  honestyLabel,
  mutationPlain,
  normalizeCriticVerdict,
  oracleKind,
  livePauseCause,
  parkCause,
  provenancePill,
  reviewerVerdict,
  stopReason,
  stopSentence,
  VALIDATION_STRENGTH,
} from "../lib/plain";

describe("gateReason — every token maps to plain English, none leak jargon", () => {
  // Iterate the MAP, never a hand-written list. A TS enumeration of a Python vocabulary is a
  // second origin: the old array here listed 13 tokens while the gate had 14, so
  // `validation_not_attempted` leaked raw jargon through the fallback and this test stayed green.
  // TOTALITY against mosaera_policies.gate.GateReason is checked Python-side
  // (packages/core/tests/test_gate_reason_coverage.py); this checks the COPY quality.
  it("maps every gate token to a plain sentence fragment", () => {
    for (const t of Object.keys(GATE_REASON)) {
      const plain = gateReason(t);
      expect(plain).not.toContain("_");
      expect(plain).not.toBe(t);
      // No raw engine words survive.
      expect(plain).not.toMatch(/oracle|critic_|tamper/);
    }
    expect(gateReason("oracle_unverified")).toBe("the work couldn't be independently verified");
  });
  it("unknown tokens degrade to readable, never crash", () => {
    expect(gateReason("brand_new_reason")).toBe("brand new reason");
  });
});

describe("oracleKind — all 6 kinds", () => {
  it("maps every kind; ast jargon is gone", () => {
    // F67: these three collapse to the whole-run tests_passed boolean, so none of them names
    // a check of its own. The old wording ("checked by a test", "checked by a syntax check")
    // claimed per-criterion verification that never happened.
    expect(oracleKind("acceptance_test")).toBe("covered by the run's whole suite passing");
    expect(oracleKind("ast_transformation_contract")).toBe("checked by a code-structure rule");
    expect(oracleKind("wellformedness_parse")).toBe("covered by the run's whole suite passing");
    expect(oracleKind("validation_exit")).toBe("covered by the run's whole suite passing");
    expect(oracleKind("tests_unmodified")).toBe("checked by leaving the tests untouched");
    expect(oracleKind("none")).toBe("no check attached");
  });
});

describe("claimVerdict — honest labels", () => {
  it("a claim without a check is NEVER called verified", () => {
    expect(claimVerdict("satisfied")).toEqual({ label: "verified", tone: "success" });
    expect(claimVerdict("failed").tone).toBe("destructive");
    expect(claimVerdict("unbound")).toEqual({ label: "no way to check it", tone: "muted" });
    expect(claimVerdict("unevaluable")).toEqual({ label: "couldn't be checked", tone: "muted" });
  });
});

describe("provenancePill — owner-ratified plain origins", () => {
  it("maps provenance; preference always wins over provenance", () => {
    expect(provenancePill("ENTAILED", true)).toBe("FROM YOUR REQUEST");
    expect(provenancePill("REPOSITORY_INVARIANT", true)).toBe("REPO RULE");
    expect(provenancePill("INFERRED", true)).toBe("SUGGESTED");
    expect(provenancePill("ENTAILED", false)).toBe("PREFERENCE");
  });
});

describe("normalizeCriticVerdict — the INSUFFICIENT_EVIDENCE fix", () => {
  it("counts the backend's actual token (the old exact-match counted zero)", () => {
    expect(normalizeCriticVerdict("INSUFFICIENT_EVIDENCE")).toBe("INSUFFICIENT_EVIDENCE");
    expect(normalizeCriticVerdict("INSUFFICIENT")).toBe("INSUFFICIENT_EVIDENCE");
    expect(normalizeCriticVerdict("supported")).toBe("SUPPORTED");
    expect(normalizeCriticVerdict("DISCARDED")).toBe("DISCARDED");
    expect(normalizeCriticVerdict("???")).toBe("OTHER");
    expect(normalizeCriticVerdict(null)).toBe("OTHER");
  });
  it("plain labels", () => {
    expect(CRITIC_VERDICT.INSUFFICIENT_EVIDENCE).toBe("not enough evidence");
    expect(CRITIC_VERDICT.SUPPORTED).toBe("confirmed");
    expect(CRITIC_VERDICT.DISCARDED).toBe("set aside");
  });
});

describe("reviewerVerdict", () => {
  it("plain phrases, tolerant of case", () => {
    expect(reviewerVerdict("APPROVE")).toBe("approved");
    expect(reviewerVerdict("REQUEST_CHANGES")).toBe("asked for changes");
    expect(reviewerVerdict("block")).toBe("blocked delivery");
  });
});

describe("mutationPlain — sabotage framing, tri-state honest", () => {
  it("true = caught (green), false = missed (amber, a priced gap), null = NEVER a verdict", () => {
    expect(mutationPlain(true).tone).toBe("success");
    expect(mutationPlain(true).label).toContain("checks noticed");
    expect(mutationPlain(false).tone).toBe("amber");
    expect(mutationPlain(false).label).toContain("didn't notice");
    expect(mutationPlain(null)).toEqual({ label: "sabotage check not run", tone: "muted" });
    expect(mutationPlain(undefined).tone).toBe("muted");
  });
});

describe("honestyLabel — fully plain badge", () => {
  it("green only for clean; everything else says exactly what happened", () => {
    expect(honestyLabel("clean")).toEqual({
      label: "EVERYTHING DELIVERED WAS VERIFIED", tone: "success",
    });
    expect(honestyLabel("unverified", 1).label).toBe("DELIVERED WITH 1 UNVERIFIED CLAIM");
    expect(honestyLabel("unverified", 3).label).toBe("DELIVERED WITH 3 UNVERIFIED CLAIMS");
    expect(honestyLabel("unverified", 1).tone).toBe("amber");
    expect(honestyLabel("no-claims")).toEqual({
      label: "DELIVERED — NOTHING WAS CHECKED", tone: "amber",
    });
    expect(honestyLabel("nothing").tone).toBe("muted");
    expect(honestyLabel("in-progress").label).toBe("STILL RUNNING");
  });
});

describe("honestySentence — the hero's quiet verdict", () => {
  it("green only for clean; every other state says what happened", async () => {
    const { honestySentence } = await import("../lib/plain");
    expect(honestySentence("clean")).toEqual({
      text: "Every claim that could be checked, was.", tone: "success",
    });
    expect(honestySentence("unverified", 1).text).toBe(
      "Delivered, with 1 claim that couldn't be verified.",
    );
    expect(honestySentence("unverified", 2).tone).toBe("amber");
    expect(honestySentence("no-claims").tone).toBe("amber");
    expect(honestySentence("nothing")).toEqual({ text: "Nothing was delivered.", tone: "muted" });
    expect(honestySentence("in-progress").text).toBe("Still running.");
  });
});

describe("VALIDATION_STRENGTH", () => {
  it("shallow reads as the warning it is", () => {
    expect(VALIDATION_STRENGTH.shallow).toContain("behaviour wasn't tested");
    expect(VALIDATION_STRENGTH.suite).toBe("a real test suite ran");
  });
});

describe("parkCause — every family reads plain, none crash", () => {
  it("maps the fixed families", () => {
    expect(parkCause("give_up")).toContain("stopped honestly");
    expect(parkCause("plan_unworkable")).toContain("unworkable as written");
    expect(parkCause("under_specified")).toContain("under-specified");
    expect(parkCause("iteration_limit")).toContain("revision limit");
    expect(parkCause("rode_to_cap")).toContain("every allowed revision");
    expect(parkCause("parked")).toContain("delivery checkpoint");
    expect(parkCause("")).toBe("");
  });

  it("parameterizes stalled:<kind>, generic for an unknown kind", () => {
    expect(parkCause("stalled:test")).toContain("same failing tests");
    expect(parkCause("stalled:review")).toContain("same review feedback");
    expect(parkCause("stalled:hygiene")).toContain("code-hygiene fixes");
    expect(parkCause("stalled:plan")).toContain("re-planning in circles");
    // Never render the raw kind as jargon.
    expect(parkCause("stalled:unknown")).toBe(
      "The run stopped making progress and the breaker tripped.",
    );
    expect(parkCause("stalled:frobnicate")).not.toContain("frobnicate");
  });

  it("an unknown token renders readably — the backend vocabulary can grow", () => {
    expect(parkCause("some_new:cause")).toBe("The run stopped: some new cause.");
  });
});

describe("stopReason — the first present channel, FULL text", () => {
  it("stall beats blocked; the text is never truncated", () => {
    const long = "y".repeat(150);
    expect(
      stopReason({ stall_reason: long, blocked_reason: "later" }),
    ).toEqual({ label: "No convergence", text: long });
    expect(stopReason({ blocked_reason: "missing dep" })).toEqual({
      label: "Coder blocked",
      text: "missing dep",
    });
  });

  it("null on an empty or absent diagnosis", () => {
    expect(stopReason(null)).toBeNull();
    expect(stopReason({})).toBeNull();
    expect(stopReason({ stall_reason: "  " })).toBeNull();
  });
});

describe("stopSentence — composed from the record, never asserted", () => {
  it("outcome + cause + the honest suffixes", () => {
    expect(
      stopSentence({
        outcome: "thrash_park",
        park_cause: "stalled:plan",
        tests_modified: true,
        iteration: 1,
        max_iterations: 3,
      }),
    ).toBe(
      "Ground to a halt before stopping. The run stopped making progress — it was " +
        "re-planning in circles. It also modified the tests it was judged by. " +
        "Stopped at revision 1 of 3.",
    );
  });

  it("sparse records compose what exists and invent nothing", () => {
    expect(stopSentence({ outcome: "honest_park" })).toBe(
      "Stopped honestly, without delivering.",
    );
    expect(stopSentence({})).toBe("");
  });
});

describe("livePauseCause — a run that is asking RIGHT NOW is not a run that ended", () => {
  /* Found live 2026-08-24 on my own #108 fix. The gate panel correctly began showing WHY the run
     stopped, and on a delivery park it read:

       "The run parked at the delivery checkpoint for a decision that never delivered."

     The run had not failed — it was waiting for the operator, at that moment, on that screen. Two
     things were wrong at once: the tense claims a settled outcome, and the sentence is VACUOUS
     anyway, because the reader is looking at the gate it describes.

     `PARK_CAUSE.parked` stays exactly as it is: on a SETTLED run it is accurate and useful. This is
     about which vocabulary belongs at which moment. */

  it("says nothing about a plain delivery park — the operator is looking at it", () => {
    expect(livePauseCause("parked")).toBe("");
  });

  it("still names a cause the operator cannot otherwise see", () => {
    // These are all true at a pause AND at a conclusion: they describe how the run got here.
    expect(livePauseCause("under_specified")).toMatch(/under-specified/i);
    expect(livePauseCause("give_up")).toMatch(/couldn't finish/i);
    expect(livePauseCause("plan_unworkable")).toMatch(/unworkable/i);
    expect(livePauseCause("stalled:test")).toMatch(/looping on the same failing tests/i);
  });

  it("never claims the run ended", () => {
    for (const cause of ["parked", "under_specified", "give_up", "iteration_limit", "rode_to_cap"]) {
      expect(livePauseCause(cause), cause).not.toMatch(/never delivered/i);
    }
  });

  it("an unknown cause degrades the same way parkCause does", () => {
    expect(livePauseCause("some_new_backend_token")).toBe(parkCause("some_new_backend_token"));
  });

  it("the SETTLED wording is untouched — it is correct there", () => {
    expect(parkCause("parked")).toMatch(/never delivered/i);
  });
});
