import { describe, expect, it } from "vitest";

import { actorFor, activityLine } from "../components/runs/runActors";

describe("actorFor", () => {
  it("names the newer graph nodes instead of echoing the node id", () => {
    expect(actorFor("design")).toMatchObject({ actor: "The Architect", done: "prepared the design" });
    expect(actorFor("quality_revise")).toMatchObject({
      actor: "The Smith",
      done: "revised for quality",
    });
  });

  it("still falls back honestly for an unknown node", () => {
    expect(actorFor("mystery")).toMatchObject({ actor: "mystery", done: "ran mystery" });
  });
});

describe("activityLine", () => {
  it("reads a delete as 'deleted <path>' (matches read/wrote)", () => {
    expect(activityLine("file_deleted", "src/old.py")).toBe("deleted src/old.py");
  });
});

describe("the engine-band roster nodes have names (#63)", () => {
  it("Proctor and the Critic are named, not raw node ids", () => {
    expect(actorFor("author_tests")).toMatchObject({
      actor: "The Assayer",
      done: "authored the acceptance tests",
    });
    expect(actorFor("critic")).toMatchObject({ actor: "The Critic", done: "judged the outcome" });
  });

  it("the coder's loop nodes all attribute to Forge", () => {
    for (const node of ["fix", "hygiene_fix", "review_fix", "quality_revise", "reason"])
      expect(actorFor(node).actor).toBe("The Smith");
  });

  it("sandbox_exec reads as a sentence, not a raw kind", () => {
    expect(activityLine("sandbox_exec", "pytest -q")).toBe("ran in the sandbox pytest -q");
  });
});
