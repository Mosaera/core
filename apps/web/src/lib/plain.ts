import { fmtDuration } from "./duration";

/* The copy deck: THE single source of operator-facing language for the run pages —
   and, since the PM chat began naming the same failure causes, for that surface too.
   Data modules (lib/ledger.ts, lib/runs.ts) keep engine semantics; components come
   here for words. The operator is not an engineer — every string must read in plain
   English while still conveying what the system actually proved.

   Honesty rules the words must never soften: a claim that couldn't be checked is
   never called verified; "not measured" is never a verdict; a delivery over
   warnings says so. Unit-tested exhaustively in plain.test.ts. */

import type { RunDiagnosis } from "../api/client";

export type Tone = "success" | "amber" | "destructive" | "muted";

/* -------------------------------------------------------- gate reason tokens */

/** Every reason the delivery checkpoint can raise.
 *
 *  TOTAL over `mosaera_policies.gate.GateReason` — enforced by a Python-side test
 *  (`test_gate_reason_classification.py`) that parses this object's keys and compares them to the
 *  Literal. The count is deliberately not written here: it drifted (the comment said 13 while the
 *  Literal had 14, so `validation_not_attempted` rendered to operators as raw jargon via the
 *  fallback below for six days, and the TS-side test enumerated the same stale 13 so nothing
 *  failed). A TS enumeration of a Python vocabulary is a second origin by construction. */
export const GATE_REASON: Record<string, string> = {
  validation_failed: "the automated checks failed",
  validation_unavailable: "no automated checks could run",
  validation_not_attempted: "no checks were attempted — the run never reached validation",
  tests_tampered: "the run modified the tests it was judged by",
  content_destroyed: "the run emptied a file instead of deleting it — nothing proved it should go",
  reviewer_requested_changes: "the reviewer asked for changes",
  reviewer_blocked: "the reviewer blocked delivery",
  reviewer_conflict: "the reviewers disagreed",
  reviewer_unknown: "the reviewer's verdict couldn't be read",
  security_findings: "the security scan found problems",
  security_unverified: "the security scan couldn't check this change",
  security_not_attempted: "the run ended before the security scan could run",
  security_stale: "the code changed after the security scan — this version wasn't scanned",
  reviewer_stale: "the code changed after the review — this version wasn't reviewed",
  oracle_unverified: "the work couldn't be independently verified",
  critic_vetoed: "the independent checker vetoed delivery",
  unsatisfied_claim: "not every claim was verified",
  claim_behavioral_failed: "the change did not do something the item asked for",
  claim_structural_failed: "the code is not shaped the way the item asked for",
  claim_integrity_failed: "a claim about not touching the tests was broken",
  impact_unassessed:
    "this changes existing behaviour and nothing checks who depended on it",
  removal_unproven:
    "the removal could not be proven safe — something may still use what was removed",
  iteration_limit: "the revision limit was reached",
};

export function gateReason(token: string): string {
  return GATE_REASON[token] ?? token.replace(/_/g, " ");
}

/* ------------------------------------------------------------- claim checks */

/** What kind of check stands behind a claim (mosaera_core.claims ORACLE_KINDS).
 *
 *  F67: the first three DO NOT name a check of their own. `claim_oracles.evaluate_claims`
 *  collapses acceptance_test / validation_exit / wellformedness_parse into the SINGLE whole-run
 *  `tests_passed` boolean — measured on a real delivery, six claims all resolved to one shared
 *  `oracle_ref: "validation pipeline passed"`. So a green suite marks every one of them
 *  satisfied whether or not any test exercises that particular criterion.
 *
 *  These strings used to imply per-criterion verification — `wellformedness_parse` rendered as
 *  "checked by a syntax check", which was wrong in BOTH directions: no syntax check ran, and the
 *  suite that did run does not check that criterion specifically. They now say what is true.
 *  Only `tests_unmodified` and `ast_transformation_contract` carry a specific, named ref. */
