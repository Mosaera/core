import { describe, expect, it } from "vitest";

import type { BacklogItem, HistoryRun, Project } from "../api/client";
import {
  AFTER_MERGE_PREFILL,
  askAboutChangePrefill,
  backlogItemForRun,
  buildFileTree,
  changesSummary,
  deriveReadiness,
  explainChangesPrefill,
  fileDiffStatus,
  fileStats,
  flattenTreeFiles,
  groupFilesByFolder,
  groupRuns,
  groupRunsByDate,
  latestSettledRun,
  mergeRiskPrefill,
  requestChangeEditsPrefill,
  runCardBadge,
  type DiffFileStatus,
} from "../lib/changes";
import { annotateDiff, diffLineKind, isTruncatedDiff, parseDiff } from "../lib/diff";

function run(over: Partial<HistoryRun> = {}): HistoryRun {
  return {
    id: "r1", task: "build the hero", status: "APPROVED", tests_passed: true, iterations: 1,
    commit_sha: "abc", source: "s", branch: "b", project_id: "p1", item_id: null,
    created_at: "2026-07-02T10:00:00Z", ...over,
  };
}

function item(over: Partial<BacklogItem> = {}): BacklogItem {
  return {
    id: 1, project_id: "p1", title: "Hero", description: "", acceptance: "",
    status: "done", position: 1, iteration: null, created_at: null, ...over,
  };
}

function project(over: Partial<Project> = {}): Project {
  return {
    id: "p1", name: "Demo", source_repo: "/tmp/demo", goal: "g", brief: "b",
    status: "active", branch: "mosaera/x", mr_url: "", autonomous: false,
    has_gitlab_token: true, gitlab_token_masked: "", error: "",
    created_at: null, backlog: [], runs: [], ...over,
  };
}

const DIFF =
  "diff --git a/src/app.ts b/src/app.ts\n" +
  "index 111..222 100644\n--- a/src/app.ts\n+++ b/src/app.ts\n" +
  "@@ -1,2 +1,3 @@\n+added line\n+another\n-removed\n context\n" +
  "diff --git a/README.md b/README.md\n" +
  "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n+docs\n";

describe("parseDiff / diffLineKind / isTruncatedDiff", () => {
  it("splits files and counts adds/dels", () => {
    const files = parseDiff(DIFF);
    expect(files.map((f) => f.path)).toEqual(["src/app.ts", "README.md"]);
    expect(files[0].adds).toBe(2);
    expect(files[0].dels).toBe(1);
    expect(files[1].adds).toBe(1);
  });

  it("tolerates a bare hunk without a diff --git header", () => {
    const files = parseDiff("@@ -1 +1 @@\n-old\n+new");
    expect(files).toHaveLength(1);
    expect(files[0]).toMatchObject({ path: "", adds: 1, dels: 1 });
  });

  it("classifies line kinds", () => {
    expect(diffLineKind("+x")).toBe("add");
    expect(diffLineKind("-x")).toBe("del");
    expect(diffLineKind("+++ b/f")).toBe("meta");
    expect(diffLineKind("--- a/f")).toBe("meta");
    expect(diffLineKind("@@ -1 +1 @@")).toBe("hunk");
    expect(diffLineKind("index 111..222")).toBe("meta");
    expect(diffLineKind(" context")).toBe("ctx");
  });

  it("detects the server truncation marker", () => {
    expect(isTruncatedDiff(DIFF)).toBe(false);
    expect(isTruncatedDiff(DIFF + "\n... (diff truncated at 200000 chars)")).toBe(true);
  });
});

