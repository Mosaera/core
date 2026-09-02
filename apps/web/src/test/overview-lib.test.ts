import { describe, expect, it } from "vitest";

import type { ActiveRun, BacklogItem, HistoryRun, Project, ProjectMessage } from "../api/client";
import {
  activityFeed,
  attentionItems,
  backlogCounts,
  derivePhase,
  lastActivityAt,
  latestPmNote,
  lifecycleAction,
  timeAgo,
} from "../lib/overview";

function item(id: number, status: string, title = `item ${id}`, created = "2026-07-01T10:00:00Z"): BacklogItem {
  return {
    id, project_id: "p1", title, description: "", acceptance: "",
    status, position: id, iteration: null, created_at: created,
  };
}

function run(over: Partial<HistoryRun> = {}): HistoryRun {
  return {
    id: "r1", task: "do the thing", status: "APPROVED", tests_passed: true,
    iterations: 1, commit_sha: "abc", source: "src", branch: "b",
    project_id: "p1", item_id: null, created_at: "2026-07-02T10:00:00Z", ...over,
  };
}

function project(over: Partial<Project> = {}): Project {
  return {
    id: "p1", name: "P", source_repo: "src", goal: "g", brief: "b",
    status: "active", branch: "", mr_url: "", autonomous: false,
    has_gitlab_token: false, gitlab_token_masked: "", error: "",
    created_at: "2026-07-01T00:00:00Z", backlog: [], runs: [], ...over,
  };
}

const liveRun: ActiveRun = { run_id: "r9", status: "running", task: "live work", phase: "implement" };

describe("backlogCounts", () => {
  it("counts by status", () => {
    const c = backlogCounts([item(1, "todo"), item(2, "in_progress"), item(3, "in_review"), item(4, "done"), item(5, "todo")]);
    expect(c).toEqual({ total: 5, todo: 2, inProgress: 1, inReview: 1, done: 1 });
  });
});

describe("derivePhase", () => {
  it("maps the status matrix", () => {
    expect(derivePhase(project({ status: "draft" }))).toBe("Intake");
    expect(derivePhase(project({ status: "drafting" }))).toBe("Intake");
    expect(derivePhase(project({ status: "ready" }))).toBe("Intake"); // intake chat open
    expect(derivePhase(project({ status: "active" }))).toBe("Planning"); // no backlog yet
    expect(derivePhase(project({ status: "active", backlog: [item(1, "todo")] }))).toBe("Building");
    expect(derivePhase(project({ status: "active", backlog: [item(1, "in_review")] }))).toBe("Review");
    expect(derivePhase(project({ status: "active" }), liveRun)).toBe("Building");
    expect(derivePhase(project({ status: "in_review" }))).toBe("Merge");
    expect(derivePhase(project({ status: "merged" }))).toBe("Delivered");
  });
});

describe("lifecycleAction — PROJECT-level moves only", () => {
  /* The item-level branches moved to lib/triage.ts on 2026-08-22. They are per-item verbs, and a
     single "next action" could name only ONE of them however many kinds of stuck work existed —
     which is how a worklist degrades into a status line. What remains has no backlog item to hang
     off: intake, an open MR, the post-merge sprint. */
  it("intake states name their own move", () => {
    expect(lifecycleAction(project({ status: "drafting" }))?.cta).toBeNull();
    const ready = lifecycleAction(project({ status: "ready" }));
    expect(ready?.title).toMatch(/Shape the project/);
    expect(ready?.cta?.to).toBe("start");
  });

  it("an open MR outranks the empty-backlog notice", () => {
    const a = lifecycleAction(
      project({ status: "in_review", mr_url: "https://gl/mr/1", backlog: [item(1, "in_review")] }),
    );
    expect(a?.cta?.kind).toBe("external");
    expect(a?.cta?.to).toBe("https://gl/mr/1");
  });

  it("a merged project is pointed at the next sprint", () => {
    expect(lifecycleAction(project({ status: "merged" }))?.cta?.to).toBe("pm");
  });

  it("an empty backlog says the PM is still decomposing", () => {
    expect(lifecycleAction(project({ backlog: [] }))?.title).toMatch(/Building the backlog/);
  });

  it("returns NULL when the lifecycle asks for nothing — the worklist owns item work", () => {
    // This state used to produce "Run next item: …" / "Work is in flight", both of which the
    // triage ladder now answers per item and in the plural.
    expect(
      lifecycleAction(project({ backlog: [item(1, "todo"), item(2, "in_progress")] })),
    ).toBeNull();
  });
});

