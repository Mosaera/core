/* Item-consolidated run grouping — the fix for "the same run showing incomplete ten times".
 *
 * The Runs page listed ATTEMPTS; the operator thinks in ITEMS. Seven visible rows of one stuck
 * item read as seven problems, and "needs attention: 29" counted imperfect attempts while the
 * overview counted 9 waiting items — two numbers for one truth. Here: the ITEM is the row, its
 * LATEST meaningful attempt is its state, priors collapse behind an expander, and attention
 * counts items.
 *
 * This also retires `groupProjectRuns`' residual-else, which branched on truthy `tests_passed` —
 * the exact tri-state misuse `lib/validation.ts:1` outlaws (null means "never reached tests",
 * not "failed"). Attention now derives from `runOutcome`/`OUTCOME_META`, the honest vocabulary.
 *
 * `lib/changes.ts` has its own (coarser) grouping for the merge-readiness board — do not
 * conflate them; that rule carries over verbatim. */

import type { BacklogItem, HistoryRun } from "../api/client";
import { OUTCOME_META, runOutcome, type RunOutcome } from "./validation";

export interface ItemGroup {
  /** null = an ad-hoc run with no backlog item. NEVER merged by task string — joining runs on
   *  prose would fabricate an identity the record does not contain. */
  item: BacklogItem | null;
  /** Newest first, as the API delivers them. */
  attempts: HistoryRun[];
  /** The attempt that IS the item's state: the newest one, except that a cancelled latest does
   *  not supersede a prior settled attempt — cancelling a stray re-run must not demote a
   *  delivered item. The cancel still shows in history. */
  latest: HistoryRun;
  outcome: RunOutcome;
  /** Default-hidden behind the toggle: every attempt cancelled, or the project is merged. The
   *  record keeps everything; the default view shows what needs a human. */
  archived: boolean;
}

function stateAttempt(attempts: HistoryRun[]): HistoryRun {
  if (attempts.some((r) => r.status === "RUNNING")) {
    return attempts.find((r) => r.status === "RUNNING")!;
  }
  return attempts.find((r) => r.status !== "CANCELLED") ?? attempts[0];
}

export function groupRunsByItem(
  runs: HistoryRun[],
  backlog: BacklogItem[],
  projectMerged = false,
): ItemGroup[] {
  const byItem = new Map<number, HistoryRun[]>();
  const adHoc: HistoryRun[] = [];
  for (const run of runs) {
    if (run.item_id == null) adHoc.push(run);
    else {
      const list = byItem.get(run.item_id) ?? [];
      list.push(run);
      byItem.set(run.item_id, list);
    }
  }
  const groups: ItemGroup[] = [];
  for (const [itemId, attempts] of byItem) {
    const latest = stateAttempt(attempts);
    groups.push({
      item: backlog.find((i) => i.id === itemId) ?? null,
      attempts,
      latest,
      outcome: runOutcome(latest),
      archived: projectMerged || attempts.every((r) => r.status === "CANCELLED"),
    });
  }
  for (const run of adHoc) {
    groups.push({
      item: null,
      attempts: [run],
      latest: run,
      outcome: runOutcome(run),
      archived: projectMerged || run.status === "CANCELLED",
    });
  }
  // Newest activity first — the order the attempts already carry.
  groups.sort((a, b) => runs.indexOf(a.attempts[0]) - runs.indexOf(b.attempts[0]));
  return groups;
}

/** Items (not attempts) whose LATEST state needs a human — the one attention number. */
export function itemsNeedingAttention(groups: ItemGroup[]): ItemGroup[] {
  return groups.filter(
    (g) => !g.archived && g.outcome !== "running" && OUTCOME_META[g.outcome].attention,
  );
}

export function runningItems(groups: ItemGroup[]): ItemGroup[] {
  return groups.filter((g) => g.outcome === "running");
}

export function deliveredItems(groups: ItemGroup[]): ItemGroup[] {
  return groups.filter((g) => !g.archived && g.outcome === "passed");
}

/** Toolbar one-liner in ITEM language; attempts get one honest trailing count. */
export function itemRunsSummary(groups: ItemGroup[], totalRuns: number): string {
  const visible = groups.filter((g) => !g.archived);
  const archived = groups.length - visible.length;
  const parts = [`${visible.length} ${visible.length === 1 ? "item" : "items"}`];
  const running = runningItems(groups).length;
  const attention = itemsNeedingAttention(groups).length;
  const delivered = deliveredItems(groups).length;
  if (running > 0) parts.push(`${running} running`);
  if (attention > 0) parts.push(`${attention} need${attention === 1 ? "s" : ""} attention`);
  if (delivered > 0) parts.push(`${delivered} delivered`);
  if (archived > 0) parts.push(`${archived} archived`);
  parts.push(`${totalRuns} ${totalRuns === 1 ? "attempt" : "attempts"}`);
  return parts.join(" · ");
}

export function summarizeItemsPrefill(groups: ItemGroup[], totalRuns: number): string {
  return (
    `Summarize this project's run history (${itemRunsSummary(groups, totalRuns)}). ` +
    `What did each item accomplish, and what should I look at next?`
  );
}