export const ORACLE_KIND: Record<string, string> = {
  acceptance_test: "covered by the run's whole suite passing",
  validation_exit: "covered by the run's whole suite passing",
  wellformedness_parse: "covered by the run's whole suite passing",
  tests_unmodified: "checked by leaving the tests untouched",
  ast_transformation_contract: "checked by a code-structure rule",
  none: "no check attached",
};

export function oracleKind(kind: string): string {
  return ORACLE_KIND[kind] ?? kind.replace(/_/g, " ");
}

/** Per-claim verdicts, honestly labeled: a claim with no check is NEVER "verified". */
export const CLAIM_VERDICT: Record<string, { label: string; tone: Tone }> = {
  satisfied: { label: "verified", tone: "success" },
  failed: { label: "failed", tone: "destructive" },
  unbound: { label: "no way to check it", tone: "muted" },
  unevaluable: { label: "couldn't be checked", tone: "muted" },
};

export function claimVerdict(v: string): { label: string; tone: Tone } {
  return CLAIM_VERDICT[v] ?? { label: v, tone: "muted" };
}

/** Where a claim came from (owner-ratified plain pills). material=false wins. */
export const PROVENANCE: Record<string, string> = {
  ENTAILED: "FROM YOUR REQUEST",
  REPOSITORY_INVARIANT: "REPO RULE",
  INFERRED: "SUGGESTED",
};
export const PREFERENCE_PILL = "PREFERENCE";

export function provenancePill(provenance: string, material: boolean): string {
  if (!material) return PREFERENCE_PILL;
  return PROVENANCE[provenance] ?? provenance.replace(/_/g, " ");
}

/* -------------------------------------------------------- reviewer / critic */

export const REVIEWER_VERDICT: Record<string, string> = {
  APPROVE: "approved",
  REQUEST_CHANGES: "asked for changes",
  BLOCK: "blocked delivery",
  CONFLICT: "reviewers disagreed",
  UNKNOWN: "verdict unreadable",
};

export function reviewerVerdict(v: string): string {
  return REVIEWER_VERDICT[v.toUpperCase()] ?? v.toLowerCase().replace(/_/g, " ");
}

/** The backend emits SUPPORTED / INSUFFICIENT_EVIDENCE (critic_policy.py); the UI
 *  previously matched the exact token "INSUFFICIENT" and silently counted zero.
 *  Normalize ONCE, here. */
export type CriticVerdict = "SUPPORTED" | "INSUFFICIENT_EVIDENCE" | "DISCARDED" | "OTHER";

export function normalizeCriticVerdict(v: unknown): CriticVerdict {
  const s = String(v ?? "").toUpperCase();
  if (s === "SUPPORTED") return "SUPPORTED";
  if (s.startsWith("INSUFFICIENT")) return "INSUFFICIENT_EVIDENCE";
  if (s === "DISCARDED") return "DISCARDED";
  return "OTHER";
}

export const CRITIC_VERDICT: Record<CriticVerdict, string> = {
  SUPPORTED: "confirmed",
  INSUFFICIENT_EVIDENCE: "not enough evidence",
  DISCARDED: "set aside",
  OTHER: "unrecognized",
};

/* --------------------------------------------------- validation / sabotage */

/** What a green check run was actually WORTH (ADR-0034). Shallow is never green. */
export const VALIDATION_STRENGTH: Record<string, string> = {
  suite: "a real test suite ran",
  shallow: "only a syntax-level check ran — behaviour wasn't tested",
  none: "no checks ran",
  unknown: "no check plan was recorded",
};

/** The mutation check in plain terms: we deliberately break the delivered code and
 *  see whether the checks notice. Tri-state honest — null is NEVER a verdict. */
export function mutationPlain(v: boolean | null | undefined): { label: string; tone: Tone } {
  if (v === true) {
    return {
      label: "sabotage caught — we deliberately broke the code and the checks noticed",
      tone: "success",
    };
  }
  if (v === false) {
    return {
      label:
        "sabotage missed — we deliberately broke the code and the checks didn't notice (on record)",
      tone: "amber",
    };
  }
  return { label: "sabotage check not run", tone: "muted" };
}

