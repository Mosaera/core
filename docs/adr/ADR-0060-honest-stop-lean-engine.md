# ADR-0060: The honest-stop — a progress breaker that CONCLUDES, and the lean engine (#56, arc #43)

- Status: accepted (**amended 2026-08-02 by
  [ADR-0077](ADR-0077-language-native-convergence-signal.md)** — the no-count branch)
- Date: 2026-07-19
- Owners: Mosaera core

> **Amendment (2026-08-02, ADR-0077 / `#81`).** This ADR deliberately left the *uncountable*
> validation branch as a fingerprint stall bucketed `thrash_park`, reasoning that with no count
> signal a relabel would only flatter the metric. That reasoning rested on an implicit premise —
> **that no language could count** — which ADR-0077 removes by giving SQL and Node real counts via
> `LanguagePack.interpret`. For the genuinely-uncountable residual, ADR-0077 lets the trip climb
> this ADR's own reason → supervise ladder, on the same evidential standard: the trip fires only
> after real fix iterations, the give-up lands strictly below the cap, and the reason names a
> concrete failure signature. **Rode-to-cap is still thrash** — that part of this ADR is unchanged.
- Related issue: #56 (honest-stop / lean engine) — arc #43; successor to #51 (ADR-0056) / #54 (ADR-0058) /
  #55 (ADR-0059)
- Related threat model: TM-0001 (updated — the arc ships NO trust-surface change; the demotion was
  considered, red-teamed, and DEFERRED)
- Red-team: **DONE** (the *proposed* Phase-3 oracle demotion, 1 agent, claim A) — the verdict is exactly
  why the demotion was **dropped from this arc**; see §Decision 4 and §Red-team disposition. The shipped
  change (honest-stop + lean deletions) is **not** a trust-boundary change (no red-team required).

## Context

The full-posture re-baseline measured **thrash_park ≈ 46%** and a 5-agent engine deep-dive (2026-07-18)
found the root shape: the engine had **seven mechanisms that BOUND a non-converging loop and zero that
CONCLUDE one**. Every breaker (stall fingerprint, plan-stall, repeat-limit, sub-caps, iteration cap)
limits how long the grind runs, then the run parks at a cap and the honest classifier (ADR-0053)
correctly scores it thrash. Worse, the **supervise give-up set `stalled=True`** — so even a coder
hand-raise the engine *believed immediately* classified as thrash. The external evidence agrees: every
leading SWE agent (SWE-agent, OpenHands, Aider, Agentless, Cursor, Claude Code) runs one loop with one
cap; the neutral leaderboard study (arXiv 2506.17208) finds no correlation between orchestration
complexity and performance. Meanwhile the verification research (EvilGenie, PatchDiff, SpecBench, the
mutation-vs-coverage literature) ranks the **held-out spec-derived test** and **test-integrity guard** as
the load-bearing oracle layers, and per-run coverage %-gating / broad mutation as cost without matching
evidence.

The owner's directive: *"if it can't do something it should be honest and flag it right away — so
supervise kicks off."* This arc builds exactly that mechanism, consolidates the breaker pile into it,
and deletes dead mechanism — **without touching the reliability classifier** (metric integrity: the runs
stop honestly *before* the thrash signals fire; thrash is never redefined). A proposed oracle *demotion*
(cost) was built, red-teamed, and reverted (§Decision 4) — the oracle keeps its full strength, so this
arc makes no trust-boundary change.

## Decision 1 — the progress breaker (the honest-stop)

A **deterministic, best-so-far failing-count tracker** in the test loop (`progress.bump_progress`,
consumed in `test_node`):

