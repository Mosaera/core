/* Pins on the item-consolidated grouping — the fix for the Firehose Audit's exhibit A ("the same
 * run showing incomplete ten times"). Each pin names the semantics it protects. */
import { describe, expect, it } from "vitest";

import type { BacklogItem, HistoryRun } from "../api/client";
import {
  deliveredItems,
  groupRunsByItem,
  itemRunsSummary,
  itemsNeedingAttention,
  summarizeItemsPrefill,
} from "../lib/itemRuns";

const run = (over: Partial<HistoryRun>): HistoryRun =>
  ({
    id: "r1", task: "Build the hero", status: "APPROVED", tests_passed: true, iterations: 1,
    commit_sha: "abc", source: "s", branch: "b", project_id: "p1", item_id: 1,
    validation_status: "pass", created_at: "2026-08-22", ...over,
  }) as HistoryRun;

const item = (id: number, over: Partial<BacklogItem> = {}): BacklogItem =>
  ({ id, title: `Item ${id}`, status: "in_progress", ...over }) as BacklogItem;

describe("grouping", () => {
  it("seven failed attempts of one item are ONE attention item, not seven", () => {
    const attempts = Array.from({ length: 7 }, (_, i) =>
      run({ id: `a${i}`, status: "INCOMPLETE", tests_passed: null, validation_status: null }),
    );
    const groups = groupRunsByItem(attempts, [item(1)]);
    expect(groups).toHaveLength(1);
    expect(groups[0].attempts).toHaveLength(7);
    expect(itemsNeedingAttention(groups)).toHaveLength(1);
  });

  it("ad-hoc runs (null item_id) are each their own group — never merged by task string", () => {
    const groups = groupRunsByItem(
      [run({ id: "x", item_id: null, task: "same words" }), run({ id: "y", item_id: null, task: "same words" })],
      [],
    );
    expect(groups).toHaveLength(2);
  });

  it("a cancelled LATEST does not supersede a prior settled attempt", () => {
    // Cancelling a stray re-run must not demote a delivered item; the cancel stays in history.
    const groups = groupRunsByItem(
      [run({ id: "stray", status: "CANCELLED" }), run({ id: "shipped" })],
      [item(1)],
    );
    expect(groups[0].latest.id).toBe("shipped");
    expect(deliveredItems(groups)).toHaveLength(1);
  });

  it("an all-cancelled item auto-archives; anything else does not", () => {
    const groups = groupRunsByItem(
      [
        run({ id: "c1", status: "CANCELLED", item_id: 1 }),
        run({ id: "c2", status: "CANCELLED", item_id: 1 }),
        run({ id: "ok", item_id: 2 }),
      ],
      [item(1), item(2)],
    );
    expect(groups.find((g) => g.item?.id === 1)?.archived).toBe(true);
    expect(groups.find((g) => g.item?.id === 2)?.archived).toBe(false);
  });

  it("a RUNNING attempt is the item's state even over a settled one", () => {
    const groups = groupRunsByItem(
      [run({ id: "live", status: "RUNNING" }), run({ id: "done" })],
      [item(1)],
    );
    expect(groups[0].latest.id).toBe("live");
    expect(groups[0].outcome).toBe("running");
  });
});

describe("tri-state discipline survives the cutover", () => {
  it("tests_passed: null never lands an item in attention via truthiness", () => {
    // The deleted groupProjectRuns branched on truthy tests_passed — the misuse
    // lib/validation.ts:1 outlaws. A delivered run with a null flag is unavailable-attention
    // through runOutcome, and a PASSING run with null validation_status is legacy-passed —
    // neither path may ever consult truthiness again.
    const legacy = groupRunsByItem([run({ validation_status: null, tests_passed: true })], [item(1)]);
    expect(itemsNeedingAttention(legacy)).toHaveLength(0);
    const parked = groupRunsByItem(
      [run({ status: "INCOMPLETE", validation_status: null, tests_passed: null })],
      [item(1)],
    );
    expect(itemsNeedingAttention(parked)).toHaveLength(1); // parked = attention, but for the RIGHT reason
  });
});

describe("the summary speaks item language", () => {
  it("counts items with one honest trailing attempt count", () => {
    const groups = groupRunsByItem(
      [
        run({ id: "a1", status: "INCOMPLETE", tests_passed: null, validation_status: null, item_id: 1 }),
        run({ id: "a2", status: "INCOMPLETE", tests_passed: null, validation_status: null, item_id: 1 }),
        run({ id: "ok", item_id: 2 }),
      ],
      [item(1), item(2)],
    );
    expect(itemRunsSummary(groups, 3)).toBe(
      "2 items · 1 needs attention · 1 delivered · 3 attempts",
    );
  });
});

describe("PM prefill", () => {
  it("exact string, in item language", () => {
    const groups = groupRunsByItem([run({})], [item(1)]);
    expect(summarizeItemsPrefill(groups, 1)).toBe(
      "Summarize this project's run history (1 item · 1 delivered · 1 attempt). " +
        "What did each item accomplish, and what should I look at next?",
    );
  });
});
