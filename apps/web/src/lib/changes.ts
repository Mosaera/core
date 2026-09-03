/* Pure derivations for the Changes (merge-readiness) tab. Every value traces
   to a real API field — no fabricated risk, owners, or analysis. Unit-tested
   in changes-lib.test.ts. */

import { groupRunsByItem, type ItemGroup } from "./itemRuns";
import type { BacklogItem, HistoryRun, Project } from "../api/client";
import { isTruncatedDiff, parseDiff } from "./diff";
import { runOutcome } from "./validation";

/* ---------------------------------------------------------------- readiness */

export type ReadinessState =
  | "merged"
  | "mr-open"
  /** Committed locally, no MR, and the branch tip is NOT on the remote (ADR-0102).
   *  Unknown sync (null) never claims this — it stays "ready". */
  | "delivered-unpushed"
  | "blocked"
  | "ready"
  | "no-changes"
  | "no-token";

export interface Readiness {
  state: ReadinessState;
  /** For blocked: what the latest settled run got wrong. Validation being
   *  *unavailable* is not a failure — it never blocks. */
  reason?: "validation-failed" | "not-approved";
  /** The run that defines blocked (and the honest basis for "ready"). */
  definingRun?: HistoryRun;
  /** Merged projects: settled runs whose validation genuinely failed (history,
   *  not blockers) — excludes unavailable. */
  historicalFailures: number;
}

/** Newest run that actually finished the delivery gate. RUNNING and CANCELLED
 *  runs never define merge readiness — they surface in grouping instead. */
export function latestSettledRun(runs: HistoryRun[]): HistoryRun | undefined {
  return runs.find((r) => r.status === "APPROVED" || r.status === "NOT APPROVED");
}

export function deriveReadiness(
  project: Project,
  diff: { has_changes: boolean; remote_synced?: boolean | null } | undefined,
  mrState: string | null,
  // A GitHub App connection is as good as a GitLab token for opening the request
  // (capability.has_github_connection) — readiness must not be GitLab-blind, or a
  // connected GitHub project reads "no token" forever and the open action never renders.
  alsoCredentialed = false,
): Readiness {
  const credentialed = project.has_gitlab_token || alsoCredentialed;
  const runs = project.runs ?? [];
  const settled = latestSettledRun(runs);
  const historicalFailures = runs.filter((r) => runOutcome(r) === "validation-failed").length;
  const outcome = settled ? runOutcome(settled) : undefined;

  if (project.status === "merged" || mrState === "merged") {
    return { state: "merged", historicalFailures };
  }
  if (project.mr_url && project.status === "in_review") {
    return { state: "mr-open", definingRun: settled, historicalFailures };
  }
  if (diff?.has_changes && outcome === "not-approved") {
    return { state: "blocked", reason: "not-approved", definingRun: settled, historicalFailures };
  }
  // Validation unavailable is NOT a failure — an approved-with-unavailable run
  // (human override) falls through to "ready", never "blocked".
  if (diff?.has_changes && outcome === "validation-failed") {
    return {
      state: "blocked",
      reason: "validation-failed",
      definingRun: settled,
      historicalFailures,
    };
  }
  // "Delivered but unpushed" is a first-class state (ADR-0102 slice H): the work is
  // committed locally and the remote provably lacks the branch tip. Only a MEASURED
  // false claims it — null (offline/unknown) falls through to "ready" as before.
  if (diff?.has_changes && credentialed && diff.remote_synced === false) {
    return { state: "delivered-unpushed", definingRun: settled, historicalFailures };
  }
  if (diff?.has_changes && credentialed) {
    return { state: "ready", definingRun: settled, historicalFailures };
  }
  if (!diff?.has_changes) {
    return { state: "no-changes", historicalFailures };
  }
  return { state: "no-token", historicalFailures };
}

/* ----------------------------------------------------------------- grouping */

export interface ChangeGroups {
  /** Failing, not approved, cancelled, or still running — needs eyes. */
  attention: HistoryRun[];
  /** Approved with passing validation. */
  approved: HistoryRun[];
  /** Merged projects: settled/cancelled runs shown as history, not blockers. */
  historical: HistoryRun[];
}

