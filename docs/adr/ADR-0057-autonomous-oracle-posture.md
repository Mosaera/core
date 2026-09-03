# ADR-0057: The autonomous oracle posture — activate the full independent oracle (#52, arc #43)

- Status: accepted
- Date: 2026-07-18
- Owners: Mosaera core
- Related issue: #52 (oracle gap) — arc #43; blocked-by #51 (thrash reducer, ADR-0056)
- Related threat model: TM-0001 (updated — the autonomous delivery path)
- Red-team: **DONE** (2026-07-18, 3 refute-agents; 3 FIX-NOW fixed + re-verified; STOP-rule tripped on the MCB-09 class → escalated to the successor; see §Red-team)

## Context

The reliability scoreboard's persistent `false_ship` is **MCB-09** — a *bug fix* on lines the seed
tests **execute but do not assert** (they run `merge()` but never hit the touching/unsorted cases the fix
concerns). Tracing the oracle produced two decisive facts that reshaped the plan:

1. **Deterministic coverage + mutation alone does NOT fix it, and is net-negative.** Change-coverage
   *credits* MCB-09 (the lines are executed); the single mutation-check is *fooled* (flipping the fixed
   `<=` is caught by an unrelated overlapping-intervals test, so it "vouches" for a suite that never
   asserts the fix). And default-on coverage would **park the currently-correct MCB-10 delivery** (its new
   methods are uncovered → credit denied) — a delivery regression with no false-ship fixed.
2. **The durable fix is an independent *asserting* oracle — the Proctor** (ADR-0020), which authors a test
   asserting the actual required behavior. It is **already ON for real autonomous API runs** (via
   `_verify_overlay`) but the **benchmark runs it OFF** — so the 91.7% baseline measured a *weaker oracle
   than what ships*. Coverage / mutation / gap-fill are deterministic *supports* (coverage+gap-fill turn
   uncovered-new-behavior into a covered deliver; mutation downgrades rubber-stamps), not the fix alone.

So the durable oracle is the **Proctor's authored asserting test, backed by the deterministic supports** —
and the real gap is that this posture wasn't the *measured* one.

## Decision

**Owner decisions:** (1) **layered OR-oracle** — keep the gate's existing OR structure and ACTIVATE the
supports (do NOT switch to a hard-gate); (2) **autonomous-only** — guided runs keep a human backstop at
the gate and skip the extra cost. This makes #52 **enable-not-rewrite + measurement-fidelity**, not a gate
rewrite.

