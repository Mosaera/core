import { describe, expect, it } from "vitest";

import type { BacklogItem } from "../api/client";
import type { BranchStanding } from "../api/delivery";
import {
  mergeability,
  deliverySummary,
  driftNote,
  itemMrRows,
  standingPlain,
  stuckItems,
  READINESS_PLAIN,
  remoteSyncPlain,
} from "../lib/delivery";

function item(over: Partial<BacklogItem> = {}): BacklogItem {
  return {
    id: 1, project_id: "p1", title: "Hero", description: "", acceptance: "",
    status: "done", position: 0, iteration: null, created_at: null, ...over,
  };
}

describe("itemMrRows", () => {
  it("orders by position, folds MR facts, and gates the opener honestly", () => {
    const rows = itemMrRows([
      item({ id: 2, position: 1, status: "todo" }),
      item({ id: 1, position: 0, status: "done" }),
      item({
        id: 3, position: 2, status: "in_review",
        branch: "mosaera/item-3", mr_url: "https://gl/mr/3", mr_state: "opened",
      }),
    ]);
    expect(rows.map((r) => r.id)).toEqual([1, 2, 3]);
    // Delivered + no MR/branch → openable; todo → never; already-opened → never.
    expect(rows[0].canOpen).toBe(true);
    expect(rows[1].canOpen).toBe(false);
    expect(rows[2].canOpen).toBe(false);
    expect(rows[2].mrState).toBe("opened");
  });

  it("a branch marker without a URL still blocks reopening (the idempotency guard)", () => {
    const rows = itemMrRows([item({ branch: "mosaera/item-1", mr_url: "" })]);
    expect(rows[0].canOpen).toBe(false);
  });

  it("the live poll overrides the stored state", () => {
    const rows = itemMrRows(
      [item({ mr_url: "u", branch: "b", mr_state: "opened" })],
      [{ id: 1, state: "merged" }],
    );
    expect(rows[0].mrState).toBe("merged");
  });
});

describe("deliverySummary", () => {
  it("honest counts, empty parts omitted", () => {
    expect(
      deliverySummary(
        itemMrRows([
          item({ id: 1, mr_url: "u", branch: "b", mr_state: "merged" }),
          item({ id: 2, position: 1, mr_url: "u2", branch: "b2", mr_state: "opened" }),
          item({ id: 3, position: 2, status: "in_review" }),
        ]),
      ),
    ).toBe("1 merged · 1 MR open · 1 without their own MR");
    expect(deliverySummary(itemMrRows([item({ status: "todo" })]))).toBe("no item MRs yet");
  });
});

describe("plain wording", () => {
  it("unknown remote sync never reads as synced", () => {
    expect(remoteSyncPlain(true)).toContain("is on the remote");
    expect(remoteSyncPlain(false)).toContain("NOT on the remote");
    expect(remoteSyncPlain(null)).toContain("unknown");
    expect(remoteSyncPlain(undefined)).toContain("unknown");
  });

  it("every readiness state has a sentence", () => {
    for (const sentence of Object.values(READINESS_PLAIN)) {
      expect(sentence.length).toBeGreaterThan(10);
    }
  });

  it("driftNote surfaces only base-drift pauses", () => {
    expect(driftNote("base drift: origin/main and the local tip diverged")).toContain(
      "base drift",
    );
    expect(driftNote("autonomous paused: budget reached")).toBeNull();
    expect(driftNote("")).toBeNull();
    expect(driftNote(null)).toBeNull();
  });
});


describe("standingPlain", () => {
  const st = (o: Partial<BranchStanding>): BranchStanding =>
    ({ state: "unknown", ahead: null, behind: null, base: "main", ...o }) as BranchStanding;

  it("counts ahead exactly — that half is computable offline", () => {
    expect(standingPlain(st({ state: "ahead", ahead: 3, behind: 0 }), "main")).toBe(
      "3 commits ahead of main",
    );
    expect(standingPlain(st({ state: "ahead", ahead: 1, behind: 0 }), "main")).toBe(
      "1 commit ahead of main",
    );
  });

  it("says even when in sync", () => {
    expect(standingPlain(st({ state: "in_sync", ahead: 0, behind: 0 }), "main")).toBe(
      "even with main",
    );
  });

  it("names divergence when both sides moved", () => {
    expect(standingPlain(st({ state: "behind", ahead: 2, behind: 5 }), "main")).toBe(
      "2 commits ahead, 5 commits behind main — diverged",
    );
  });

  it("admits an UNCOUNTABLE behind rather than inventing a number", () => {
    // The whole point of the fetch-free design: we can prove we are behind without holding the
    // objects to count by how much. Saying "0 behind" or omitting it would both be lies.
    const out = standingPlain(st({ state: "behind_unknown", ahead: 1 }), "main");
    expect(out).toContain("unknown amount");
    expect(out).not.toMatch(/\d+ commits behind/);
  });

  it("never renders an unknown as in-sync (ADR-0102 slice H)", () => {
    for (const state of ["unknown", "no_remote", "no_remote_base"] as const) {
      expect(standingPlain(st({ state }), "main")).not.toMatch(/even with|in sync/i);
    }
  });
});