/* ---------------------------------------------------------- honesty badge */

export type HonestyKind = "clean" | "unverified" | "no-claims" | "nothing" | "in-progress";

/** The header verdict, fully plain (owner-ratified). Green ONLY for a delivery
 *  where every material claim was verified — anything less says so in amber. */
export function honestyLabel(kind: HonestyKind, count = 0): { label: string; tone: Tone } {
  switch (kind) {
    case "clean":
      return { label: "EVERYTHING DELIVERED WAS VERIFIED", tone: "success" };
    case "unverified":
      return {
        label: `DELIVERED WITH ${count} UNVERIFIED CLAIM${count === 1 ? "" : "S"}`,
        tone: "amber",
      };
    case "no-claims":
      return { label: "DELIVERED — NOTHING WAS CHECKED", tone: "amber" };
    case "nothing":
      return { label: "NOTHING DELIVERED", tone: "muted" };
    case "in-progress":
      return { label: "STILL RUNNING", tone: "muted" };
  }
}

/** The hero's verdict SENTENCE — same semantics as honestyLabel, spoken quietly.
 *  Green only for "clean"; everything else says exactly what happened. */
export function honestySentence(kind: HonestyKind, count = 0): { text: string; tone: Tone } {
  switch (kind) {
    case "clean":
      return { text: "Every claim that could be checked, was.", tone: "success" };
    case "unverified":
      return {
        text: `Delivered, with ${count} claim${count === 1 ? "" : "s"} that couldn't be verified.`,
        tone: "amber",
      };
    case "no-claims":
      return { text: "Delivered — nothing was checked.", tone: "amber" };
    case "nothing":
      return { text: "Nothing was delivered.", tone: "muted" };
    case "in-progress":
      return { text: "Still running.", tone: "muted" };
  }
}

/** The "why?" explainer behind the badge. */
export const HONESTY_EXPLAINER =
  "This verdict is computed from the record, never asserted. It only reads green when " +
  "the work was delivered AND every claim was verified by the check attached to it. A " +
  "claim that couldn't be checked never counts as verified. Preferences are recorded to " +
  "guide the work but can't block delivery. Every claim below names the check it stands on.";

/* ------------------------------------------------------------ row sentences */

export const SENTENCES = {
  decomposition: (n: number) =>
    `Broken down into ${n} claim${n === 1 ? "" : "s"} — the specific promises this work must keep.`,
  decompositionDraftNote: "(drafted from the request — the run hasn't locked them in yet)",
  runStart: (n: number) => `Work started · ${n} claim${n === 1 ? "" : "s"} to verify.`,
  gateParked: (reasons: string[]) =>
    `Paused for your decision — ${reasons.map(gateReason).join(", ")}`,
  gateOverrideNote: "A person chose to deliver despite these warnings — it's on record.",
  gateAllClear: (approved: boolean) =>
    `Passed the delivery checkpoint${approved ? " · reviewer approved" : ""}.`,
  deliveredClean: "Delivered. Every claim was verified.",
  deliveredNothingChecked: "Delivered — nothing was checked.",
  deliveredUnverified: (n: number) =>
    `Delivered with ${n} unverified claim${n === 1 ? "" : "s"}.`,
  knownGapTitle: "Known gap — accepted on record",
  knownGapNote: "Approving accepts this gap, on record.",
  structuralVouch: (ids: string[]) =>
    `The code's structure was independently verified to match the request (${ids.join(", ")}).`,
  notFound: "This run isn't active and no record of it exists.",
} as const;

export const TERMINATED: Record<string, string> = {
  "NOT APPROVED": "You declined it — nothing was delivered.",
  INCOMPLETE: "Ended without delivering.",
  CANCELLED: "Cancelled — nothing was delivered.",
  ERROR: "Stopped by an error — nothing was delivered.",
};

/* ------------------------------------------------------------ how it ended */

