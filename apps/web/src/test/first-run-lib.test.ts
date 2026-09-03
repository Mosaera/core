import { describe, expect, it } from "vitest";

import type { Preflight } from "../api/firstRun";
import { environmentChecks, incompleteBanner, setupConsequence, statusTone } from "../lib/firstRun";

function pf(over: Partial<Preflight> = {}): Preflight {
  return {
    checks: [],
    inventory: { ollama_reachable: null, ollama_tags: [], ollama_error: "", env_keys: [] },
    can_run: false,
    reason: "",
    blocks_launch: false,
    ...over,
  };
}

describe("check rendering", () => {
  it("keeps the environment rows in a fixed order so the screen never reshuffles", () => {
    const report = pf({
      checks: ["database", "docker", "images"].map((key) => ({
        key,
        label: key,
        status: "ok" as const,
        ok: true,
        detail: "",
        fix: "",
      })),
    });
    expect(environmentChecks(report).map((c) => c.key)).toEqual(["docker", "images", "database"]);
  });

  it("never tones an unknown check as success", () => {
    expect(statusTone("unknown")).not.toBe("success");
    expect(statusTone("ok")).toBe("success");
  });
});

describe("the deferred-setup banner", () => {
  it("is empty once the instance can run — it clears itself, with no flag to reconcile", () => {
    expect(incompleteBanner(pf({ can_run: true, reason: "" }))).toBe("");
  });

  it("carries the server's own reason", () => {
    expect(incompleteBanner(pf({ can_run: false, reason: "not reachable at :11434" }))).toMatch(
      /not reachable at :11434/,
    );
  });

  it("still says something useful when the server gave no reason", () => {
    expect(incompleteBanner(pf({ can_run: false, reason: "" }))).toMatch(/fail at the first model/);
  });

  // The two clauses below are the whole point of `blocks_launch`. The banner used to promise a
  // refusal in BOTH cases; on a fresh instance with an unreachable local Ollama the run was
  // accepted and cloned. A banner that describes a control the server does not exercise is the
  // silent-degradation shape #119 exists to close.
  it("promises a refusal only when the launch guard actually refuses", () => {
    expect(
      incompleteBanner(pf({ can_run: false, reason: "coder is bound to anthropic", blocks_launch: true })),
    ).toMatch(/Runs will be refused/);
  });

  it("says the run will START and then fail when nothing is merely reachable", () => {
    const msg = incompleteBanner(pf({ can_run: false, reason: "not reachable", blocks_launch: false }));
    expect(msg).toMatch(/fail at the first model call/);
    expect(msg).not.toMatch(/refused/);
  });
});

describe("the banner's unknown state", () => {
  it("never reports a failed readiness check as a healthy instance", () => {
    // Before this, a 500 from /api/preflight produced no wizard AND no banner: the operator was
    // told nothing at all and found out at the first run.
    const msg = incompleteBanner(undefined, "error");
    expect(msg).toMatch(/Couldn't check whether this instance is ready/);
  });

  it("still says nothing once the instance can run", () => {
    expect(incompleteBanner(pf({ can_run: true }), "probed")).toBe("");
  });
});

describe("the consequence sentence has one origin", () => {
  it("is the same string the banner uses, in both directions", () => {
    const blocked = pf({ can_run: false, reason: "r", blocks_launch: true });
    const doomed = pf({ can_run: false, reason: "r", blocks_launch: false });
    expect(incompleteBanner(blocked)).toContain(setupConsequence(blocked));
    expect(incompleteBanner(doomed)).toContain(setupConsequence(doomed));
    expect(setupConsequence(blocked)).not.toBe(setupConsequence(doomed));
  });
});
