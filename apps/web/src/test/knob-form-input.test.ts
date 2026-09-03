import { describe, expect, it } from "vitest";

import { IGNORE, parseFieldInput } from "../components/settings/KnobForm";

describe("parseFieldInput (S4)", () => {
  it("a blank field is a deliberate unset", () => {
    expect(parseFieldInput("number", "")).toBeNull();
    expect(parseFieldInput("text", "")).toBeNull();
  });

  it("a text/select/toggle field passes the raw string through unchanged", () => {
    expect(parseFieldInput("text", "http://localhost:11434")).toBe("http://localhost:11434");
  });

  it("a real number commits", () => {
    expect(parseFieldInput("number", "300")).toBe(300);
    expect(parseFieldInput("number", "-5")).toBe(-5);
    expect(parseFieldInput("number", "1.5")).toBe(1.5);
  });

  it("a non-blank value that STILL isn't a real number is IGNORED, never committed as null", () => {
    // The bug this closes: `Number(raw)` on any of these is NaN, which JSON-serializes to
    // `null` and used to silently UNSET the knob — a keystroke, not a deliberate clear.
    for (const raw of ["-", "1.2.3", "1e", "abc", "NaN"]) {
      expect(parseFieldInput("number", raw), raw).toBe(IGNORE);
    }
  });
});