- **Signal:** `parse_failing_count` (#55) on every failing validation. **Best-so-far, not prev-vs-now**:
  an attempt counts as progress only when it beats the best count ever seen this episode — so
  oscillation (5→6→5) is correctly a non-converging streak, which both the #55 two-value window and the
  digit-stripped fingerprint miss.
- **K = the existing `stall_limit`** — no new knob; the #51 sensitivity dial scales this breaker for
  free (`cautious` → trip on the 2nd non-improving attempt).
- **Trip ladder, each rung budget-aware** so the eventual give-up ALWAYS lands strictly below the
  iteration cap (the frozen classifier's rode-to-cap check is independent of reasons — a give-up at the
  cap would be thrash, so the ladder never books a rung it can't complete):
  1. **Reason pass** (ADR-0017, posture-ON) — only if a full rung (the pass + up to `stall_limit-1`
     fixes) still concludes below the cap. Streak resets; best survives (a "different approach" must
     still beat the best — it can't change the test population).
  2. **Supervise** (new `test → supervise` edge) with `kind="no_progress"` and the deterministic
     diagnosis: the count trend + the trapping test names (`parse_failing_tests`). Autonomous re-scopes
     once (bounded by `max_escalations`; the re-scope resets the tracker); a breaker-origin re-scope is
     **denied when the remaining budget can't fit another fix cycle** (`budget_short`, breaker-origin
     only — a hand-raise re-scope can succeed with zero fix iterations and is exempt).
  3. **Give-up → `give_up_reason`** — the `plan_unworkable_reason` pattern generalized: an accurate,
     ≤80-char reason (full trend in the gate payload), `stalled` left **False on purpose**, concluded
     strictly below the cap → `classify_outcome` buckets it `honest_park` **by construction**.
- **Give-up honesty applies to ALL supervise origins** — a believed hand-raise ("blocked: …",
  "escalation unresolved: …") is an honest conclusion too; the three flipped integration tests' own
  comments ("believed immediately — did not loop to the cap") were already the honest_park spec.
- **Unparseable validation output** (non-pytest) keeps the pre-#56 fingerprint-stall path byte-for-byte;
  at/over the cap the honest window is closed and the stall park stands (rode-to-cap IS thrash).
- **Escalation continuity:** a give-up park still carries `validation_failed` in the gate reasons, so
  `diagnose_bottleneck` names the coder and the ADR-0016 model-escalation re-run fires on exactly these
  honest parks — the honest-stop is what makes escalation cheap (park fast, retry stronger).
- The bench harness `_resolve` now resumes escalation interrupts with the API runner's autonomous
  re-scope semantics **explicitly** (it previously worked by an accidental fall-through) — the matrix
  runs measure production behavior.

## Decision 2 — consolidation (subsume, don't add)

| Mechanism | Verdict |
|---|---|
| test-kind `_stall_bump` on parseable output | **SUBSUMED** — skipped; the progress breaker is a strict superset at the same threshold with a better destination |
| test-kind `_stall_bump` on unparseable output | **KEPT** as the fallback (today's semantics; relabeling it is a measured follow-up, not this arc) |
| `coder_test_repeat_limit` | **KEPT** — the intra-session token guard that produces the hand-raise |
| hygiene / review `_stall_bump` | **KEPT** — no count signal exists for lint findings / reviewer verdicts |
| plan breaker (`plan_stall_limit`) | **KEPT** — earlier and cheaper than any supervise path |
| sub-caps (hygiene/review/quality) | **KEPT** — loop bounds, not convergence detectors |

Net: **no new budgets, no new knobs**; two knobs deleted (below); RunState net −1 field.

## Decision 3 — deletions (the lean engine)

- **`gap_fill` (full subsystem):** node + route + gapcov memo + instruction + 3 state fields + knob +
  the `uncovered_executable` helper. The #52 red-team had already excluded it from the posture as a
  *confirmation oracle* (it ratifies delivered code); default-OFF made it dead weight in the measured
  config.
- **`react_on_bad_test`:** an LLM call with zero write authority and zero routing effect that only
  reworded a park message. The honest-stop's deterministic diagnosis (failing-test names + count trend,
  on EVERY park, at zero model cost) is equal-or-better. The lost "suspected-bad-test vs coder-limited"
  judgment → **DEFER-TO-SUCCESSOR** (dynamic per-test verification): the up-front `tester_repairs_tests`
  path still handles the bad-test class proactively.

## Decision 4 — oracle demotion: CONSIDERED, red-teamed, and DEFERRED

The verification research suggested demoting the per-run cost layers (coverage %-gating out of the
posture; the mutation check scoped to proctor-edited runs only) as "cost without matching evidence."
This was **built, red-teamed, and then reverted** — a lead-engineering call under the arc's
correctness-first mandate.

**Why deferred (the red-team, claim A, 1 agent):** the refuter reproduced end-to-end, against the real
production functions, that the demotion **reopens a park→ship channel the pre-demotion system catches**:
a standing/authored suite that EXECUTES but does not ASSERT a changed line (the executed-but-unasserted
class). Pre-demotion, coverage (`covered=False`) AND the mutation check (survived → `False`) each parked
it; post-demotion, coverage falls back to the module-level import heuristic (over-credits) and the
mutation check never runs on the common path, so on the reviewer-silence backstop the run **flips
park→approve and ships wrong code**. Critically, the refuter showed this path fires **more broadly than
"Proctor flake"**: every gate-deny re-plan re-authors the acceptance suite against the coder's on-disk
implementation (so it can never be red → `tester_vouched` False at the second gate visit), leaving the
standing credit as the only oracle — with no change-level check after demotion.

The demotion's only benefit is **cost** (skipping a coverage run + per-changed-file mutation runs on
green trees). Trading a demonstrated correctness signal for cost, immediately before a benchmark that
measures correctness, is exactly the "short-term convenience over correctness" the mandate forbids — and
the reopened class had **already tripped the STOP rule in the #52 red-team** (it has now recurred across
consecutive red-teams). So the oracle stays at **full strength** (`oracle_coverage` + unscoped
`oracle_mutation_check` in the posture, 5 knobs), and the demotion is **bundled with its successor**: the
dynamic per-test-verification arc, which replaces the coarse executed-but-unasserted signal with a
change-level one — at which point demoting the coarse layers is safe. Logged on the roadmap as a
successor prerequisite. **Net: this arc makes NO trust-boundary change.**