describe("deriveReadiness", () => {
  const changes = { has_changes: true };

  it("merged wins over everything, counting historical failures", () => {
    const p = project({
      status: "merged", mr_url: "https://gl/mr/1",
      runs: [run({ tests_passed: false }), run({ id: "r2", tests_passed: true })],
    });
    const r = deriveReadiness(p, changes, "merged");
    expect(r.state).toBe("merged");
    expect(r.historicalFailures).toBe(1);
  });

  it("mrState merged flips readiness even before project.status catches up", () => {
    expect(deriveReadiness(project({ mr_url: "u", status: "in_review" }), changes, "merged").state)
      .toBe("merged");
  });

  it("mr-open when an MR exists and is not merged", () => {
    const r = deriveReadiness(
      project({ mr_url: "u", status: "in_review", runs: [run({ tests_passed: false })] }),
      changes, "opened",
    );
    expect(r.state).toBe("mr-open");
    expect(r.definingRun?.tests_passed).toBe(false); // inline warning data
  });

  it("blocked on latest settled failing validation; reason and run exposed", () => {
    const r = deriveReadiness(
      project({ runs: [run({ tests_passed: false, validation_status: "failed" })] }), changes, null,
    );
    expect(r.state).toBe("blocked");
    expect(r.reason).toBe("validation-failed");
    expect(r.definingRun?.id).toBe("r1");
  });

  it("delivered-unpushed only on a MEASURED false; unknown sync stays ready", () => {
    // ADR-0102 slice H: local-only commits used to read as "ready" (success).
    const p = project({ runs: [run()] });
    expect(deriveReadiness(p, { has_changes: true, remote_synced: false }, null).state).toBe(
      "delivered-unpushed",
    );
    // null = honest unknown (offline / no remote) — never claims unpushed.
    expect(deriveReadiness(p, { has_changes: true, remote_synced: null }, null).state).toBe(
      "ready",
    );
    expect(deriveReadiness(p, { has_changes: true, remote_synced: true }, null).state).toBe(
      "ready",
    );
    // An open MR outranks it (the push already happened for that MR).
    expect(
      deriveReadiness(
        project({ mr_url: "u", status: "in_review" }),
        { has_changes: true, remote_synced: false },
        "opened",
      ).state,
    ).toBe("mr-open");
  });

  it("validation unavailable is NOT blocked — it falls through to ready", () => {
    const r = deriveReadiness(
      project({ has_gitlab_token: true, runs: [run({ tests_passed: false, validation_status: "unavailable" })] }),
      changes, null,
    );
    expect(r.state).toBe("ready");
    expect(r.historicalFailures).toBe(0); // unavailable is not counted as a failure
  });

  it("blocked with not-approved beats validation reason", () => {
    const r = deriveReadiness(
      project({ runs: [run({ status: "NOT APPROVED", tests_passed: false })] }), changes, null,
    );
    expect(r.reason).toBe("not-approved");
  });

  it("RUNNING/CANCELLED never define readiness — newest settled run does", () => {
    const runs = [
      run({ id: "live", status: "RUNNING", tests_passed: false }),
      run({ id: "c", status: "CANCELLED", tests_passed: false }),
      run({ id: "green", status: "APPROVED", tests_passed: true }),
    ];
    expect(latestSettledRun(runs)?.id).toBe("green");
    expect(deriveReadiness(project({ runs }), changes, null).state).toBe("ready");
  });

  it("an older failure superseded by a newer green run does not block", () => {
    const runs = [run({ id: "new", tests_passed: true }), run({ id: "old", tests_passed: false })];
    expect(deriveReadiness(project({ runs }), changes, null).state).toBe("ready");
  });

  it("no-changes and no-token; blocked beats no-token", () => {
    expect(deriveReadiness(project(), { has_changes: false }, null).state).toBe("no-changes");
    expect(deriveReadiness(project({ has_gitlab_token: false }), changes, null).state)
      .toBe("no-token");
    expect(
      deriveReadiness(
        project({ has_gitlab_token: false, runs: [run({ tests_passed: false })] }), changes, null,
      ).state,
    ).toBe("blocked");
  });
});

