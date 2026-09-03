/* Pure derivations for the Delivery tab (ADR-0102 slice P) — the git-delivery
   management surface. Every value traces to a real API field; the readiness
   verdict itself comes from lib/changes deriveReadiness (one source of truth).
   Unit-tested in delivery-lib.test.ts. */

import type { BacklogItem, Project } from "../api/client";
import type { BranchStanding } from "../api/delivery";
import type { ReadinessState } from "./changes";

/* ---------------------------------------------------------------- readiness */

/** Plain sentence per readiness state — the pipeline header's verdict line. */
export const READINESS_PLAIN: Record<ReadinessState, string> = {
  merged: "Merged — the delivered work is on the source repository.",
  "mr-open": "A merge request is open and waiting for a human to merge.",
  "delivered-unpushed":
    "Committed locally — the delivered work is NOT on the remote yet. Open the merge request to push it.",
  blocked: "Delivery is blocked — the latest settled run did not clear the gate.",
  ready: "Ready — accumulated changes can be opened as a merge request.",
  "no-changes": "Nothing to deliver yet — no accumulated changes vs the source.",
  "no-token": "No credential for this provider — connect it under Settings \u2192 Git (or add the project token) to open requests.",
};

/** The remote-sync fact, honestly worded. null/undefined = unknown, never synced. */
export function remoteSyncPlain(synced: boolean | null | undefined): string {
  if (synced === true) return "branch tip is on the remote";
  if (synced === false) return "branch tip is NOT on the remote";
  return "remote sync unknown (offline or no remote)";
}

/** One plain clause for where the branch stands against the base. Fetch-free upstream, so
 *  "behind" may be provable without being countable — say that rather than invent a number, and
 *  never let an unknown read as in-sync (ADR-0102 slice H's rule, extended). */
export function standingPlain(s: BranchStanding | undefined, base: string): string {
  if (!s) return "";
  const n = (c: number | null) => (c === 1 ? "1 commit" : `${c} commits`);
  switch (s.state) {
    case "in_sync":
      return `even with ${base}`;
    case "ahead":
      return `${n(s.ahead)} ahead of ${base}`;
    case "behind":
      return s.ahead
        ? `${n(s.ahead)} ahead, ${n(s.behind)} behind ${base} — diverged`
        : `${n(s.behind)} behind ${base}`;
    case "behind_unknown":
      return `behind ${base} by an unknown amount (the clone hasn't fetched since it moved)`;
    case "no_remote_base":
      return `${base} does not exist on the remote`;
    case "no_remote":
      return "no remote configured";
    default:
      return `standing vs ${base} unknown (offline or a git fault)`;
  }
}

/* -------------------------------------------------------------- item MR rows */

export interface ItemMrRow {
  id: number;
  position: number;
  title: string;
  /** The backlog status (todo | in_progress | in_review | done | deferred). */
  status: string;
  branch: string;
  /** The branch this MR targets, as RECORDED by the server (0028). */
  mrTarget: string;
  mrUrl: string;
  /** "" (never opened) | opened | merged | closed — the polled MR state. */
  mrState: string;
  /** Delivered, and no MR opened yet (no url AND no branch marker) → Open MR. */
  canOpen: boolean;
}

/** One row per backlog item, position order, MR facts folded in. `statusItems`
 *  (the live poll) overrides the stored `mr_state` so the page reflects the
 *  freshest read without waiting for the next project refetch. */
export function itemMrRows(
  backlog: BacklogItem[],
  statusItems?: { id: number; state: string | null }[],
): ItemMrRow[] {
  const polled = new Map((statusItems ?? []).map((s) => [s.id, s.state]));
  return [...backlog]
    .sort((a, b) => a.position - b.position || a.id - b.id)
    .map((i) => {
      const delivered = i.status === "in_review" || i.status === "done";
      const mrUrl = i.mr_url ?? "";
      const branch = i.branch ?? "";
      return {
        id: i.id,
        position: i.position,
        title: i.title,
        status: i.status,
        branch,
        mrUrl,
        mrTarget: i.mr_target ?? "",
        mrState: polled.get(i.id) ?? i.mr_state ?? "",
        canOpen: delivered && !mrUrl && !branch,
      };
    });
}

/** The header's mono summary: honest counts, empty parts omitted. */
export function deliverySummary(rows: ItemMrRow[]): string {
  const opened = rows.filter((r) => r.mrState === "opened" || (r.mrUrl && !r.mrState)).length;
  const merged = rows.filter((r) => r.mrState === "merged").length;
  const openable = rows.filter((r) => r.canOpen).length;
  const parts: string[] = [];
  if (merged > 0) parts.push(`${merged} merged`);
  if (opened > 0) parts.push(`${opened} MR${opened === 1 ? "" : "s"} open`);
  // "deliverable without an MR" read as UNDELIVERED, and it is not. Item branches STACK: an item
  // can have no MR of its own while its commits are already on the base, because a later item's MR
  // carried them. The live page said "16 deliverable without an MR" over work that had merged hours
  // earlier (2026-08-24). The arithmetic was right; the words were a claim the row cannot support.
  // Say what is actually counted. Real containment — is this item's commit an ancestor of the base?
  // — needs a REST read per item and a staleness story, and is tracked separately.
  if (openable > 0) parts.push(`${openable} without their own MR`);
  if (parts.length === 0) parts.push("no item MRs yet");
  return parts.join(" · ");
}