## Decision 5 — the escalation-ON product config (measurement)

The bench's historical `MOSAERA_MODEL_ESCALATION=0` measured the engine with one hand tied: the
field-proven ADR-0016 ladder re-runs exactly the runs that end honestly `incomplete` — which is what the
honest-stop now produces quickly. The re-baseline matrix:

| Run | Config | Repeat |
|---|---|---|
| A | posture, escalation OFF | 3 (comparable headline; false_ship 0-1 gate) |
| B | posture, escalation ON, local+cloud coder/tester ladder | 1 smoke → 3 if the signal holds |

Enable: `MOSAERA_MODEL_ESCALATION=1` + a `MOSAERA_ROLE_ESCALATION` ladder, e.g.
`{"coder": [{"provider":"ollama","model":"qwen3-coder:30b"}, {"provider":"anthropic","model":"<priced
tier>"}], "tester": [...]}`; a cloud tier additionally needs `MOSAERA_ALLOW_CLOUD_EGRESS=1` + the model
in `model_prices` + its API key, else `cloud_tier_allowed` blocks it safely (no spend, tier-0 stands).

## Rejected

- **A new `progress_limit` knob** — `stall_limit` is the same question; a second knob is a second dial
  to mis-set.
- **Routing unparseable-output trips to supervise now** — no count signal means no deterministic
  diagnosis; relabeling that slice without new mechanism would flatter the metric. Measured follow-up.
- **Editing `evaluate_gate` / `packages/policies`** — `give_up_reason` flows around the gate exactly
  like `plan_unworkable_reason`; the trust boundary is untouched.
- **Changing `classify_outcome`** — frozen. Honesty is achieved by stopping earlier with accurate
  reasons, not by redefining thrash.
- **Keeping `react_on_bad_test` behind its knob** — a dead knob is surface area; the deterministic
  diagnosis supersedes it.
- **Demoting the oracle for cost** (coverage out of the posture; mutation proctor-scoped) — built and
  red-teamed, then reverted: it reopens the executed-but-unasserted park→ship channel (§Decision 4).
  Deferred to the dynamic per-test-verification successor, which makes the demotion safe.

## Red-team disposition (the CONSIDERED demotion — 1 verification pass, claim A)

Target = the proposed demotion (commit reverted). **0 FIX-NOW.**

- **CONFIRMED × 2 → the demotion is DROPPED** (not merely deferred as a residual): both confirmed
  instances (standing-suite rubber-stamp loses the mutation downgrade; coverage→import-heuristic
  over-credit) are the executed-but-unasserted class. Rather than ship the demotion and defer the
  reopened class, the decision is to **not ship the demotion** — the oracle keeps its full strength.
  The class-recurrence flag (this class in consecutive red-teams) raises the **dynamic per-test
  verification** successor's priority; the demotion rides with it.
- **FALSE-POSITIVE × 1:** resume/rehydrate `proctor_edits` loss — `proctor_edits` is a declared,
  checkpointed key and `_rehydrate` reapplies the posture (the #52 FN1 fix); the failure direction was
  fail-safe (park, never ship) even in the hypothetical loss.

The honest-stop + lean deletions (what ships) add no trust surface: `give_up_reason` flows around
`evaluate_gate` exactly like `plan_unworkable_reason`, a tampering run can never reach the supervise
re-scope (tamper sets `stalled` and returns early), and both deleted features were opt-in and
non-load-bearing.

## Consequences

- Knobs: removed `coverage_gap_fill`, `react_on_bad_test`; posture **6 → 5** (the coverage/mutation
  demotion was reverted). RunState: added `progress_track` / `progress_trip` / `give_up_reason`; removed
  `uncovered_changed_lines` / `gap_fill_attempts` / `gap_fill_log` / `test_review_needed`.
- Three integration tests flipped as genuine spec changes (supervise give-up → honest); the classifier
  tests untouched.
- `_termination_reason` order: `plan_unworkable_reason` → `give_up_reason` → stalled → gate reasons.
- The re-baseline numbers land in CHANGELOG 0.6.0 with the benchmark snapshot (ADR-0055).