/** Plain readings of the terminal buckets (`bench/reliability.py`). */
export const OUTCOME_PLAIN: Record<string, string> = {
  clean_deliver: "Delivered",
  honest_park: "Stopped honestly, without delivering",
  thrash_park: "Ground to a halt before stopping",
  false_ship: "Delivered work that fails the hidden check",
  crash: "Crashed",
};

/** Why it stopped walking. The gate's reasons say what was missing at the DOOR; these say why the
 *  run stopped. A reader wants this one first, so it is rendered first. */
export const STOP_CHANNELS: { key: keyof RunDiagnosis; label: string }[] = [
  { key: "stall_reason", label: "No convergence" },
  { key: "give_up_reason", label: "Gave up" },
  { key: "plan_unworkable_reason", label: "Plan unworkable" },
  { key: "blocked_reason", label: "Coder blocked" },
  { key: "escalate_reason", label: "Escalated to a human" },
];

/** Plain sentence per park cause (`bench/reliability.py classify_park_cause`).
 *  `stalled:<kind>` is parameterized; an unknown token renders readably, never crashes —
 *  the backend vocabulary can grow (as `under_specified` did). */
const PARK_CAUSE: Record<string, string> = {
  give_up: "The agents concluded they couldn't finish this and stopped honestly.",
  plan_unworkable: "The plan turned out to be unworkable as written.",
  under_specified: "The request was too under-specified to start safely.",
  iteration_limit: "The revision limit was reached before the work could be proven.",
  rode_to_cap: "The run used every allowed revision without converging.",
  parked: "The run parked at the delivery checkpoint for a decision that never delivered.",
};

const STALLED_KIND: Record<string, string> = {
  test: "it was looping on the same failing tests",
  review: "it was looping on the same review feedback",
  hygiene: "it was looping on the same code-hygiene fixes",
  plan: "it was re-planning in circles",
};

/** Causes whose SETTLED wording describes an outcome the run has not reached yet.
 *
 *  `parked` is the whole set today, and it fails twice over at a live pause: "a decision that never
 *  delivered" is a claim about a decision the operator is in the middle of making, and the sentence
 *  is vacuous anyway — the reader is looking at the gate it describes. Found on the deployed build
 *  2026-08-24, on the #108 fix that put this vocabulary in front of a live gate for the first time.
 *
 *  Everything else in `PARK_CAUSE` describes how the run GOT here (under-specified, gave up,
 *  unworkable plan, looping), which is equally true at the pause and afterwards. */
const _SETTLED_ONLY = new Set(["parked"]);

/** The park cause as it reads while the run is STILL ASKING — `""` when the settled sentence would
 *  claim an ending that has not happened, or would only restate the gate the operator is reading.
 *
 *  Deliberately a separate function rather than a flag on `parkCause`: the settled wording is
 *  correct where it is used, and one vocabulary serving two moments is how a true sentence becomes
 *  a false one somewhere else. */
export function livePauseCause(cause: string): string {
  if (_SETTLED_ONLY.has(cause)) return "";
  return parkCause(cause);
}

/** What Quincy is doing right now, in words the operator can read at a glance.
 *
 *  Keyed by the question he asked his own records — the same closed enum the tool accepts. Plain
 *  and specific on purpose: "Checking how this project fails" tells you what is happening,
 *  where "Cogitating…" tells you only that something is. The raw tool call would tell you more
 *  than either and belongs in a log, not in a conversation.
 *
 *  Also the wording that gets STORED with the turn, so the collapsed summary under a finished
 *  reply reads the same as the live line did. */
const PM_STEP: Record<string, string> = {
  open_work: "Checking what's blocked",
  failures: "Checking how this project fails",
  item_history: "Checking which items took several runs",
  criteria_failed: "Checking which acceptance criteria failed",
  orphaned: "Checking for gaps in the record",
};