describe("groupRuns / runCardBadge", () => {
  it("approved-but-failing lands in attention with the warning label", () => {
    const failing = run({ tests_passed: false });
    const groups = groupRuns([failing, run({ id: "ok" })], false);
    expect(groups.attention.map((r) => r.id)).toEqual(["r1"]);
    expect(groups.approved.map((r) => r.id)).toEqual(["ok"]);
    const badge = runCardBadge(failing);
    expect(badge.label).toBe("Approved · validation failed");
    expect(badge.tone).toBe("red");
  });

  it("merged demotes settled runs to historical; RUNNING stays live", () => {
    const groups = groupRuns(
      [run({ id: "live", status: "RUNNING" }), run({ id: "old", tests_passed: false })],
      true,
    );
    expect(groups.historical.map((r) => r.id)).toEqual(["old"]);
    expect(groups.attention.map((r) => r.id)).toEqual(["live"]);
  });

  it("planner-unavailable is amber, never red or green", () => {
    const badge = runCardBadge(run({ tests_passed: false, validation_status: "unavailable" }));
    expect(badge).toEqual({ label: "Approved · validation unavailable", tone: "amber" });
  });

  it("badges for the remaining statuses", () => {
    expect(runCardBadge(run({ status: "RUNNING" }))).toEqual({ label: "Running", tone: "neutral" });
    expect(runCardBadge(run({ status: "CANCELLED" }))).toEqual({
      label: "Cancelled", tone: "neutral",
    });
    // Errored runs are durably finalized now (no stale RUNNING) — red, honest.
    expect(runCardBadge(run({ status: "ERROR" }))).toEqual({ label: "Error", tone: "red" });
    expect(runCardBadge(run({ status: "NOT APPROVED" }))).toEqual({
      label: "Not approved", tone: "red",
    });
    // Honest non-delivery (ADR-0006): INCOMPLETE is an amber warning, not grey/neutral.
    expect(runCardBadge(run({ status: "INCOMPLETE" }))).toEqual({
      label: "Incomplete", tone: "amber",
    });
    expect(runCardBadge(run())).toEqual({ label: "Approved", tone: "green" });
  });

  it("backlogItemForRun matches by item_id only", () => {
    const backlog = [item({ id: 7, title: "Hero" })];
    expect(backlogItemForRun(run({ item_id: 7 }), backlog)?.title).toBe("Hero");
    expect(backlogItemForRun(run({ item_id: null }), backlog)).toBeUndefined();
  });
});

describe("changesSummary", () => {
  it("joins honest segments, omitting zeros", () => {
    expect(
      changesSummary({
        fileCount: 7, adds: 214, dels: 80, base: "main",
        runCount: 3, attentionCount: 1, mrLabel: "MR open",
      }),
    ).toBe("7 files · +214 −80 vs main · 3 changes · 1 needs attention · MR open");
    expect(
      changesSummary({
        fileCount: 1, adds: 0, dels: 0, base: "main", runCount: 0, attentionCount: 0, mrLabel: null,
      }),
    ).toBe("1 file · vs main");
  });
});

describe("fileStats / groupFilesByFolder", () => {
  it("prefers server stats and is never partial with them", () => {
    const { stats, partial } = fileStats({
      diff: DIFF + "\n... (diff truncated at 200000 chars)",
      files: ["src/app.ts"],
      stats: [{ path: "src/app.ts", additions: 2, deletions: 1 }],
    });
    expect(partial).toBe(false);
    expect(stats).toEqual([{ path: "src/app.ts", additions: 2, deletions: 1 }]);
  });

  it("falls back to parsing; truncation marks partial and unparsed files get nulls", () => {
    const { stats, partial } = fileStats({
      diff: DIFF + "\n... (diff truncated at 200000 chars)",
      files: ["src/app.ts", "README.md", "missing.bin"],
    });
    expect(partial).toBe(true);
    expect(stats.find((s) => s.path === "src/app.ts")).toEqual({
      path: "src/app.ts", additions: 2, deletions: 1,
    });
    expect(stats.find((s) => s.path === "missing.bin")).toEqual({
      path: "missing.bin", additions: null, deletions: null,
    });
  });

  it("groups by first path segment with (root), ordered by size then name", () => {
    const groups = groupFilesByFolder([
      { path: "src/a.ts", additions: 1, deletions: 0 },
      { path: "src/b.ts", additions: 2, deletions: 1 },
      { path: "README.md", additions: 3, deletions: 0 },
      { path: "assets/logo.svg", additions: null, deletions: null },
    ]);
    expect(groups.map((g) => g.name)).toEqual(["src", "(root)", "assets"]);
    expect(groups[0]).toMatchObject({ adds: 3, dels: 1 });
    expect(groups[2].adds).toBe(0); // binary nulls don't pollute sums
  });
});

describe("PM prefills", () => {
  it("exact strings", () => {
    expect(explainChangesPrefill("main", 7)).toBe(
      "Explain this project's accumulated changes (7 files changed vs main). " +
        "What changed, why, and which backlog items produced it?",
    );
    expect(explainChangesPrefill("main", 1)).toContain("(1 file changed vs main)");
    expect(mergeRiskPrefill("main", 2)).toBe(
      "Review the merge risk of the accumulated changes vs main (2 files changed). " +
        "What should I double-check before opening or accepting the merge request?",
    );
    expect(AFTER_MERGE_PREFILL).toMatch(/merged\. What should we plan/);
    expect(askAboutChangePrefill(run())).toBe('Regarding the change "build the hero" (run r1): ');
  });

  it("request-edits carries run, item, and failure context; omits absent parts", () => {
    const full = requestChangeEditsPrefill(run({ tests_passed: false }), item({ title: "Hero" }));
    expect(full).toContain('The change "build the hero" (run r1) needs edits');
    expect(full).toContain('backlog item "Hero"');
    expect(full).toContain("Its validation run failed.");
    expect(full).toMatch(/Requested changes:\n$/);
    const bare = requestChangeEditsPrefill(run());
    expect(bare).not.toContain("backlog item");
    expect(bare).not.toContain("validation run failed");
  });
});

