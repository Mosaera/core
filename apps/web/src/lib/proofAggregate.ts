/* Project-wide proof: what the delivered work actually stands on.
 *
 * The Overview used to draw the latest SETTLED run's radar. On a real project the latest settled
 * run is usually a park where nothing was checked, so the page reported "not-checked" three times
 * over a project whose delivered work was fully checked — a run-level instrument on a project
 * page, fed by the thinnest data in the codebase (measured live 2026-08-22).
 *
 * This aggregates over the run that DELIVERED each item. Remediated parks vanish by construction:
 * an item is represented once, by the attempt that shipped, so eight failed attempts followed by a
 * clean delivery count as one clean delivery. (21% of this instance's parked runs belonged to
 * items that later delivered — noise the old view could not filter.)
 *
 * THREE COUNTING RULES, and the first is the load-bearing one:
 *
 *  1. POSITIVE EVIDENCE ONLY. An axis counts a delivery as proven on a RECORDED verdict, never on
 *     the absence of an objection. 12 of 13 delivering runs on this instance carry an empty
 *     `gate_reasons` list; counting that as proof would paint a perfect score over work that was
 *     never independently verified — green-by-vacancy, a named defect class in this repo. Anything
 *     unrecorded is `unknown`, and `unknown` is never green.
 *  2. COUNTS WITH VISIBLE DENOMINATORS. Every axis reports proven / failed / unknown out of N.
 *     No decimals, no synthesized index, no blended polygon.
 *  3. THE DENOMINATOR IS WHAT WAS MEASURED. Independence denominates over deliveries that recorded
 *     a vouch verdict at all — the field returned "" on every run before 2026-08-13 (it read a
 *     bench-harness key absent from live RunState), so counting those blanks as failures would
 *     blame the engine for an instrument that was not yet wired. They are reported separately. */

import type { BacklogItem, HistoryRun } from "../api/client";

/** The three the RUN LIST can answer, plus the three that live only inside a sealed receipt and
 *  therefore arrive from the server-side aggregate (ADR-0109). One union so both sources render
 *  through the same component and neither can introduce an axis the other has never heard of. */
export type ProofAxisKey =
  | "independence"
  | "checks"
  | "integrity"
  | "review"
  | "security"
  | "proof_depth";

export interface ProofAxis {
  key: ProofAxisKey;
  label: string;
  /** Deliveries this axis could positively verify. */
  proven: number;
  /** Deliveries where the axis recorded a negative verdict. */
  failed: number;
  /** Deliveries with nothing recorded — never counted as either. */
  unknown: number;
  /** proven + failed: the honest denominator ("0 of 8", not "0 of 13"). */
  measured: number;
  /** What the axis means, in the operator's words. */
  note: string;
}

export interface ProjectProof {
  /** Items that have ever delivered — the population every axis denominates against. */
  delivered: number;
  axes: ProofAxis[];
}

/** The run that delivered each item: newest APPROVED attempt, one per item. Ad-hoc runs
 *  (`item_id: null`) are their own unit — they delivered something too. */
export function deliveringRuns(runs: HistoryRun[], _items: BacklogItem[] = []): HistoryRun[] {
  const byUnit = new Map<string, HistoryRun[]>();
  for (const r of runs) {
    const key = r.item_id != null ? `item:${r.item_id}` : `run:${r.id}`;
    byUnit.set(key, [...(byUnit.get(key) ?? []), r]);
  }
  const out: HistoryRun[] = [];
  for (const attempts of byUnit.values()) {
    const delivered = attempts
      .filter((r) => r.status === "APPROVED")
      .sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")));
    if (delivered[0]) out.push(delivered[0]);
  }
  return out;
}

type Verdict = "proven" | "failed" | "unknown";

/** Independence: did anything OTHER than the producer vouch for this delivery?
 *  `vouch` is either a positive vouch string, `no_vouch:<guards>`, or "" (never recorded). */
function independence(run: HistoryRun): Verdict {
  const vouch = String(run.diagnosis?.vouch ?? "");
  if (!vouch) return "unknown"; // instrument absent — not evidence of either answer
  return vouch.startsWith("no_vouch") ? "failed" : "proven";
}

/** Checks: did a real suite run and pass on this delivery? */
function checks(run: HistoryRun): Verdict {
  if (run.validation_status === "pass" && run.tests_passed === true) return "proven";
  if (run.validation_status === "failed" || run.tests_passed === false) return "failed";
  return "unknown";
}

/** Integrity: the run did not edit the tests it was judged by, and the record is sealed. */
function integrity(run: HistoryRun): Verdict {
  if (run.diagnosis?.tests_modified === true) return "failed";
  if (run.diagnosis?.tests_modified === false && run.receipt_id) return "proven";
  return "unknown";
}

const AXES: { key: ProofAxisKey; label: string; note: string; read: (r: HistoryRun) => Verdict }[] =
  [
    {
      key: "independence",
      label: "Independence",
      note: "something other than the producer vouched for it",
      read: independence,
    },
    { key: "checks", label: "Checks", note: "a real test suite ran and passed", read: checks },
    {
      key: "integrity",
      label: "Integrity",
      note: "the run did not edit the tests it was judged by",
      read: integrity,
    },
  ];

export function projectProof(runs: HistoryRun[], items: BacklogItem[] = []): ProjectProof {
  const delivering = deliveringRuns(runs, items);
  const axes = AXES.map(({ key, label, note, read }) => {
    let proven = 0;
    let failed = 0;
    let unknown = 0;
    for (const run of delivering) {
      const v = read(run);
      if (v === "proven") proven += 1;
      else if (v === "failed") failed += 1;
      else unknown += 1;
    }
    return { key, label, note, proven, failed, unknown, measured: proven + failed };
  });
  return { delivered: delivering.length, axes };
}

/** The sentence the page leads with. Independence first, by owner decision — a governance product
 *  that hides its own weakest number is a dashboard. */
export function proofHeadline(proof: ProjectProof): string {
  if (proof.delivered === 0) return "Nothing has delivered yet.";
  const ind = proof.axes.find((a) => a.key === "independence")!;
  if (ind.measured === 0) {
    return `${proof.delivered} delivered · independence not recorded on any of them`;
  }
  return `${ind.proven} of ${ind.measured} deliveries were independently vouched`;
}

/* ------------------------------------------------------------------ how strong is an axis? */

export type ProofTone = "unmeasured" | "strong" | "fair" | "weak";

/** Thresholds, named once. Percentages rather than "any failure at all", because the previous
 *  rule had exactly three states — all proven, none proven, and everything in between — so 24 of 25
 *  and 1 of 25 were painted identically. One imperfect run made an axis look as bad as near-total
 *  failure, which is how a panel stops meaning anything (owner, 2026-08-24).
 *
 *  90% is "strong" rather than 100%: on a project of 25 deliveries a single old run that predates a
 *  control should not repaint the axis, and the count beside every spoke still tells the exact
 *  story for anyone who wants it. */
export const PROOF_STRONG = 0.9;
export const PROOF_FAIR = 0.7;

/** An axis's strength band. `unmeasured` is its own answer and never a colour on the scale —
 *  "nothing was measured" is not a score, and painting it as one is the absence-as-evidence
 *  mistake this aggregate exists to avoid. */
export function proofTone(axis: ProofAxis): ProofTone {
  if (axis.measured === 0) return "unmeasured";
  const share = axis.proven / axis.measured;
  if (share >= PROOF_STRONG) return "strong";
  if (share >= PROOF_FAIR) return "fair";
  return "weak";
}
