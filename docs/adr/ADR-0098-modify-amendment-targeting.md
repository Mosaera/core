# ADR-0098 — A MODIFY item names the test that asserts the behaviour it changes

- **Status:** ACCEPTED — 2026-08-10
- **Scope:** `packages/core/mosaera_core/graph/_modify_amendment.py`, `_proctor_authoring.py`
- **Relates to:** [ADR-0058](ADR-0058-proctor-validates-repairs-tests.md) (the Proctor's repair authority),
  [ADR-0087](ADR-0087-test-contracts-and-renegotiation.md) (the operator-authorized amendment),
  [ADR-0097](ADR-0097-consumer-impact-modify.md) (the `consumer_impact` claim)
- **Red team:** DONE 2026-08-11 — R1 clean · **R2 CONFIRMED and FIXED** · R3 clean, STOP rule
  applied (see *Red team* below)

## Context

Verb-arc slice 4 shipped the `consumer_impact` oracle, and MCB-28 — the bench case built for it —
delivered **0 of 2** on the 52-run integration sweep. The oracle was not the problem: it ran and
returned *satisfied*. The two runs failed for unrelated reasons, and one of them is structural.

Run 1 stalled at iteration 1: `tests_tampered`, *"pre-existing/protected tests or their collection
config were modified: tests/test_pricing.py."* The item's brief instructs that edit, because a
behaviour change makes the test asserting the old behaviour wrong. And that is a trap with no
autonomous exit:

1. the item requires editing a protected test;
2. editing it sets `tests_modified` → `stalled`, immediately;
3. `amendment_offer` then returns `{}` **by design** — *"a run that already TAMPERED may not be
   handed authorization to amend"*, which is correct, and prevents the amendment gate laundering
   the thing it exists to prevent;
4. so the only sanctioned route is to fail against the test *without touching it*, escalate, and
   have a **human** authorize — and an autonomous bench run has no human.

Even that route was unavailable: `amendment_gate` is default-OFF and not in
`apply_oracle_posture`, so it was inert for all 52 runs. **A MODIFY item cannot deliver
autonomously**, and no amount of oracle quality changes that.

## Decision

**When an ENTAILED `consumer_impact` claim exists, the Proctor's existing coder-blind repair turn
is told which pre-existing test asserts the behaviour being changed, and instructed to restate it
against the new behaviour.**

**This grants no new authority, and that is the whole argument for the placement.** ADR-0058
already lets the Proctor repair pre-existing tests — once, at `iteration <= 1`, before any
implementation exists, with the result content-pinned into `proctor_edits`. What was missing is
that nothing ever *told* it a MODIFY item requires restating the old-behaviour test, so it left the
contradiction standing and the coder walked into it. Naming a deterministic target inside an
authority that already exists is exactly what the faithfulness guard (ADR-0062) does two blocks
earlier in the same instruction.

Every ADR-0058 safety property therefore holds unchanged:

| property | why it still holds |
|---|---|
| **Coder-blind** | Runs before `implement`. No implementation exists, so a repair cannot be fitted to wrong code — the Reflexion failure ADR-0013 is built against. |
| **One-shot** | `iteration <= 1` only. A gate-deny re-plan re-authors *without* the excuse. |
| **Content-pinned** | Lands in `proctor_edits`; the tamper guard excuses exactly that content and `ctx.protected_tests` then locks the coder out of it. |
| **Cannot gut a test** | The assertion-profile check refuses the excuse for any repair that drops or shrinks a test function → `tampered_integrity` parks the run. The instruction says *restate*, never *delete* or *loosen*, precisely because the downstream check would turn the latter into a park. |
| **Ships only on proven mutation-catch** | Unchanged: a run with non-empty `proctor_edits` must clear `oracle_mutation_check` at the gate. |

**Targeting is deterministic and bounded three ways** — AST reference enumeration, no model call:

- **ENTAILED claims only.** Sentences quoted from the acceptance text the operator approved
  (`claims_from_acceptance`). A model's INFERRED proposal can never nominate a test for rewriting.
- **The claim's own symbol only.** Reuses slice 4's `nonuse.consumers_of`, so a baselined test that
  does not reference the changed symbol is never named.
- **Pre-existing files only.** The path must be in `integrity_baseline`. A test authored *this* run
  is not a pre-existing bar, and pointing the Proctor at its own output is a loop.

## Consequences

- **A MODIFY item can deliver autonomously.** The deadlock quoted in `graph/_amendment.py` —
  *"the engine can only ADD"* — is closed for the MODIFY verb without a human in the loop and
  without relaxing the tamper guard.
- **The operator-authorized path (ADR-0087) is untouched and still the only route for the cases
  this does not cover** — a test the operator must judge, a contradiction the acceptance text does
  not resolve, or any amendment after iteration 1.
- **Byte-identical for every non-MODIFY item.** No `consumer_impact` claim ⇒ empty block ⇒ the same
  instruction string as before.
- **Residual risk, stated.** The Proctor is a model, and it is being pointed at a real bar. The
  containment is that it may only *restate*, that a loss is refused mechanically by the profile
  check, and that the item's own acceptance text is the only thing that can nominate a target.
  What is *not* contained is a Proctor that restates the assertion to the wrong new value — the
  same residual ADR-0058 already carries, and the hidden grader is what measures it.
- **MEASURED 2026-08-11 — the mechanism WORKS, and is not sufficient alone.**
  ([record](../engineering-history/mcb28-slice4-measurement-2026-08-11.md).) 10 runs of MCB-28,
  5 per tester model. On the **2 runs where the Proctor complied**, `proctor_edits` carried
  `tests/test_pricing.py` and `tests_tampered`, `validation_failed` and `claim_behavioral_failed`
  **all disappeared**, with every claim satisfied — the deadlock fully broken, observed for the
  first time. Compliance was **0/5** on the default tester (which is also the coder) and **2/5** on
  a larger one; at n=5 that is suggestive, not a measured model effect.
  **The case still delivers 0/10, for a reason outside slice 4:** both compliant runs were vetoed
  by the critic for claims `task-c3` and `task-c10` — *narrative context describing the PRE-change
  state*, minted `oracle_kind: none`. `nodes_critic.py` passes every claim unfiltered, so for a
  MODIFY item the critic demands sentences that a correct change must necessarily falsify. The
  better the work, the more certainly it is refused.
  **RESOLVED 2026-08-11** — with the critic narrowed (ADR-0100) MCB-28 **delivered**:
  `clean_deliver`, zero gate reasons. The targeting is confirmed live on all 10 runs via
  `modify_amendment_targets`, not replayed by hand. Remaining bottleneck: Proctor compliance.
  **Owed (now DONE):** `amendment_refusals` on the card — `proctor_edits == []` currently conflates "never
  edited" with "edited and refused as a weakening", which need opposite fixes.

## Red team (2026-08-11) — 3 rounds, trust-boundary file-domain (the tamper excuse)

**R1 — the four stated bounds hold in code, not just in prose.** ENTAILED-only and
baseline-only are enforced deny-by-default in `_modify_amendment_targets`; the one-shot
coder-blind gate is real (`nodes_plan.py`, `tester_repairs_tests and iteration <= 1`); and the
excuse is content-pinned only after the file is proven to still assert behaviour and to not have
lost a test function (`_weakens`), so *restate* cannot become *delete* or *loosen*. Clean.

**R2 — CONFIRMED, FIX-NOW, fixed.** `consumers_of` matches a **bare name**: `_symbol_of` discards
the module path (`pricing.discount.apply` → `apply`) and `_references_in` matches any
`ast.Attribute.attr`. Reproduced deterministically: a claim about `pricing.discount.apply`
nominated an unrelated baselined test asserting `Tax().apply(100) == 120`. A nominated test may be
rewritten under the tamper excuse, so the guard would stand down on a contract nothing asked to
change.

The root cause is an **inherited claim**: ADR-0097 established that over-matching "is harmless by
construction", which is TRUE of the oracle — a wider consumer set only makes `impact_unassessed`
fire more often, i.e. conservative. ADR-0098 reused that same enumeration to choose files the
Proctor may **edit**, where the identical over-matching is permissive. The argument was sound in
its original context and unsound in the borrowed one.

Fixed in `_resolved_targets`, one-sided (it can only ever nominate FEWER files): a claim naming a
module requires the test to import from it; a bare symbol with exactly one definition is
unambiguous and unchanged; a bare symbol with several definitions nominates **nothing**. Pinned by
`test_a_name_collision_does_not_hand_out_an_unrelated_test`, with a positive control that the real
consumer is still named — a narrowing that nominated nothing would pass the first test while
silently disabling the mechanism. Verified against the **real MCB-28 seed**: its claim is a bare
`apply_discount` with one definition, so the case is unaffected.

**R3 — clean, and the STOP rule applied.** The MCB-28 regression check passed. The one further
issue found is a *partial*-prefix collision (a claim saying `discount.apply` would still match a
`billing.discount` module), which is the **same defect class as R2** — name collision. The protocol
forbids a third round on one class, so it is **ACCEPTED and documented** rather than patched:
it requires an actual import of a same-named module, the claim text is operator-approved ENTAILED
text, and the non-weakening profile check still bounds the damage to a restatement.

**Residual, unchanged and restated:** a Proctor that restates the assertion to the *wrong new
value*. Contained only by the profile check and measured only by the hidden grader — the same
residual ADR-0058 carries. MCB-28 is what will measure it.