describe("stuckItems", () => {
  const row = (o: Partial<ReturnType<typeof itemMrRows>[number]>) =>
    ({ id: 1, position: 0, title: "t", status: "in_review", branch: "mosaera/item-100",
       mrTarget: "mosaera/item-99", mrUrl: "u", mrState: "opened", canOpen: false, ...o }) as never;

  it("flags an open MR whose target branch is gone", () => {
    const out = stuckItems([row({})], [{ name: "main" }, { name: "mosaera/item-100" }], "gitlab");
    expect(out.get(1)).toBe("mosaera/item-99");
  });

  it("does not flag one whose target still exists", () => {
    const out = stuckItems([row({})], [{ name: "mosaera/item-99" }], "gitlab");
    expect(out.size).toBe(0);
  });

  it("stays silent when the branch list is the clone fallback", () => {
    // The clone never lists mosaera/* at all, so a missing name proves nothing there. Crying
    // wolf would be the same defect class as the flag this replaces.
    const out = stuckItems([row({})], [{ name: "main" }], "clone");
    expect(out.size).toBe(0);
  });

  it("ignores merged and unopened items", () => {
    const rows = [row({ id: 2, mrState: "merged" }), row({ id: 3, mrState: "" })];
    expect(stuckItems(rows, [{ name: "main" }], "gitlab").size).toBe(0);
  });
});

describe("mergeability — what GitLab actually says, never a guess", () => {
  /* The one place a wrong answer puts a green "Ready to merge" in front of an operator on evidence
     nobody checked. GitLab's `detailed_merge_status` is the authority; this maps it to words and to
     what the modal may offer. Values observed live on this instance 2026-08-24: `ci_still_running`,
     `ci_must_pass`, `checking`, `not_open`. */

  it("mergeable is the ONLY state that offers a plain merge", () => {
    const m = mergeability("mergeable");
    expect(m.ready).toBe(true);
    expect(m.offer).toBe("merge");
    expect(m.headline).toMatch(/ready to merge/i);
  });

  it("a running pipeline is not ready, and offers auto-merge instead of refusing", () => {
    const m = mergeability("ci_still_running");
    expect(m.ready).toBe(false);
    expect(m.offer).toBe("auto-merge");
    expect(m.headline).toMatch(/pipeline is still running/i);
  });

  it("a FAILED pipeline offers nothing — auto-merge is not a way past a red pipeline", () => {
    const m = mergeability("ci_must_pass");
    expect(m.ready).toBe(false);
    expect(m.offer).toBe("none");
  });

  it("hard blockers name themselves and offer nothing", () => {
    for (const [status, pattern] of [
      ["conflict", /conflict/i],
      ["need_rebase", /rebase|conflict/i],
      ["discussions_not_resolved", /discussion/i],
      ["draft_status", /draft/i],
      ["not_approved", /approval/i],
    ] as const) {
      const m = mergeability(status);
      expect(m.ready, status).toBe(false);
      expect(m.offer, status).toBe("none");
      expect(m.headline, status).toMatch(pattern);
    }
  });

  it("'checking' is its own answer, neither ready nor blocked", () => {
    const m = mergeability("checking");
    expect(m.ready).toBe(false);
    expect(m.offer).toBe("none");
    expect(m.headline).toMatch(/still checking/i);
  });

  it("AN UNRECOGNISED STATUS IS NEVER READY, and shows what GitLab said", () => {
    // THE load-bearing pin. The vocabulary grows server-side; the tempting bug is to treat
    // "not obviously blocked" as mergeable, which is how a green button appears over an
    // unchecked claim. Fail toward not-ready and quote the token verbatim.
    const m = mergeability("some_future_status_nobody_mapped");
    expect(m.ready).toBe(false);
    expect(m.offer).toBe("none");
    expect(m.headline).toContain("some_future_status_nobody_mapped");
  });

  it("a missing status is not ready either — absence is not permission", () => {
    for (const missing of [null, undefined, ""]) {
      const m = mergeability(missing);
      expect(m.ready, String(missing)).toBe(false);
      expect(m.offer, String(missing)).toBe("none");
    }
  });

  it("carries the raw token so a reader can reconcile the sentence against GitLab", () => {
    expect(mergeability("ci_still_running").raw).toBe("ci_still_running");
  });
});

describe("the summary counts what it can see, and says only that", () => {
  it("never calls an item undelivered on evidence the row does not carry", () => {
    /* Item branches stack, so an item with no MR of its own may already be on the base — a later
       item's MR carried its commits. The page read "16 deliverable without an MR" over work that
       had merged hours earlier. The count is right; the claim was not. */
    const line = deliverySummary([
      { id: 1, position: 0, title: "a", status: "done", branch: "", mrUrl: "", mrTarget: "", mrState: "", canOpen: true },
      { id: 2, position: 1, title: "b", status: "done", branch: "", mrUrl: "", mrTarget: "", mrState: "", canOpen: true },
    ]);
    expect(line).toBe("2 without their own MR");
    expect(line).not.toMatch(/deliverable|undelivered|pending/i);
  });
});