/** The pause note IS drift when the launch refused a stale base (slice D). */
export function driftNote(projectError: string | null | undefined): string | null {
  const err = (projectError ?? "").trim();
  if (!err) return null;
  return /base drift/i.test(err) ? err : null;
}

/* ------------------------------------------------------- MR compose prefill */

/** The prefilled draft for a project-wide ("combined") merge request. Lives here because BOTH the
 *  Delivery tab and the Changes merge bar open the same compose sheet for the same API call — when
 *  this was inlined in Delivery, Changes had no review step at all and pushed on one click. */
export function projectComposeDraft(project: Project, base: string) {
  return {
    kind: "project" as const,
    title: `mosaera: ${project.name}`,
    body: project.brief || `Combined delivery for ${project.name}.`,
    target: base,
    squash: false,
    removeSource: true,
  };
}

/** Items whose OPEN merge request points at a branch that no longer exists — GitLab shows
 *  "The target branch X does not exist" and the MR cannot merge. Only decidable when the branch
 *  list is authoritative: the clone-sourced fallback never lists mosaera/* at all, so a missing
 *  name there proves nothing and we return none rather than cry wolf. */
export function stuckItems(
  rows: ItemMrRow[],
  branches: { name: string }[],
  branchSource: string | undefined,
): Map<number, string> {
  const out = new Map<number, string>();
  if (branchSource !== "gitlab") return out;
  const live = new Set(branches.map((b) => b.name));
  for (const r of rows) {
    if (r.mrState === "opened" && r.mrTarget && !live.has(r.mrTarget)) {
      out.set(r.id, r.mrTarget);
    }
  }
  return out;
}

/* ------------------------------------------------------- MR mergeability (ADR-0102 amendment) */

/** What the confirm modal may offer. `auto-merge` is GitLab's own merge-when-pipeline-succeeds. */
export type MergeOffer = "merge" | "auto-merge" | "none";

export interface Mergeability {
  /** True ONLY when GitLab says the MR is mergeable right now. */
  ready: boolean;
  /** One plain sentence naming the state — the operator's whole answer. */
  headline: string;
  offer: MergeOffer;
  /** GitLab's own token, always carried so the sentence can be reconciled against the source. */
  raw: string;
}

/* GitLab's `detailed_merge_status` (15.6+). Deliberately a TABLE, one edit from the type, for the
   reason ADR-0090 gives about `REASON_CLASS`: a privately-held list of "the bad ones" goes stale
   the moment the vocabulary grows, and the direction it goes stale in decides whether an operator
   is shown a green button over an unchecked claim. */
const _MERGE_STATUS: Record<string, { headline: string; offer: MergeOffer }> = {
  mergeable: { headline: "Ready to merge.", offer: "merge" },
  ci_still_running: { headline: "The pipeline is still running.", offer: "auto-merge" },
  ci_must_pass: { headline: "The pipeline has not passed.", offer: "none" },
  conflict: { headline: "Conflicts with the target branch.", offer: "none" },
  need_rebase: { headline: "Needs a rebase — conflicts with the target branch.", offer: "none" },
  discussions_not_resolved: { headline: "Unresolved discussions on the merge request.", offer: "none" },
  draft_status: { headline: "Still marked a draft.", offer: "none" },
  not_approved: { headline: "Required approvals are missing.", offer: "none" },
  blocked_status: { headline: "Blocked by another merge request.", offer: "none" },
  broken_status: { headline: "GitLab cannot merge this branch.", offer: "none" },
  not_open: { headline: "This merge request is not open.", offer: "none" },
  checking: { headline: "GitLab is still checking whether this can merge.", offer: "none" },
  unchecked: { headline: "GitLab is still checking whether this can merge.", offer: "none" },
};

/** GitLab's mergeability verdict, in words, with what may be offered on it.
 *
 *  FAILS TOWARD NOT-READY, always. An unrecognised status quotes GitLab verbatim and offers
 *  nothing: the vocabulary grows server-side, and the tempting bug — treat anything not obviously
 *  blocked as mergeable — is how a green "Ready to merge" ends up in front of an operator on
 *  evidence nobody checked. An absent status is not permission either. */
export function mergeability(status: string | null | undefined): Mergeability {
  const raw = (status ?? "").trim();
  if (!raw) {
    return {
      ready: false,
      headline: "GitLab has not said whether this can merge.",
      offer: "none",
      raw: "",
    };
  }
  const known = _MERGE_STATUS[raw];
  if (!known) {
    return { ready: false, headline: `GitLab reports "${raw}".`, offer: "none", raw };
  }
  return { ready: known.offer === "merge", headline: known.headline, offer: known.offer, raw };
}