export function groupRuns(runs: HistoryRun[], projectMerged: boolean): ChangeGroups {
  const groups: ChangeGroups = { attention: [], approved: [], historical: [] };
  for (const run of runs) {
    if (projectMerged && run.status !== "RUNNING") {
      groups.historical.push(run);
    } else if (run.status === "APPROVED" && run.tests_passed) {
      groups.approved.push(run);
    } else {
      groups.attention.push(run);
    }
  }
  return groups;
}

export type BadgeTone = "green" | "amber" | "red" | "neutral";

/** Honest one-badge summary per run. "Approved · validation failed" must read
 *  as a warning — approval and passing tests are independent facts. */
export function runCardBadge(run: HistoryRun): { label: string; tone: BadgeTone } {
  if (run.status === "RUNNING") return { label: "Running", tone: "neutral" };
  if (run.status === "CANCELLED") return { label: "Cancelled", tone: "neutral" };
  if (run.status === "ERROR") return { label: "Error", tone: "red" };
  if (run.status === "NOT APPROVED") return { label: "Not approved", tone: "red" };
  // Honest non-delivery (ADR-0006): a run that parked / exhausted iterations / couldn't satisfy
  // the reviewer ends INCOMPLETE — an amber warning, never dressed up as done or a hard error.
  if (run.status === "INCOMPLETE") return { label: "Incomplete", tone: "amber" };
  if (run.status === "APPROVED" && run.validation_status === "unavailable")
    return { label: "Approved · validation unavailable", tone: "amber" };
  // `tests_passed === false` only — null means no test phase was reached, which is not a failure.
  if (run.status === "APPROVED" && run.tests_passed === false)
    return { label: "Approved · validation failed", tone: "red" };
  if (run.status === "APPROVED" && run.tests_passed == null)
    return { label: "Approved · validation unavailable", tone: "amber" };
  if (run.status === "APPROVED") return { label: "Approved", tone: "green" };
  return { label: run.status.toLowerCase(), tone: "neutral" };
}

export function backlogItemForRun(
  run: HistoryRun,
  backlog: BacklogItem[],
): BacklogItem | undefined {
  if (run.item_id == null) return undefined;
  return backlog.find((i) => i.id === run.item_id);
}

/* ------------------------------------------------------- date grouping (commits) */

export interface RunDateGroup {
  key: string;
  label: string;
  runs: HistoryRun[];
}

/** Bucket runs by local calendar day for the commits-style list. Runs arrive
 *  newest-first from the API and that order is preserved (both across and within
 *  buckets). Today/Yesterday get friendly labels; a run with a missing/invalid
 *  `created_at` lands in a trailing "Undated" bucket instead of crashing. */
export function groupRunsByDate(runs: HistoryRun[], now: Date = new Date()): RunDateGroup[] {
  return bucketByDate(runs, (r) => r.created_at, now).map((b) => ({
    key: b.key,
    label: b.label,
    runs: b.items,
  }));
}

export interface DateBucket<T> {
  key: string;
  label: string;
  items: T[];
}

/** Bucket anything datestamped into Today / Yesterday / a date label, preserving input order.
 *  One origin for the label vocabulary — the run list and the item-consolidated change list both
 *  read it, so the two surfaces can never drift into different words for the same day. */
export function bucketByDate<T>(
  items: T[],
  at: (item: T) => string | null,
  now: Date = new Date(),
): DateBucket<T>[] {
  const dayKey = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
  const todayKey = dayKey(now);
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const yesterdayKey = dayKey(yesterday);

  const buckets: DateBucket<T>[] = [];
  const byKey = new Map<string, DateBucket<T>>();
  const undated: T[] = [];

  for (const item of items) {
    const raw = at(item);
    const d = raw ? new Date(raw) : null;
    if (!d || Number.isNaN(d.getTime())) {
      undated.push(item);
      continue;
    }
    const key = dayKey(d);
    let bucket = byKey.get(key);
    if (!bucket) {
      const label =
        key === todayKey
          ? "Today"
          : key === yesterdayKey
            ? "Yesterday"
            : d.toLocaleDateString(undefined, {
                month: "short",
                day: "numeric",
                year: d.getFullYear() === now.getFullYear() ? undefined : "numeric",
              });
      bucket = { key, label, items: [] };
      byKey.set(key, bucket);
      buckets.push(bucket);
    }
    bucket.items.push(item);
  }
  if (undated.length > 0) buckets.push({ key: "undated", label: "Undated", items: undated });
  return buckets;
}