/** "checked 2 things · 11s" — the disclosure label under a finished reply.
 *
 *  Says how many and how long, and nothing about whether it went well: the reply above says that.
 *  Singular/plural because "checked 1 things" is the kind of small wrongness that makes a person
 *  trust the rest of the screen less. */
export function pmStepsSummary(count: number, seconds: number): string {
  const things = count === 1 ? "1 thing" : `${count} things`;
  return seconds > 0 ? `checked ${things} · ${fmtDuration(seconds)}` : `checked ${things}`;
}

/** The live status line for one step. Falls back to the plain shape of the name rather than
 *  going blank, the same way `parkCause` degrades on a token this build does not know. */
export function pmStep(kind: string, detail = ""): string {
  if (kind === "project_history") return PM_STEP[detail] ?? "Checking this project's records";
  if (!kind) return "Thinking";
  return kind.replace(/_/g, " ");
}

/** Why a PM chat turn did not complete — the operator's reading of the cause token the server
 *  recorded. Keys are `mosaera_agents.pm._planning.fallback_reason`'s closed vocabulary, reused
 *  verbatim rather than re-minted, so the chat and the run pages name the same three things the
 *  same way.
 *
 *  Every sentence obeys the rule `convergence.py` was fixed for: a cause must never blame the
 *  operator for an engine or infrastructure limit. Only `empty` — the honest unknown, where the
 *  model returned nothing and we genuinely cannot say why — may suggest rephrasing. Saying it
 *  after a transport failure sends a human to rewrite a request that was never the problem
 *  (measured on the run path 2026-08-07: it did). */
const PM_TURN_FAILURE: Record<string, string> = {
  model_failed:
    "This turn didn't complete: the model couldn't be reached. Nothing was changed, and nothing you sent was lost. That's an infrastructure failure, not a problem with what you asked.",
  budget_exhausted:
    "This turn didn't complete: Quincy used his whole step budget before writing a reply. Nothing was changed. Raising the budget is the fix — the request is not the problem.",
  empty:
    "This turn didn't complete: the model returned nothing usable. Nothing was changed. Rephrasing the request may help.",
};

/** The sentence for a failure cause — degrading readably on a token this build doesn't know,
 *  the same way `parkCause` does. A cause we cannot explain is still worth showing: "something
 *  went wrong and here is what the server called it" beats a blank row. */
export function pmTurnFailure(cause: string): string {
  if (!cause) return "";
  return PM_TURN_FAILURE[cause] ?? `This turn didn't complete (${cause.replace(/_/g, " ")}). Nothing was changed.`;
}

export function parkCause(cause: string): string {
  if (!cause) return "";
  if (cause.startsWith("stalled:")) {
    const kind = STALLED_KIND[cause.slice("stalled:".length)];
    return kind
      ? `The run stopped making progress — ${kind}.`
      : "The run stopped making progress and the breaker tripped.";
  }
  const known = PARK_CAUSE[cause];
  return known ?? `The run stopped: ${cause.replace(/[_:]/g, " ")}.`;
}

/** The first present out-of-band stop channel — the FULL, uncapped text. */
export function stopReason(d?: RunDiagnosis | null): { label: string; text: string } | null {
  if (!d) return null;
  for (const { key, label } of STOP_CHANNELS) {
    const value = d[key];
    if (typeof value === "string" && value.trim()) return { label, text: value };
  }
  return null;
}

/** One deterministic plain-English sentence (or three) saying how the run ended.
 *  Composed from the record, never asserted — and never a model call. */
export function stopSentence(d: RunDiagnosis): string {
  const parts: string[] = [];
  const outcome = OUTCOME_PLAIN[d.outcome ?? ""];
  if (outcome) parts.push(`${outcome}.`);
  const cause = parkCause(d.park_cause ?? "");
  if (cause) parts.push(cause);
  if (d.tests_modified) parts.push("It also modified the tests it was judged by.");
  if (typeof d.iteration === "number" && typeof d.max_iterations === "number") {
    parts.push(`Stopped at revision ${d.iteration} of ${d.max_iterations}.`);
  }
  return parts.join(" ");
}