describe("attentionItems", () => {
  it("healthy project has none", () => {
    expect(attentionItems(project({ backlog: [item(1, "todo")] }), null)).toEqual([]);
  });
  it("project error is red and first", () => {
    const a = attentionItems(project({ error: "intake failed: boom" }), null);
    expect(a[0]).toMatchObject({ severity: "red", text: "intake failed: boom" });
  });
  it("failed validation on the latest run is red — honest vocabulary", () => {
    const a = attentionItems(
      project({ runs: [run({ tests_passed: false, validation_status: "failed" })] }), null,
    );
    expect(a.some((x) => x.severity === "red" && /validation failed/.test(x.text))).toBe(true);
  });
  it("a not-approved run is amber, not a test failure", () => {
    const a = attentionItems(
      project({ runs: [run({ status: "NOT APPROVED", tests_passed: false })] }), null,
    );
    expect(a.some((x) => x.severity === "amber" && /was not approved/.test(x.text))).toBe(true);
  });
  it("validation-unavailable is amber and never 'tests failed' (kills the lie)", () => {
    const a = attentionItems(
      project({ runs: [run({ tests_passed: false, validation_status: "unavailable" })] }), null,
    );
    expect(a.some((x) => x.severity === "amber" && /validation was unavailable/.test(x.text))).toBe(true);
    expect(a.some((x) => /tests failed/i.test(x.text))).toBe(false);
  });
  it("an errored (timed-out) run is 'errored', never 'tests failed'", () => {
    const a = attentionItems(project({ runs: [run({ status: "ERROR", tests_passed: false })] }), null);
    expect(a.some((x) => x.severity === "red" && /errored/.test(x.text))).toBe(true);
    expect(a.some((x) => /tests failed/i.test(x.text))).toBe(false);
  });
  it("in-review items and an open MR are amber", () => {
    const a = attentionItems(
      project({ status: "in_review", mr_url: "https://gl/mr/1", backlog: [item(1, "in_review")] }),
      "opened",
    );
    expect(a.every((x) => x.severity === "amber")).toBe(true);
    expect(a.some((x) => /waiting for review/.test(x.text))).toBe(true);
    expect(a.some((x) => /Merge request \(opened\)/.test(x.text))).toBe(true);
  });
});

describe("activity + timestamps", () => {
  const messages: ProjectMessage[] = [
    { role: "user", content: "hi", created_at: "2026-07-03T10:00:00Z" },
    { role: "pm", content: "Plan is ready.", created_at: "2026-07-03T11:00:00Z" },
  ];
  it("merges and sorts newest-first with a limit", () => {
    const p = project({ runs: [run()], backlog: [item(1, "todo")] });
    const feed = activityFeed(p, messages, 3);
    expect(feed).toHaveLength(3);
    expect(feed[0].text).toBe("PM replied in chat");
    expect(feed[0].kind).toBe("message");
    expect(feed[0].at.getTime()).toBeGreaterThan(feed[2].at.getTime());
  });

  it("does not file a failed turn under the stakeholder's messages", () => {
    // A `note` row records that a PM turn did not complete. The old two-way ternary sent
    // everything that was not `pm` down the else-branch, labelling an engine failure
    // "Stakeholder message to the PM" — attributing it to the operator on their own timeline.
    const feed = activityFeed(project({}), [
      { role: "note", content: "model_failed", created_at: "2026-07-03T12:00:00Z" },
    ]);
    const event = feed.find((e) => e.kind === "message");
    expect(event?.text).toBe("A PM reply didn't complete");
    expect(event?.text).not.toMatch(/Stakeholder/);
    expect(event?.tone).toBe("amber");
  });

  it("latestPmNote never quotes a failure token as Quincy's words", () => {
    // Already correct (`role === "pm"`), pinned so a later "generalisation" cannot put a bare
    // cause token into the Overview's "Latest from the PM" excerpt.
    expect(
      latestPmNote([
        { role: "pm", content: "Plan is ready.", created_at: "2026-07-03T11:00:00Z" },
        { role: "note", content: "model_failed", created_at: "2026-07-03T12:00:00Z" },
      ]),
    ).toBe("Plan is ready.");
  });

  it("marks failed/denied runs as amber, healthy events neutral", () => {
    const p = project({ runs: [run({ tests_passed: false, status: "NOT APPROVED" })] });
    const feed = activityFeed(p, []);
    const runEvent = feed.find((e) => e.kind === "run");
    expect(runEvent?.tone).toBe("amber");
    expect(feed.find((e) => e.kind === "project")?.tone).toBe("neutral");
  });
  it("lastActivityAt picks the newest stamp", () => {
    const p = project({ runs: [run()] });
    expect(lastActivityAt(p, messages)?.toISOString()).toBe("2026-07-03T11:00:00.000Z");
  });
  it("latestPmNote returns the last pm message", () => {
    expect(latestPmNote(messages)).toBe("Plan is ready.");
    expect(latestPmNote([{ role: "user", content: "x", created_at: null }])).toBeNull();
  });
  it("timeAgo formats", () => {
    const now = new Date("2026-07-05T12:00:00Z");
    expect(timeAgo(new Date("2026-07-05T11:59:40Z"), now)).toBe("just now");
    expect(timeAgo(new Date("2026-07-05T11:52:00Z"), now)).toBe("8 min ago");
    expect(timeAgo(new Date("2026-07-05T09:00:00Z"), now)).toBe("3 hr ago");
    expect(timeAgo(new Date("2026-07-03T09:00:00Z"), now)).toBe("2 days ago");
    expect(timeAgo(null, now)).toBe("—");
  });
});