/** The Changes list, item-consolidated (owner decision 2026-08-22): one entry per backlog item,
 *  its LATEST attempt carrying the state, earlier attempts collapsed underneath — the same model
 *  the Runs page uses, so a "row" finally means the same thing on both pages. The item lands in
 *  the day bucket of its latest attempt, which is what "when did this change land" means. */
export function groupItemChangesByDate(
  runs: HistoryRun[],
  backlog: BacklogItem[],
  projectMerged: boolean,
  now: Date = new Date(),
): DateBucket<ItemGroup>[] {
  const groups = groupRunsByItem(runs, backlog, projectMerged);
  return bucketByDate(groups, (g) => g.latest.created_at, now);
}

/* --------------------------------------------------------- file tree (commit page) */

/** Stable DOM id for a file's diff section, so the file tree can scroll to it. */
export function fileAnchorId(path: string): string {
  return `file-${path.replace(/[^a-zA-Z0-9]+/g, "-")}`;
}

export type DiffFileStatus = "A" | "M" | "D";

/** Human-readable status word (the A/M/D letters aren't self-evident). */
export const FILE_STATUS_LABEL: Record<DiffFileStatus, string> = {
  A: "added",
  M: "modified",
  D: "deleted",
};

/** A/M/D from a parsed file's raw diff lines (git writes `new file`/`deleted file`). */
export function fileDiffStatus(lines: string[]): DiffFileStatus {
  if (lines.some((l) => l.startsWith("new file"))) return "A";
  if (lines.some((l) => l.startsWith("deleted file"))) return "D";
  return "M";
}

export interface TreeFileNode {
  type: "file";
  name: string;
  path: string;
  adds: number;
  dels: number;
  status: DiffFileStatus;
}
export interface TreeDirNode {
  type: "dir";
  name: string; // may be a collapsed "a/b/c" chain
  path: string;
  children: TreeNode[];
  adds: number;
  dels: number;
}
export type TreeNode = TreeFileNode | TreeDirNode;

/** Files in the tree's display order (depth-first, dirs before files, matching
 *  what FileTree renders) — so the stacked diffs scroll in tree order. */
export function flattenTreeFiles(nodes: TreeNode[]): TreeFileNode[] {
  const out: TreeFileNode[] = [];
  for (const node of nodes) {
    if (node.type === "dir") out.push(...flattenTreeFiles(node.children));
    else out.push(node);
  }
  return out;
}

interface RawDir {
  dirs: Map<string, RawDir>;
  files: TreeFileNode[];
}

/** Build a nested folder tree from a flat list of changed files, collapsing
 *  single-child directory chains (e.g. `apps/api/mosaera_api`) into one node —
 *  the GitLab commit-page idiom. Pure; unit-tested. */
export function buildFileTree(
  files: { path: string; adds: number; dels: number; status: DiffFileStatus }[],
): TreeNode[] {
  const root: RawDir = { dirs: new Map(), files: [] };
  for (const f of files) {
    const parts = f.path.split("/");
    const name = parts.pop() ?? f.path;
    let cur = root;
    for (const seg of parts) {
      let next = cur.dirs.get(seg);
      if (!next) {
        next = { dirs: new Map(), files: [] };
        cur.dirs.set(seg, next);
      }
      cur = next;
    }
    cur.files.push({ type: "file", name, path: f.path, adds: f.adds, dels: f.dels, status: f.status });
  }
  return convertDir(root, "");
}

function convertDir(dir: RawDir, prefix: string): TreeNode[] {
  const nodes: TreeNode[] = [];
  const dirNames = [...dir.dirs.keys()].sort((a, b) => a.localeCompare(b));
  for (const name of dirNames) {
    let raw = dir.dirs.get(name)!;
    let display = name;
    // Collapse a chain of single-subdir, no-file directories into one node.
    while (raw.files.length === 0 && raw.dirs.size === 1) {
      const [childName, childRaw] = [...raw.dirs.entries()][0];
      display = `${display}/${childName}`;
      raw = childRaw;
    }
    const path = prefix ? `${prefix}/${display}` : display;
    const children = convertDir(raw, path);
    const adds = children.reduce((n, c) => n + c.adds, 0);
    const dels = children.reduce((n, c) => n + c.dels, 0);
    nodes.push({ type: "dir", name: display, path, children, adds, dels });
  }
  nodes.push(...[...dir.files].sort((a, b) => a.name.localeCompare(b.name)));
  return nodes;
}

