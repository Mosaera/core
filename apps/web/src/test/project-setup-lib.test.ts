import { describe, expect, it } from "vitest";

import type { ProjectSetup } from "../api/client";
import {
  draftCanBeVerified,
  draftChangesSomething,
  initialDraft,
  testerKnobNote,
  unverifiableWarning,
} from "../lib/projectSetup";
import { GATE_REMEDY, gateRemedy, ORACLE_LEG_REMEDY } from "../lib/remedy";

function setup(over: Partial<ProjectSetup> = {}): ProjectSetup {
  return {
    completed_at: null,
    current: {
      run_mode: "guided",
      posture: "business",
      test_cmd: "",
      tester_enabled: false,
      budget_usd: null,
      budget_tokens: null,
    },
    choices: { run_mode: ["guided"], posture: ["business"], cost_mode: ["balanced"] },
    tester_knob: { value: false, source: "default", clamped_by: null },
    available: true,
    oracle_plan: {
      legs: { tester_vouched: false, standing_suite: false, test_cmd: false, structural_vouch: false },
      verified_possible: false,
      recommended_knobs: ["tester_enabled"],
      recommend_test_cmd: true,
    },
    ...over,
  };
}

describe("the pre-filled draft", () => {
  it("applies a settable recommendation so the accept is one click", () => {
    expect(initialDraft(setup()).tester_enabled).toBe(true);
  });

  it("does NOT pre-apply a recommendation the operator cannot actually set", () => {
    // env > stored (ADR-0005): the toggle is read-only, so pre-filling it would show a card
    // promising verification that the save cannot deliver.
    const pinned = setup({ tester_knob: { value: false, source: "env", clamped_by: null } });
    expect(initialDraft(pinned).tester_enabled).toBe(false);
  });

  it("leaves everything else exactly as stored", () => {
    const draft = initialDraft(setup());
    expect(draft.run_mode).toBe("guided"); // the most supervised mode — never widened for you
    expect(draft.posture).toBe("business");
    expect(draft.test_cmd).toBe("");
  });

  it("knows whether it is proposing a change or just reflecting one", () => {
    // Drives the button's wording, which would otherwise claim a fix it is not making.
    expect(draftChangesSomething(setup(), initialDraft(setup()))).toBe(true);
    const nothingToDo = setup({
      oracle_plan: { ...setup().oracle_plan!, recommended_knobs: [] },
    });
    expect(draftChangesSomething(nothingToDo, initialDraft(nothingToDo))).toBe(false);
  });
});

describe("can anything vouch?", () => {
  const base = setup();
  const draft = {
    run_mode: "guided",
    posture: "business",
    test_cmd: "",
    tester_enabled: false,
    budget_usd: null,
  };

  it("is false when no leg is available — the newcomer's default state", () => {
    expect(draftCanBeVerified(base, draft)).toBe(false);
    expect(unverifiableWarning(base, draft)).toMatch(/nothing independent can vouch/i);
  });

  it("the Proctor alone is enough", () => {
    expect(draftCanBeVerified(base, { ...draft, tester_enabled: true })).toBe(true);
  });

  it("a test command alone is enough, but whitespace is not a command", () => {
    expect(draftCanBeVerified(base, { ...draft, test_cmd: "pytest -q" })).toBe(true);
    expect(draftCanBeVerified(base, { ...draft, test_cmd: "   " })).toBe(false);
  });

  it("a standing suite is enough on its own", () => {
    const withSuite = setup({
      oracle_plan: { ...base.oracle_plan!, legs: { ...base.oracle_plan!.legs, standing_suite: true } },
    });
    expect(draftCanBeVerified(withSuite, draft)).toBe(true);
    expect(unverifiableWarning(withSuite, draft)).toBe(""); // a warning always on is unread
  });
});

describe("the knob's provenance is stated, not hidden", () => {
  it("names an env pin", () => {
    expect(testerKnobNote(setup({ tester_knob: { source: "env" } }))).toMatch(/environment/i);
  });

  it("names a clamp — the operator must not be shown a toggle that does not govern", () => {
    expect(testerKnobNote(setup({ tester_knob: { clamped_by: "autonomous_verified" } }))).toMatch(
      /autonomous_verified/,
    );
  });

  it("says nothing when the knob is simply editable", () => {
    expect(testerKnobNote(setup())).toBe("");
  });
});

describe("park remedies", () => {
  it("names what to do, not just what happened", () => {
    expect(gateRemedy("oracle_unverified")?.text).toMatch(/Proctor|test command/i);
    expect(gateRemedy("iteration_limit")?.knob).toBe("max_iterations");
  });

  it("specialises by WHICH oracle leg refused", () => {
    // A generic sentence sends the operator to flip the Proctor when the Proctor was already on
    // and the sabotage check is what said no. The run records the leg; this reads it.
    expect(gateRemedy("oracle_unverified", ["mutation"])).toBe(ORACLE_LEG_REMEDY.mutation);
    expect(gateRemedy("oracle_unverified", ["structural"])).toBe(ORACLE_LEG_REMEDY.structural);
    expect(gateRemedy("oracle_unverified", ["independence"])).toBe(GATE_REMEDY.oracle_unverified);
  });

  it("ignores leg info for reasons it does not apply to, and returns null on a miss", () => {
    expect(gateRemedy("validation_failed", ["mutation"])).toBe(GATE_REMEDY.validation_failed);
    expect(gateRemedy("a_reason_from_the_future")).toBeNull(); // render nothing, never a guess
  });

  it("offers no knob for a tamper finding", () => {
    // There is no setting that makes "the run edited the tests it was judged by" acceptable, and
    // offering one would teach the operator to click past the most serious park the engine emits.
    expect(GATE_REMEDY.tests_tampered.knob).toBeUndefined();
    expect(GATE_REMEDY.content_destroyed.knob).toBeUndefined();
  });
});

describe("the budget row states the absence rather than inventing a number", () => {
  it("never pre-fills a suggested cap", () => {
    // A per-item cost is MEASURED from a project's own metered runs, and a new project has none.
    // A "typical" figure here would be the first number a newcomer ever reads from us, invented.
    expect(initialDraft(setup()).budget_usd).toBeNull();
  });

  it("carries the cap through when one is already set", () => {
    const capped = setup({ current: { ...setup().current, budget_usd: 25 } });
    expect(initialDraft(capped).budget_usd).toBe(25);
  });

  it("counts a changed cap as a proposal", () => {
    const draft = { ...initialDraft(setup()), budget_usd: 10 };
    expect(draftChangesSomething(setup(), draft)).toBe(true);
  });
});
