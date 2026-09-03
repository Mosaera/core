# ADR-0074: Layer-2 park→ship disposition — close the oracle gap OUTSIDE the graph (#76)

- Status: accepted (built behind a knob, default OFF; **red-team (2 rounds) + bench DoD DONE 2026-07-23**; arc closed)
- Date: 2026-07-22
- Owners: Mosaera core + api
- Related issue: #76 (Quincy-layer post-run disposition; the architectural home for #66's goal) —
  the named successor to the ADR-0070 LLM-judge dead-end, built on the reliability arc's honest-stop
  reasons (#44/#56) and the comprehensive-mutation soundness gate (ADR-0071/#74).
- Related threat model: TM-0001 (the delivery-gate evidence surface — this rung SHIPS code on a
  deterministic verdict, the same boundary the in-graph gate defends).
- Red-team: **required** (a bad authored test that passes wrong code is a `false_ship`). To be run as
  the trust-boundary definition-of-done gate, post-merge, before the next phase builds on it.
- Amended by: [ADR-0093](ADR-0093-mutation-operator-sufficiency.md), [ADR-0094](ADR-0094-eligibility-structural-claim-widening.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.

## Context

The engine (Layer 1) is a reliability machine whose output is a two-symbol contract: `clean_deliver`
OR `honest_park(reason)`. Delivery sits at ~47% — **half of all runs honest-park**, and many of those
are impl-correct code the oracle simply could not INDEPENDENTLY verify. The dominant convertible class
is `oracle_unverified`: a real test suite ran GREEN, but the tests are the coder's OWN — no tester
oracle, no baselined suite the coder can't weaken, no operator `--test-cmd` — so the gate (ADR-0034,
oracle-make-real Phase 3) parks rather than ship on the coder's self-authored green. That park is the
FLOOR, not the win.

The owner insight (2026-07-21): converting `honest_park → clean_deliver` belongs to **Quincy, at the
orchestration layer, OUTSIDE the run graph** — not more nodes/breakers inside `graph/build.py` (that
fights de-god-filing and grows the hottest file). The run concludes, emits its full evidence + the
named unverified blocker, and a Layer-2 rung disposes: **close the named gap deterministically** —
author the missing asserting test for exactly the flagged behaviour, re-run the REAL sandboxed oracle
→ green + mutation-proven ships VERIFIED, anything else stays parked.

**The hard invariant is the ADR-0070 lesson.** A held-out LLM *judge* as the oracle was measured a dead
end: **0 park→ship conversions in 15 runs, `false_ship` 2→3** ("fixing the Proctor's wrong test does not
make correct code ship"). #76 is its named successor: the LLM only AUTHORS a test; the deterministic
**execution + comprehensive mutation** is the sole ship authority — prove the output at the door.

## Decision — a deterministic gap-closer + a sweep rung, default OFF

### Part A — `packages/core/mosaera_core/disposition.py` (the gap-closer, a leaf)

`close_oracle_gap(workspace, sandbox, author_tests, *, acceptance, task, comprehensive=True)` — pure
orchestration of existing primitives, no graph nodes, no `StateGraph` re-run, deny-by-default at every
step (any inconclusive → parked):

1. **Author** a spec-derived asserting test for the item's acceptance (the model's ONLY role, via the
   `AgentsBridge.author_tests` seam). Discover the authored files by the `tests/` before/after
   content-hash diff; only **NEW** files count (editing a baselined test is out of scope — that path is
   the coder-blind `proctor_edits` excuse). None authored → `unavailable`.
2. **Assertion floor** (`oraclecheck.authored_suite_asserts_behaviour`, static AST) — the suite must
   assert real behaviour, not a tautology. Fails → `unavailable`.
3. **Green on the delivered code** (`validation.run_plan`) — the DELIVERED tree passes the independent
   test. Not green → `unverified` (the code is actually wrong — parked, honestly).
4. **Comprehensive mutation** (`mutation.suite_catches_a_mutation(comprehensive=True)`, ADR-0071) — the
   authored suite must CATCH a mutation in EVERY changed non-test region (a second unasserted region
   surfaces a survivor → False; always reverts). This is the red-phase-legitimacy substitute that avoids
   reverting the whole delivered diff. Not caught → `unverified`.

All four pass → `verified` (SHIP). Steps 2–4 are the ship authority; step 1 is the only model call.

### Part B — the sweep rung (`apps/api/mosaera_api/app_context/_escalation.py`)

`_try_close_named_gap(project_id, item, mode, run_id, session, used_settings)` — a new rung in the
`_after` disposition ladder (`_launch.py`), slotted **between** live model escalation (ADR-0022) and
the resilient recurate/defer (ADR-0023); same `(session) -> bool` shape. Gated `mode == "autonomous"`
+ `disposition_gap_close` (new knob, **default OFF**). It:

- Returns False fast unless `session.final` matches the **convertible signal**: the gate reasons, minus
  the benign `iteration_limit`/`reviewer_unknown`, are exactly `{oracle_unverified}` AND `tests_passed`
  is True AND not `tests_modified` AND the held-out critic didn't veto. Every other park (a failed/absent
  validator, tamper, a reviewer/security objection, a critic veto) is NOT convertible and falls through
  unchanged.