/* ------------------------------------------------------------------ summary */

export function changesSummary(args: {
  fileCount: number;
  adds: number;
  dels: number;
  base: string;
  runCount: number;
  attentionCount: number;
  mrLabel: string | null;
}): string {
  const parts: string[] = [];
  parts.push(`${args.fileCount} ${args.fileCount === 1 ? "file" : "files"}`);
  if (args.adds > 0 || args.dels > 0) parts.push(`+${args.adds} −${args.dels} vs ${args.base}`);
  else parts.push(`vs ${args.base}`);
  if (args.runCount > 0)
    parts.push(`${args.runCount} ${args.runCount === 1 ? "change" : "changes"}`);
  if (args.attentionCount > 0) parts.push(`${args.attentionCount} needs attention`);
  if (args.mrLabel) parts.push(args.mrLabel);
  return parts.join(" · ");
}

/* -------------------------------------------------------------- file impact */

export interface FileStat {
  path: string;
  /** null = binary file (numstat "-") or unparseable (truncated diff). */
  additions: number | null;
  deletions: number | null;
}

export interface FileGroup {
  name: string;
  files: FileStat[];
  adds: number;
  dels: number;
}

export interface ProjectDiffLike {
  diff: string;
  files: string[];
  stats?: FileStat[];
}

/** Per-file stats: server --numstat when present (authoritative, accurate even
 *  when the text diff is truncated), else parsed from the diff text with an
 *  honest `partial` flag under truncation. */
export function fileStats(diff: ProjectDiffLike): { stats: FileStat[]; partial: boolean } {
  if (diff.stats && diff.stats.length > 0) {
    return { stats: diff.stats, partial: false };
  }
  const parsed = parseDiff(diff.diff).filter((f) => f.path);
  const byPath = new Map(parsed.map((f) => [f.path, f]));
  const listed = diff.files.length > 0 ? diff.files : parsed.map((f) => f.path);
  const stats = listed.map((path) => {
    const p = byPath.get(path);
    return p
      ? { path, additions: p.adds, deletions: p.dels }
      : { path, additions: null, deletions: null };
  });
  return { stats, partial: isTruncatedDiff(diff.diff) };
}

export function groupFilesByFolder(stats: FileStat[]): FileGroup[] {
  const groups = new Map<string, FileGroup>();
  for (const s of stats) {
    const slash = s.path.indexOf("/");
    const name = slash === -1 ? "(root)" : s.path.slice(0, slash);
    let g = groups.get(name);
    if (!g) {
      g = { name, files: [], adds: 0, dels: 0 };
      groups.set(name, g);
    }
    g.files.push(s);
    g.adds += s.additions ?? 0;
    g.dels += s.deletions ?? 0;
  }
  return [...groups.values()].sort(
    (a, b) => b.files.length - a.files.length || a.name.localeCompare(b.name),
  );
}

/* --------------------------------------------------------------- PM prefill */

function plural(n: number): string {
  return n === 1 ? "" : "s";
}

export function explainChangesPrefill(base: string, fileCount: number): string {
  return (
    `Explain this project's accumulated changes (${fileCount} file${plural(fileCount)} ` +
    `changed vs ${base}). What changed, why, and which backlog items produced it?`
  );
}

export function mergeRiskPrefill(base: string, fileCount: number): string {
  return (
    `Review the merge risk of the accumulated changes vs ${base} ` +
    `(${fileCount} file${plural(fileCount)} changed). What should I double-check ` +
    `before opening or accepting the merge request?`
  );
}

export const AFTER_MERGE_PREFILL =
  "The merge request has been merged. What should we plan or tackle next on this project?";

export function askAboutChangePrefill(run: HistoryRun): string {
  return `Regarding the change "${run.task}" (run ${run.id}): `;
}

/** Request-edits handoff mirrors the backlog one: full context, empty sections
 *  omitted, ends ready for the user's own words. */
export function requestChangeEditsPrefill(run: HistoryRun, item?: BacklogItem): string {
  const parts = [`The change "${run.task}" (run ${run.id}) needs edits before I can merge it.`];
  if (item) parts.push(`It was produced for backlog item "${item.title}".`);
  if (run.tests_passed === false) parts.push("Its validation run failed.");
  parts.push("Requested changes:\n");
  return parts.join("\n\n");
}
