import { describe, expect, it } from "vitest";

import type { Preflight, PresetPreview } from "../api/firstRun";
import {
  actionable,
  environmentChecks,
  foundKeys,
  foundSentence,
  fullyResolved,
  hasFastPath,
  bindingKey,
  effectiveResolution,
  incompleteBanner,
  parseBindingKey,
  probeLead,
  resolvedWithOverrides,
  setupConsequence,
  statusTone,
  uniformSummary,
  unresolvedRoles,
} from "../lib/firstRun";

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

function preset(rows: { role: string; model: string }[]): PresetPreview {
  return {
    id: "x",
    locality: "any",
    prefer: "cheapest",
    summary: "s",
    resolution: rows.map((r) => ({ ...r, provider: r.model ? "ollama" : "", reason: "because" })),
  };
}

describe("the probe sentence", () => {
  it("counts what Ollama actually has", () => {
    const found = foundSentence(
      pf({ inventory: { ollama_reachable: true, ollama_tags: ["a", "b"], ollama_error: "", env_keys: [] } }),
    );
    expect(found).toMatch(/2 models/);
  });

  it("singularises one model", () => {
    const found = foundSentence(
      pf({ inventory: { ollama_reachable: true, ollama_tags: ["a"], ollama_error: "", env_keys: [] } }),
    );
    expect(found).toMatch(/1 model\./);
  });

  it("distinguishes 'running but empty' from 'not running'", () => {
    const empty = pf({
      inventory: { ollama_reachable: true, ollama_tags: [], ollama_error: "", env_keys: [] },
    });
    expect(foundSentence(empty)).toMatch(/no models pulled/);
    const down = pf({
      inventory: { ollama_reachable: false, ollama_tags: [], ollama_error: "x", env_keys: [] },
    });
    expect(foundSentence(down)).toBe("");
  });

  it("offers the fast path when a key is already in the environment", () => {
    const withKey = pf({
      inventory: { ollama_reachable: false, ollama_tags: [], ollama_error: "", env_keys: ["anthropic"] },
    });
    expect(foundKeys(withKey)).toEqual(["anthropic"]);
    expect(hasFastPath(withKey)).toBe(true);
    expect(hasFastPath(pf())).toBe(false);
  });
});

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

  it("treats only fail and unknown as actionable — a note is not a chore", () => {
    const report = pf({
      checks: (["ok", "note", "fail", "unknown"] as const).map((status) => ({
        key: status,
        label: status,
        status,
        ok: status === "ok" || status === "note",
        detail: "",
        fix: "",
      })),
    });
    expect(actionable(report).map((c) => c.status)).toEqual(["fail", "unknown"]);
  });

  it("never tones an unknown check as success", () => {
    expect(statusTone("unknown")).not.toBe("success");
    expect(statusTone("ok")).toBe("success");
  });
});

describe("preset resolution", () => {
  const uniform = preset([
    { role: "pm", model: "a" },
    { role: "coder", model: "a" },
  ]);

  it("collapses to one line when every role matched", () => {
    expect(uniformSummary(uniform)).toBe("all 2 roles → a");
    expect(fullyResolved(uniform)).toBe(true);
  });

  it("does not collapse a mixed assignment", () => {
    expect(uniformSummary(preset([{ role: "pm", model: "a" }, { role: "coder", model: "b" }]))).toBe("");
  });

  it("names the roles a preset could not serve", () => {
    const partial = preset([{ role: "pm", model: "a" }, { role: "coder", model: "" }]);
    expect(fullyResolved(partial)).toBe(false);
    expect(unresolvedRoles(partial)).toEqual(["coder"]);
    // An unresolved role must never be summarised away as if it had landed somewhere.
    expect(uniformSummary(partial)).toBe("");
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

describe("the probe lead sentence", () => {
  // The rule this enforces: a check we could not evaluate is never rendered as a result. The lead
  // used to fall back to "Nothing was found on this machine yet" whenever the payload was absent —
  // which is also what "still loading" and "the request failed" look like.
  it("says it is still checking rather than asserting a finding", () => {
    expect(probeLead(undefined, "loading")).toMatch(/Checking what this machine has/);
    expect(probeLead(undefined, "loading")).not.toMatch(/Nothing was found/);
  });

  it("says the CHECK failed, not that the machine is empty", () => {
    expect(probeLead(undefined, "error")).toMatch(/Couldn't check this machine/);
    expect(probeLead(undefined, "error")).not.toMatch(/Nothing was found/);
  });

  it("reports an actually-empty machine as empty", () => {
    const empty = pf({
      inventory: { ollama_reachable: false, ollama_tags: [], ollama_error: "refused", env_keys: [] },
    });
    expect(probeLead(empty, "probed")).toMatch(/Nothing was found on this machine/);
  });

  it("leads with the finding when there is one", () => {
    const found = pf({
      inventory: { ollama_reachable: true, ollama_tags: ["a:1b"], ollama_error: "", env_keys: [] },
    });
    expect(probeLead(found, "probed")).toMatch(/Found Ollama on this machine with 1 model\./);
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

describe("per-role overrides", () => {
  const preset3 = (): PresetPreview => ({
    id: "premium",
    locality: "any",
    prefer: "operator",
    summary: "s",
    resolution: [
      { role: "pm", provider: "", model: "", reason: "you choose" },
      { role: "coder", provider: "", model: "", reason: "you choose" },
    ],
  });

  it("leaves untouched rows alone", () => {
    expect(effectiveResolution(preset3(), {})).toEqual(preset3().resolution);
  });

  it("applies a choice and says the choice was the operator's", () => {
    const rows = effectiveResolution(preset3(), { pm: { provider: "ollama", model: "a:1b" } });
    expect(rows[0]).toMatchObject({ provider: "ollama", model: "a:1b", reason: "you chose this one" });
    expect(rows[1].model).toBe("");
  });

  it("is only fully resolved once EVERY role has one", () => {
    const one = { pm: { provider: "ollama", model: "a:1b" } };
    expect(resolvedWithOverrides(preset3(), one)).toBe(false);
    expect(
      resolvedWithOverrides(preset3(), { ...one, coder: { provider: "ollama", model: "b:2b" } }),
    ).toBe(true);
  });

  it("round-trips a binding whose MODEL contains a slash", () => {
    // `org/model:tag` is an ordinary id shape; splitting on the last "/" would corrupt it.
    const key = bindingKey("openai", "org/model:tag");
    expect(parseBindingKey(key)).toEqual({ provider: "openai", model: "org/model:tag" });
  });
});
