import { describe, expect, it } from "vitest";

import { constraintRows } from "../lib/charter";

describe("constraintRows", () => {
  it("splits the enumerated list the PM actually writes", () => {
    // The live shape, verbatim from the instance this was designed against.
    const rows = constraintRows(
      "1. All monetary values must use decimal.Decimal quantized to two places; floats are forbidden.\n" +
        "2. Runtime dependencies are limited to the Python standard library only; no third-party packages.\n" +
        "3. Tests must employ unittest and run with `python -m unittest discover`.",
    );
    expect(rows).toHaveLength(3);
    expect(rows[0].text).toMatch(/^All monetary values/);
    // The label is a scannable head, not a literal: this rule's clause runs past the cap, so it
    // truncates on a word boundary. Assert the PROPERTY (a bounded prefix of the rule) rather
    // than a string that would break the moment the cap moved.
    expect(rows[0].label.length).toBeLessThanOrEqual(48);
    expect(rows[0].text.startsWith(rows[0].label)).toBe(true);
    expect(rows[0].label).toMatch(/^All monetary values/);
    expect(rows[2].text).toMatch(/unittest discover/);
  });

  it("keeps a wrapped rule as ONE row — wrapping is not a new constraint", () => {
    const rows = constraintRows("1. A long rule that continues\n   onto a second line.\n2. Another.");
    expect(rows).toHaveLength(2);
    expect(rows[0].text).toBe("A long rule that continues onto a second line.");
  });

  it("handles bullets as well as numbers", () => {
    expect(constraintRows("- no CI files\n• stdlib only")).toHaveLength(2);
  });

  it("returns ONE row for un-enumerated prose rather than inventing structure", () => {
    // The row count is how the caller tells "structured" from "one blob" — it is never handed
    // fabricated rows for text that has none.
    const rows = constraintRows("The system must be fast and correct and cheap.");
    expect(rows).toHaveLength(1);
    expect(rows[0].text).toBe("The system must be fast and correct and cheap.");
  });

  it("is empty for empty input", () => {
    expect(constraintRows("")).toEqual([]);
    expect(constraintRows(null)).toEqual([]);
  });

  it("never paraphrases — the rule text is verbatim", () => {
    const rule = "2. `pyproject.toml` must declare *zero* runtime dependencies.";
    expect(constraintRows(rule)[0].text).toBe(
      "`pyproject.toml` must declare *zero* runtime dependencies.",
    );
  });
});
