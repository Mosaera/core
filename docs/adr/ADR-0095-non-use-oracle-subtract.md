# ADR-0095 — A removal is proven by a non-use oracle, and an unproven removal cannot ship

- **Status:** accepted
- **Date:** 2026-08-09
- **Amends:** [ADR-0079](ADR-0079-claims-first-class-artifacts.md) (a seventh oracle kind), [ADR-0092](ADR-0092-claim-reason-split.md) (a fourth evidence class), [ADR-0094](ADR-0094-eligibility-structural-claim-widening.md) (the widening must not reach removals)
- **Scope:** `packages/core/mosaera_core/{claims,claim_oracles,nonuse}.py`, `packages/policies/{gate,standards}.py`, `apps/api/.../\_terminal.py`, `apps/web/src/lib/plain.ts`, `packages/memory/.../models_claims.py`, `bench/cases/MCB-27`
- **Invariants:** *Evidence-Gated Advancement*, *Deterministic Final Authority*, *Honest Parking*, *Control Points not Headcount*
- **Implements:** verb-arc slice 1 (SUBTRACT, end to end)

## Context — the deadlock, measured

An item whose purpose is **removal** could neither deliver nor park honestly. Reproduced on
`4bcaa77` before anything was built:

```
classify_sentence("Remove the deprecated `legacy_export` function.")  ->  ('none', True)
classify_sentence("Delete the unused `helpers/oldmath.py` module.")   ->  ('none', True)
classify_sentence("Drop the `--legacy` CLI flag.")                    ->  ('none', True)
```

`('none', True)` is a **material claim with no oracle** — unsatisfiable by construction. Meanwhile
`delete_file` is admin-opt-in and off, so the coder could not do the work either. The run re-scoped
to the iteration cap and parked without ever naming why.

The root cause is that **a removal has no behavioural signature.** The *absence* of code cannot be
exercised by an acceptance test, and a green suite proves only that whatever remains still works —
not that the thing is gone, and certainly not that nothing still calls it. Every oracle the engine
had was behavioural or shape-based. None could ask this question.

## Decision

**A `non_use` oracle kind.** A removal sentence (leading imperative or explicit passive) mints a
claim whose oracle is `nonuse.non_use_proven` — deterministic mechanical reference enumeration over
the delivered tree, no model call, no sandbox. Tri-state, in the shape `structural_spec` established:
`True` proven absent · `False` still referenced · `None` unaskable. It can only ever **downgrade**.

**Amendment 1 (2026-08-10) — the enumeration is scoped to the PRODUCTION tree.** As first written it
walked every `.py` file, and the measured result was that it refused correct removals: MCB-27
over-parked 2/2 with the hidden grader passing, because a *test asserting the symbol is gone*
(`from pkg import gone` inside `pytest.raises(ImportError)`) is an `ast.ImportFrom` like any other.
The test that proves a removal was the thing that refuted it — and this ADR's own hidden grader
makes that exact assertion, so the oracle would have refused its own proof.

This narrows nothing that was actually load-bearing, because both ways a test can name a removed
symbol are already covered by an independent control: one that **calls** it turns the suite red and
`validation_failed` parks the run; one that **asserts its absence** stays green and is not a caller.
The question this oracle owns is therefore stated precisely as *does anything in the delivered
production tree still reach for this?* Test-side mentions are still walked and **named in the
evidence** — discounting a reference silently would be the invisible-control defect. A tree with no
production files at all resolves `None`, never `True`: "zero production callers" and "zero
production files examined" are the same sentence with opposite meanings.

**Its own evidence class, `removal`, emitting `removal_unproven`.** Not `claim_structural_failed`,
and the reason is a concrete hole rather than taste: that bucket is exactly what ADR-0094 widened
for Layer-2 eligibility. An unproven removal landing there would become **auto-ship-eligible**, and
Layer 2 verifies by authoring a *behavioural* test and mutating it — which says nothing about
whether the removed thing is still referenced. **It could convert a removal that breaks every
caller.** A separate class keeps it out of every admissible set *by construction*, pinned with the
widening knob explicitly ON.

**Unprovable is FAILED, not `unevaluable`** — and this is the one place `non_use` deliberately
differs from every other kind. The others resolve an unaskable question to `unevaluable`, which the
gate ignores (owner decision 2026-08-03). That is right for a claim about behaviour: absent evidence
is not an objection. It is **wrong for a claim of absence**, where the slice's requirement is
literally *removal without a non-use proof cannot ship*. The deny-by-default therefore lives in the
per-kind evaluator, where kind-specific policy belongs; the shared reducers and the gate are
untouched.

**`removal_unproven` is PROOF-BEARING.** It fires precisely *because* proof is absent, so a clause
that could waive it would waive the only evidence standing between a removal and its callers.

**Capability: `delete_file` only; git untracking deferred.** This answers verb-arc open question 1.
"Delete a file" and "untrack a file" are different blast radii, neither replayable failure needs the
latter, and the doc already said git may wait.

## Red team (1 pass — a vocabulary addition, not a new control)

- **R1 — can the new reason turn a park into a ship?** No finding. A monotonicity sweep over
  `tests_passed × reviewer_verdict × findings_count` shows adding the `removal` class never improves
  an action and never shrinks the reason list. Downgrade-only holds.
- **R2 — does the class table stay total?** No finding. 18 declared reasons, 18 classified;
  `removal_unproven` is `objection` and in `PROOF_BEARING`.
- **R3 — can the oracle be made to VOUCH for a removal still in use? CONFIRMED, FIXED.**
  `getattr(mod, "legacy_export")` names its target as a **string**, so the AST pass saw no `Name`,
  no `Attribute`, no import — and vouched. A false vouch is the **only unsafe direction** this
  oracle has: every other error refuses a fine removal (waste), this one ships breakage. Fixed by an
  **exact-match** string-constant pass returning `None` (unprovable, therefore blocking). Exact, not
  substring: a docstring mentioning the name is prose, and treating prose as a caller would make the
  oracle refuse nearly everything — conservative to the point of useless is its own failure mode.

No second finding in any defect class; the STOP rule was not reached.

## Consequences

**A new way for runs to park.** The mitigation is measured, not asserted: a bare verb search
produced **five false positives** across the 27 shipped briefs — `delete` naming a CLI verb
(MCB-01/23), a dict method (MCB-10) and a payload action (MCB-18), all features being *built*. The
pattern was narrowed to a leading imperative or explicit passive and now mints **zero** `non_use`
claims across 361 real claims. Under-matching is safe (it falls back to today's park); over-matching
is what breaks ordinary items, so the asymmetry is deliberate.

**MCB-27 is the first subtract case in the corpus.** Verified coherent: on the seed the hidden
grader fails *and* the oracle says "still referenced"; on the reference the grader passes *and* the
oracle says "proven". Two independent judges agreeing at both ends.

**Honest limit.** The oracle proves non-use *within the delivered tree*. It cannot see a caller in
another repository, and its dynamic-reference guard is a heuristic that fails **safe** (refuse) and
not silently.