- Reopens the parked clone WITHOUT resetting (a park never commits — the delivered diff is still
  uncommitted on disk; the wipe is the NEXT run's reset, so disposition MUST run here, in place), builds
  a standalone tester agent + sandbox (`_open_author_context`, the net-new assembly seam callable outside
  the graph; the tester is forced ON regardless of the run's `tester_enabled`), and calls
  `close_oracle_gap` with `comprehensive=True` unconditionally (the soundness gate).
- `verified` → SHIP in place: `commit_all` the delivered diff + the authored test, mark the item
  `in_review`, open its per-item MR (ADR-0021), advance the sweep — reproducing `deliver_node` +
  the completed-chain path so a conversion is indistinguishable from a clean delivery downstream.
- `unverified` / `unavailable` → return False (fall through to recurate/defer — the honest park stands).

Bounded to one attempt per park (no loop). Best-effort at every step: a setup/commit fault audits and
falls through, never crashes the sweep.

## Rejected

- **An LLM green-light / judge override.** The ADR-0070 dead end. The model authors; deterministic
  execution + comprehensive mutation is the sole ship authority.
- **Reverting the delivered diff to prove a red phase.** Fragile (partial diffs, multi-file changes).
  Comprehensive mutation is the red-phase-legitimacy substitute — it proves the test fails bad code in
  every changed region without touching the delivered tree.
- **Editing a pre-existing baselined test post-park.** The `proctor_edits` excuse is `iteration<=1`
  coder-blind-gated; authoring a NEW file sidesteps it. Editing needs a new sanctioned excuse — out of
  scope.
- **More nodes inside the run graph.** The owner's outside-the-graph mandate: disposition is
  orchestration on top of the reliability machine, not another breaker in the hot file.
- **Other convertible classes** (`validation_unavailable` = nothing ran; `already_satisfied` beyond the
  `oracle_unverified` subset) — after the MVP measures.

## Consequences

- New leaf module `disposition.py` (core, no upward imports); new knob `disposition_gap_close` (default
  OFF) across `_knobs.py`/`_settings.py`/`settings_store.py` + an Autonomy toggle. No new RunState, no
  migration, no `packages/policies` touch.
- **Metric:** Layer-2 **conversion rate = verified-ships / `oracle_unverified`-parks**. Layer-1
  reliability (`1−(thrash+false_ship+crash)`) is unchanged — the gate remains the sole ship authority, so
  a false conversion would surface as a `false_ship` the hidden grader catches, not as a reliability
  regression this rung can hide.
- **The `false_ship` hole** (floor + green + comprehensive-mutation all pass but the behaviour is still
  wrong) is bounded by: green proves the independent test passes; comprehensive mutation proves the test
  fails bad code in EVERY changed region (inherits ADR-0071's soundness incl. the no-op operator);
  the floor rejects tautologies; deny-by-default at every step. The residual is a changed region with no
  mutable construct AND a behaviour the acceptance doesn't name — the red-team's charge to probe.
- **Cost:** one tester authoring call + up to `cap` sandboxed suite runs, spent per-park on demand, only
  on an autonomous `oracle_unverified` park with the knob ON — never on every run.

## Red-team (DONE 2026-07-22, pre-merge — 4 refute-agents, one lens each)

Ran BEFORE merge (owner directive: verify + measure before landing). Scope card: **target** = the MR
!293 diff (`disposition.py` + `_escalation.py`); **successor?** = the mutation blind-spot class →
DEFER-TO-SUCCESSOR (#74/ADR-0071); **budget** = 3 rounds (durable, load-bearing). Verdict: the safety
claim was **BROKEN on multiple counts** — 8 disposition-specific FIX-NOW findings (all fixed + adversarially
re-verified: each agent's own repro no longer reproduces), plus DEFER/ACCEPT residuals. STOP rule NOT
tripped (findings are diverse classes, not one recurring).

**FIX-NOW (fixed + re-verified):**
1. **Convertible-signal ignored out-of-band honest-stop channels** — `_is_convertible_park` read only
   `gate_decision.reasons`, so a thrash park (`stalled`), an early give-up (`give_up_reason`/
   `plan_unworkable_reason`), or a coder hand-raise (`blocked_reason`/`escalate_reason`) with an
   incidental green `oracle_unverified` was wrongly convertible → would ship past a safety stop / the
   escalate arm. Fix: reject when any honest-stop channel is truthy (agrees with `_termination_reason`'s
   priority) + harden a non-dict `outcome_verdict`.
2. **Mutation `source` leak via name-based filter** — the authored file was excluded from mutation only
   by `is_test_file` (name `^test_…`), so a tester authoring `tests/check.py` leaked its own `==`
   assertion into the mutation targets; flipping it faked a "catch" and shipped wrong non-mutable code.
   Fix: subtract the exact `authored` set from `source`/`changed`.
3. **Release-before-dispose reset race** — `_after` released the project mutex before the rung, so a
   concurrent run's start-reset (`git reset --hard`+`clean -fd`) could wipe the uncommitted delivered
   diff mid-disposition → a code-less / wrong-branch ship. Fix: re-`reserve_project` across the whole
   author→verify→commit, release before `advance_project`.
4. **Empty / tests-only "ship"** — the `if not commit` guard only caught a byte-identical tree. Fix:
   `close_oracle_gap` returns `unavailable` when there is no delivered NON-test source delta (nothing to
   verify → don't ship only a test).
5. **Unguarded `close_oracle_gap` call** — a fault propagated out of `_after` and was swallowed, silently
   stalling the sweep. Fix: try/except → audit + fall through.
6. **Unguarded post-commit status mark** — a DB fault after the commit left a committed-but-`todo` item
   that `advance_project` would re-deliver. Fix: guard the mark; on failure do NOT advance.
7. **Baselined-test-edit laundering** — the tester had `edit_file` under `tests/` with no `protected_paths`
   and `close_oracle_gap` never re-checked tamper, so a gutted baselined test rode the whole-tree commit
   into the ship. Fix: `protected_paths` = all pre-existing `tests/` files at the tool layer + a
   post-authoring before/after-hash tamper check in `close_oracle_gap` (any pre-existing test changed →
   `unavailable`).
8. **Non-coder-blind, spec-nudging prompt** — `_author_instruction` said "PROVE the delivered behaviour"
   and interpolated the untrusted acceptance/task unfenced. Fix: anchor the test on the ACCEPTANCE
   (derive expected values from the spec, not the code) + fence the two blocks as untrusted data. Also
   aligned the green-step interpreter to `sys.executable` (matches the mutation gate).

**DEFER-TO-SUCCESSOR (#74/ADR-0071):** a purely non-mutable changed region (e.g. a wrong constant) rides
free alongside a mutable+asserted region — the mutation primitive's own disclaimed blind spot. The
verified-reason string was softened to stop over-claiming "every mutation."

**ACCEPT (inherent residual — documented):** the *who-tests-the-test* limit. The gate proves the authored
test is a real oracle for *some* behaviour, not that it encodes the *correct* spec; a tester that misreads
the acceptance the same way the coder did (same model family), or a sufficiently crafted injected
acceptance, can still author a test that ships wrong code. FIX-NOW #8 materially narrows this (author to
spec, not to code; fence injection), but the deep property is inherent to authoring-after-delivery and is
the oracle-successor's mandate — the win is bounded by **tester independence** (a held-out model, and/or
coder-blind authoring against pre-delivery HEAD) and authoring quality, exactly the ADR's stated bound.
Default OFF + measure-first bound the exposure until this is quantified. Refuted probes: deny-by-default
fault paths and the `tests/` write-scope both held.

## Measurement (DONE 2026-07-22, pre-merge)

A focused live measurement drove the REAL `close_oracle_gap` (real `qwen3-coder:30b` tester authoring
+ real Docker sandbox green-run + comprehensive mutation) on crafted `oracle_unverified` parks
(`docs/demos/observed-outcomes.md` → *Layer-2 disposition measurement*):

- **Conversion 5/5** — a correct `discount` implementation parked with only its own green tests is
  CONVERTED to `verified` (the tester authors a spec test, the delivered code passes it + the mutation
  is caught).
- **False-ship 0/7** — a wrong `discount` (`price - pct`, returns 190 where the acceptance wants 180)
  stays parked every rep (`unverified`: "the delivered code fails the independent acceptance test").
  The spec-anchored authoring (FIX-NOW #8) means the tester encodes the acceptance, not the delivered
  behaviour, so wrong code fails the test — the who-tests-the-test residual did not bite on a clear
  acceptance.
- **No tests-only ship** (empty delivered delta → `unavailable`) and a **constant-only correct change is
  conservatively parked** (`unverified`, the deferred #74 non-mutable blind spot — a safe miss, never a
  false-ship).

~~The full-bench conversion-rate hook over the MCB corpus remains as follow-up instrumentation~~ (**SHIPPED** as `mosaera-layer2-report`, which reads every scorecard ever written and renders the rescued/parked × right/wrong matrix; corrected 2026-08-18, `docs/audits/adr-corpus-review-2026-08-18.md`. What remains open is not instrumentation but *evidence*: measured discrimination is still UNDEFINED — 1 conversion / 0 false ships — and `disposition_gap_close` stays default OFF); this
targeted A/B is the pre-merge DoD signal that the mechanism converts correct code and never false-ships
wrong code with the shipping local model.
