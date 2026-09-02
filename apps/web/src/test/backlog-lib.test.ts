import { describe, expect, it } from "vitest";

import type { BacklogItem, HistoryRun } from "../api/client";
import {
  acceptanceCriteria,
  askPmPrefill,
  backlogSummary,
  isBlocked,
  requestEditsPrefill,
  runsForItem,
} from "../lib/backlog";
import { backlogCounts } from "../lib/overview";

function item(over: Partial<BacklogItem> = {}): BacklogItem {
  return {
    id: 1, project_id: "p1", title: "Homepage hero", description: "Rework the hero.",
    acceptance: "", status: "todo", position: 1, iteration: null,
    created_at: "2026-07-01T10:00:00Z", ...over,
  };
}

function run(over: Partial<HistoryRun> = {}): HistoryRun {
  return {
    id: "r1", task: "t", status: "SUCCESS", tests_passed: true, iterations: 1,
    commit_sha: "abc", source: "s", branch: "b", project_id: "p1", item_id: null,
    created_at: "2026-07-02T10:00:00Z", ...over,
  };
}

describe("isBlocked", () => {
  it("is true only when the server marks unmet dependencies", () => {
    expect(isBlocked(item({ blocked_by: [2, 3] }))).toBe(true);
    expect(isBlocked(item({ depends_on: [2], blocked_by: [] }))).toBe(false); // all delivered
    expect(isBlocked(item())).toBe(false); // no dependencies at all
  });
});

describe("acceptanceCriteria", () => {
  it("empty and whitespace-only text yields no criteria", () => {
    expect(acceptanceCriteria("")).toEqual([]);
    expect(acceptanceCriteria("  \n  \n")).toEqual([]);
  });

  it("strips dash/star/checkbox bullets", () => {
    expect(acceptanceCriteria("- a\n* b\n- [ ] c\n- [x] d")).toEqual(["a", "b", "c", "d"]);
  });

  it("strips numbered markers", () => {
    expect(acceptanceCriteria("1. first\n2) second")).toEqual(["first", "second"]);
  });

  it("single-line blob is one criterion", () => {
    expect(acceptanceCriteria("Form validates email")).toEqual(["Form validates email"]);
  });

  it("multi-line blob is one criterion per non-empty line", () => {
    expect(acceptanceCriteria("a\n\nb\nc")).toEqual(["a", "b", "c"]);
  });
});

describe("backlogSummary", () => {
  it("omits zero segments and pluralizes", () => {
    expect(backlogSummary(backlogCounts([item()]))).toBe("1 item");
    expect(
      backlogSummary(
        backlogCounts([
          item({ id: 1 }),
          item({ id: 2 }),
          item({ id: 3, status: "in_progress" }),
          item({ id: 4, status: "in_review" }),
          item({ id: 5, status: "done" }),
        ]),
      ),
    ).toBe("5 items · 1 in progress · 1 needs review · 1 done");
  });

  it("empty backlog reads as zero items", () => {
    expect(backlogSummary(backlogCounts([]))).toBe("0 items");
  });
});

describe("runsForItem", () => {
  it("matches by item_id and preserves API (newest-first) order", () => {
    const runs = [
      run({ id: "r3", item_id: 1 }),
      run({ id: "r2", item_id: 2 }),
      run({ id: "r1", item_id: 1 }),
    ];
    expect(runsForItem(runs, item({ id: 1 })).map((r) => r.id)).toEqual(["r3", "r1"]);
    expect(runsForItem(runs, item({ id: 9 }))).toEqual([]);
  });

  it("ignores runs without an item link", () => {
    expect(runsForItem([run({ item_id: null })], item({ id: 1 }))).toEqual([]);
  });
});

describe("PM prefills", () => {
  it("ask-PM prefill names the item", () => {
    expect(askPmPrefill(item())).toContain('"Homepage hero"');
  });

  it("request-edits prefill carries title, description and acceptance", () => {
    const text = requestEditsPrefill(
      item({ acceptance: "- loads fast\n- accessible" }),
    );
    expect(text).toContain('"Homepage hero"');
    expect(text).toContain("Rework the hero.");
    expect(text).toContain("- loads fast");
    expect(text).toMatch(/Requested changes:\n$/);
  });

  it("request-edits prefill omits empty sections", () => {
    const text = requestEditsPrefill(item({ description: "", acceptance: "" }));
    expect(text).not.toContain("Current description:");
    expect(text).not.toContain("Acceptance criteria:");
  });
});

describe("acceptanceCriteria — stored shapes the operator should never see", () => {
  it("unwraps a Python list repr stored on one line (F67)", () => {
    // Verbatim from LedgerCLI's Slice 1, which rendered brackets and quotes on the card.
    const stored =
      "['pyproject.toml exists in the repo root and declares zero runtime dependencies.', " +
      "'src/budget_tracker/__init__.py is present (empty).', " +
      "'Unit tests for storage and the add command pass when executed with `python -m unittest discover`.']";
    const out = acceptanceCriteria(stored);
    expect(out).toHaveLength(3);
    expect(out[0]).toBe("pyproject.toml exists in the repo root and declares zero runtime dependencies.");
    expect(out[2]).toContain("python -m unittest discover");
    expect(out.join(" ")).not.toContain("['");
  });

  it("handles a double-quoted list and escaped quotes inside an item", () => {
    expect(acceptanceCriteria(`["the header is 'amount,category'", "exit code is 0"]`)).toEqual([
      "the header is 'amount,category'",
      "exit code is 0",
    ]);
  });

  it("leaves ordinary line-based criteria untouched", () => {
    expect(acceptanceCriteria("- one\n- two\n3. three")).toEqual(["one", "two", "three"]);
  });

  it("does NOT mangle prose that merely starts and ends with brackets", () => {
    // No quoted segments to find, so it falls through to the line parser rather than emptying.
    expect(acceptanceCriteria("[see the brief for details]")).toEqual(["[see the brief for details]"]);
  });
});
