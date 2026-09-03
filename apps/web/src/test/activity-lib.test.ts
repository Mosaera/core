import { describe, expect, it } from "vitest";

import { describeEvent } from "../lib/activity";

describe("describeEvent", () => {
  it("maps run lifecycle with honest tone", () => {
    const err = describeEvent("run.error", "boom");
    expect(err).toMatchObject({ group: "lifecycle", severity: "red" });
    expect(err.text).toContain("errored");
    expect(describeEvent("run.completed", "")).toMatchObject({
      group: "lifecycle",
      severity: "green",
      text: "Run completed",
    });
  });

  it("attributes node steps to the run personas", () => {
    const d = describeEvent("node", "test");
    expect(d).toMatchObject({ group: "lifecycle", actor: "The Engine", text: "ran validation" });
    expect(describeEvent("node", "review").actor).toBe("The Tribune");
  });

  it("maps gate decisions to Ledger with an attention tone", () => {
    const d = describeEvent("auto-park", "validation_failed");
    expect(d).toMatchObject({ group: "gate", actor: "Justice", severity: "amber" });
    expect(d.text).toContain("parked");
  });

  it("maps merge-request lifecycle", () => {
    expect(describeEvent("mr.opened", "http://x")).toMatchObject({ group: "mr", actor: "Mercury" });
    expect(describeEvent("mr.opened", "http://x").text).toContain("merge request");
    expect(describeEvent("mr.failed", "").severity).toBe("red");
  });

  it("shows unknown events verbatim (audit honesty)", () => {
    expect(describeEvent("weird.thing", "x").text).toBe("weird.thing: x");
  });
});