describe("groupRunsByDate", () => {
  const now = new Date("2026-07-20T12:00:00Z");

  it("labels today and yesterday, keeps newest-first order", () => {
    const groups = groupRunsByDate(
      [
        run({ id: "a", created_at: "2026-07-20T09:00:00Z" }),
        run({ id: "b", created_at: "2026-07-20T08:00:00Z" }),
        run({ id: "c", created_at: "2026-07-19T20:00:00Z" }),
        run({ id: "d", created_at: "2026-07-02T10:00:00Z" }),
      ],
      now,
    );
    expect(groups.map((g) => g.label)).toEqual(["Today", "Yesterday", "Jul 2"]);
    expect(groups[0].runs.map((r) => r.id)).toEqual(["a", "b"]); // order preserved
  });

  it("collects runs with a missing/invalid date into a trailing Undated bucket", () => {
    const groups = groupRunsByDate(
      [run({ id: "a", created_at: "2026-07-20T09:00:00Z" }), run({ id: "x", created_at: null })],
      now,
    );
    expect(groups.at(-1)).toMatchObject({ key: "undated", label: "Undated" });
    expect(groups.at(-1)?.runs.map((r) => r.id)).toEqual(["x"]);
  });
});

describe("fileDiffStatus + buildFileTree", () => {
  it("derives A/M/D from git's new-file/deleted-file markers", () => {
    expect(fileDiffStatus(["new file mode 100644", "+x"])).toBe("A");
    expect(fileDiffStatus(["deleted file mode 100644", "-x"])).toBe("D");
    expect(fileDiffStatus(["@@ -1 +1 @@", "+x", "-y"])).toBe("M");
  });

  it("nests files into folders and collapses single-child chains", () => {
    const f = (path: string): { path: string; adds: number; dels: number; status: DiffFileStatus } => ({
      path, adds: 1, dels: 0, status: "M",
    });
    const tree = buildFileTree([f("apps/api/mosaera_api/app.py"), f("apps/api/mosaera_api/db.py"), f("README.md")]);
    // A collapsed "apps/api/mosaera_api" directory node + a root README file.
    const dir = tree.find((n) => n.type === "dir");
    expect(dir).toMatchObject({ type: "dir", name: "apps/api/mosaera_api", adds: 2 });
    expect(dir?.type === "dir" && dir.children.map((c) => c.name)).toEqual(["app.py", "db.py"]);
    expect(tree.some((n) => n.type === "file" && n.name === "README.md")).toBe(true);
  });

  it("flattenTreeFiles yields files in tree display order (dirs first, then files)", () => {
    const f = (path: string): { path: string; adds: number; dels: number; status: DiffFileStatus } => ({
      path, adds: 1, dels: 0, status: "M",
    });
    const tree = buildFileTree([f("README.md"), f("src/app.ts"), f("src/util.ts")]);
    // src/ (dir) sorts before the root README file; within, files are alpha.
    expect(flattenTreeFiles(tree).map((n) => n.path)).toEqual([
      "src/app.ts",
      "src/util.ts",
      "README.md",
    ]);
  });
});

describe("annotateDiff", () => {
  it("tracks old/new line numbers from the @@ hunk and blanks the opposite side", () => {
    const rows = annotateDiff(["@@ -10,3 +10,3 @@", " ctx", "-gone", "+added", " tail"]);
    expect(rows.map((r) => ({ k: r.kind, o: r.oldNo, n: r.newNo }))).toEqual([
      { k: "hunk", o: null, n: null },
      { k: "ctx", o: 10, n: 10 },
      { k: "del", o: 11, n: null }, // deleted line advances only the old side
      { k: "add", o: null, n: 11 }, // added line advances only the new side
      { k: "ctx", o: 12, n: 12 },
    ]);
  });
});