- **`apply_oracle_posture(settings) -> Settings`** (`packages/core/mosaera_core/config/_posture.py`,
  re-exported from `config`). When `settings.autonomous_verified` (default True), `replace` sets the full
  stack: `tester_enabled`, `reason_on_stall_enabled` (ADR-0020) **plus** `oracle_coverage`,
  `oracle_mutation_check`, ~~`coverage_gap_fill`~~ (#52; **corrected 2026-08-18**, `docs/audits/adr-corpus-review-2026-08-18.md` — gap-fill was pulled from the posture by FN3 below and then DELETED wholesale by ADR-0060; no `coverage_gap_fill` knob exists). Identity (the same object) when
  `autonomous_verified` is off — the deterministic-baseline opt-out. Idempotent (all-True).
  - **Home = the config layer**, because BOTH the API overlay and the *benchmark* (which lives inside
    `mosaera_core`) import it, and the layer guard forbids `core → mosaera_api`. It is NOT in `build_graph`
    (that is `#51`'s *universal* seam; this is caller-applied, autonomous-only).
- **`_verify_overlay` (apps/api) delegates to it** — an autonomous run now gets the full oracle, not just
  tester+reason. Guided (`req.autonomous` False) untouched.
- **The benchmark applies the same function** (`bench/cli.py`), so the scoreboard measures the *exact
  production autonomous posture* — one shared helper means scoreboard and production can't drift.
  `MOSAERA_AUTONOMOUS_VERIFIED=0` reproduces the pre-#52 all-off baseline (the A/B lever).
- **No gate / oracle / policy / graph edit.** The OR-oracle (`oracle_verified = tester_vouched OR
  standing_suite_is_independent_oracle(…covered…) OR test_cmd, AND tests_mutation_caught is not False`,
  `graph/nodes_review.py:198-219`) and every support (coverage/mutation in `test_node`, the gap_fill
  node/route) are already wired behind the five knobs. #52 only flips them on for autonomous.

## Options considered

- **Layered OR-oracle, autonomous-only (chosen).** The Proctor authors the asserting test; coverage+gap-fill
  convert uncovered-new-behavior into a covered deliver; mutation downgrades rubber-stamps. Preserves
  delivery (authored tests let correct work ship *verified*, not parked).
- **Deterministic coverage+mutation only.** Rejected by the trace — doesn't catch MCB-09 (executed-but-
  unasserted) and parks correct additive work (MCB-10) with nothing to author the covering test. Net-negative.
- **Proctor-hard-gate** (require an independent asserting suite to ship; drop the import-heuristic fallback).
  The stronger correctness bar, but parks any change the oracle can't vouch → lower delivery on hard cases,
  more model-dependent. Deferred as a possible future strictness tier (could scale with the #51 sensitivity
  dial).
- **Global default (all runs).** Rejected — guided runs have a human backstop, so paying the extra LLM +
  sandbox cost buys no safety there.

## Security implications

Deny-by-default is fully preserved — the supports only ever *withhold* trust (downgrade), never add it; the
Proctor authoring the spec-derived asserting test is the sole positive-evidence addition, and it is guarded
by the RED-phase + the assertion floor + the mutation check. The change **enables existing, red-teamed
machinery** (ADR-0020, ADR-0044, ADR-0049) for the autonomous path; it edits no gate/policy/oracle logic.
The residual false-ship surface (below) is one-sided (a weak oracle *withholds* a park it should have made)
and is the red-team scope, not a new trust hole. → TM-0001.

## Red-team (DONE — 2026-07-18, definition-of-done gate)

**Scope card:** target = this MR (the posture wiring). Durable load-bearing, but the MCB-09 residual *class*
has a planned successor (a Proctor-hard-gate / stronger mutation-coverage oracle) → that class DEFERS.
3 refute-agents ran distinct lenses (wiring holes / false-ship-despite-posture / safety regressions).

**3 FIX-NOW (fixed + re-verified in the follow-up commit):**
- **FN1 — Resume strips the posture (HIGH, wiring).** `rehydrate` (`app_context/_rehydrate.py`) rebuilt the
  graph from a `RunSubmit` with `autonomous` unset, so `_verify_overlay` stripped the whole oracle stack on
  restart while the run still auto-approved — an oracle-denied park could flip to an auto-ship. **Fixed:**
  thread `autonomous=autonomous` into the rebuild `RunSubmit` + a regression test. (Pre-existing since
  ADR-0020; #52 made it materially worse by adding the coverage-denied→ship flip.)
- **FN2 — Mutation check crash-to-`error` (MED, safety).** `suite_catches_a_mutation` was called with no
  `try/except` in `test_node`, unlike its coverage twin (`run_coverage`, hardened against exactly this in a
  prior red-team). A transient sandbox/IO fault during the mutation check ended a deliverable run as
  `status="error"` (diff discarded) instead of a park — against the reliability arc's clean-conclusion goal.
  **Fixed:** wrap the call → `None` (inconclusive, deny-by-default) on any exception.
- **FN3 — gap-fill is a confirmation oracle (MED-HIGH, false-ship).** `coverage_gap_fill` instructs the
  tester to author delta tests that "assert only behaviour the change actually implements" — it RATIFIES the
  delivered (possibly wrong) code, flipping an honest uncovered-PARK into a coverage-credited SHIP. This
  *contradicted* the original R4 disposition (which claimed gap-fill *mitigates*). **Fixed:** removed
  `coverage_gap_fill` from the posture — an uncovered change now parks (deny-by-default); the Proctor's
  red-verified spec test is the delivery path for new behaviour, not a self-confirming delta test.

**DEFER-TO-SUCCESSOR (the MCB-09 class — STOP-rule TRIPPED: it recurred across all three lenses, so it is
inherent to the deterministic OR-oracle and escalates to the successor, not more support-patching):**
- **R1 mutation-caught-but-wrong** + **R2 mutation-inconclusive-on-non-mutable-lines** (`sorted()`/guard/
  helper-call fixes leave no mutable construct) + **R5 weak-Proctor** + the **coverage/assertion-floor
  decoupling** (a non-asserting test supplies coverage while a different test satisfies the floor; no test
  asserts the *required* behaviour): all the same "executed-but-unasserted / weak-authored-oracle" class.
  The durable fix is a **Proctor-hard-gate** (require a red-verified asserting suite to ship) and/or a
  stronger mutation set — the owner-deferred successor. On the reviewer-**silence** path the false credit
  doesn't merely withhold a park — it *manufactures an unattended delivery* (correcting this ADR's earlier
  "one-sided" framing).
- **Non-pytest repos** (SQL/node): the entire oracle stack is pytest-only, so "suite"-strength non-Python
  work over-parks and "shallow"-strength work ships on the reviewer alone — the successor is the **TS/JS +
  SQL language-expansion arc** (the declared build order: Python stable first).

**ACCEPT (documented deny-by-default residuals):**
- **R3 Coverage unavailable → import-heuristic fallback** — the image ships `coverage==7.15.2`; the fallback
  is the exception and errs toward DENY.
- **Mutation-revert bulletproof (verified CLEAN):** the revert is in a `finally` covering every in-process
  path; a restore-failure propagates as an exception → the run never reaches `deliver`. No path ships
  mutated source.
- **SIGKILL mid-mutation** could leave a mutated file on disk that resume adopts as baseline — narrow, and
  self-limiting (a real suite goes red on the mutant → parks). **Mutation cost** (one sandbox run per
  changed source file, uncapped) and the **CLI `--approve-all`** posture-gap are logged as roadmap
  follow-ups (a mutation file-cap; a `--approve-all ⇒ apply_oracle_posture` hook). Guided runs, existing
  guards (tamper, `deliver_unverified`), and the recursion limit were verified un-regressed.

**Verdict:** 3 FIX-NOW fixed + re-verified; the MCB-09 class STOP-rule tripped → escalated to the
Proctor-hard-gate / stronger-oracle successor (do NOT patch the current supports further — the oracle-
heuristic rabbit-hole lesson); non-Python → the language-expansion arc; the rest ACCEPT. Deny-by-default
held throughout — no finding lets the posture *add* trust it shouldn't.

## Operational implications

No new knob and no migration — `apply_oracle_posture` composes the five existing knobs. Default `balanced`
autonomous runs (API) already had tester+reason on; #52 adds coverage+mutation+gap-fill to them.

**Measurement caveat:** the 91.7% baseline had **all five** off, so the re-baseline measures ADR-0020
(tester) + #52 (the three supports) *together*, not #52's marginal delta. A third `MOSAERA_TESTER=1`-only
point isolates the supports. The full-posture bench is **~2× the cost** (per green tree: one Proctor
authoring call + one instrumented coverage run + one mutation run per changed source file, all memoized by
tree hash). Watch for `clean_deliver → honest_park` regressions (a correct case the local-model Proctor
can't vouch).

## Consequences

- **Good:** the benchmark finally measures the real autonomous oracle; the false-ship class gets the
  asserting oracle that is its only durable fix; deny-by-default and the gate logic are untouched.
- **Follow-up:** the red-team disposition (record here); the re-baseline `mosaera-bench --all --compare`
  (repeat=3) + the A/B; a possible Proctor-hard-gate strictness tier scaled by the #51 sensitivity dial;
  a stronger mutation/coverage oracle for R1/R5.
