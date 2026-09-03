# ADR-0090: Gate reasons are CLASSIFIED, and a control admits by class — never by a hand-written list

- Status: accepted
- Implementation: **partial — MR1 only** (the classification table + the derivation + the totality guard + the kind instrument). The reason split and the admission changes are MR2/MR3 and are **not** authorized by this ADR's implementation status.
- Date accepted: 2026-08-08
- Owners: Mosaera core
- Related issue / MR: #68 (F62)
- Supersedes / Superseded by: — (**amends** [ADR-0075](ADR-0075-engine-blocked-give-up-conversion.md) and [ADR-0079](ADR-0079-claims-first-class-artifacts.md); supersedes nothing)
- Related threat model: [TM-0001](../threat-models/TM-0001-mosaera-lite-repo-agent.md) (the Layer-2 row — admission policy, unchanged by MR1)
- Review trigger: a fifth `ReasonClass` is proposed, or MR2's reason split lands
- Amended by: [ADR-0092](ADR-0092-claim-reason-split.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.

**Decision summary:** Every `GateReason` carries a **class** — `objection` · `shortfall` ·
`incidental` · `tamper` — declared in `packages/policies/mosaera_policies/gate.py` one edit from the
`GateReason` Literal it classifies. Controls that admit or refuse a parked run decide **from the
class**, never from a privately-held list of reason strings. The classification is **total** over the
Literal and a test fails if it is not. MR1 is behaviour-neutral by construction and pinned as such.

## Context

`_GIVE_UP_ALLOWED_REASONS` was hand-written on **2026-07-23** (ADR-0075) as a deny-by-default
allowlist: a parked run is admissible to a disposition arm only if
`set(gate.reasons) - allowed` is empty. On **2026-08-02**, ADR-0079 Wave 2 minted a new gate reason,
`unsatisfied_claim`. The allowlist had never heard of it, so every park carrying it became
non-convertible by **both** arms — the Layer-2 close-the-gap arm and the ESCALATE arm.

**Every test stayed green.** Nothing related the `GateReason` Literal in `packages/policies` to the
frozenset in `core`, so there was nothing to fail. Measured cost: 7 of 18 stored over-parks,
reproduced live on three independent cases (MCB-04/07/16), and the direct cause of the ESCALATE arm
stopping a run it could then not ask about (run `20260806-231047-7c2c75`, item #87 — the operator got
an honest stop and nothing to answer).

This is the **third** instance in a week of a control that fails silently, and the first whose cause
is *another feature landing on top of it*. The defect is not the missing member. **The defect is that
a reason and its admission live in two places with nothing forcing them to move together.**

### The framing that made it hard, and why it was wrong

#68 was filed as a Gate-2 question: *may the disposition's independent re-verification establish an
unsatisfied claim?* **That question is unanswerable as posed**, because `unsatisfied_claim` is one
string over three evidence classes with opposite correct dispositions. `evaluate_claims` dispatches
on `oracle_kind`:

- **behavioural** (`acceptance_test`, `validation_exit`, `wellformedness_parse`) — the "bound claim's
  oracle" is `state["tests_passed"]` **verbatim**. There is no predicate to re-run. A failure here
  *restates* `validation_failed`, a reason both arms already admit.
- **structural** (`ast_transformation_contract`) — genuinely independent: the delivered AST provably
  lacks the shape asked for.
- **integrity** (`tests_unmodified`) — a failure IS the tamper fact wearing a benign name.

The codebase already argues exactly this, in the *satisfy* direction
(`claim_oracles.satisfied_structural_claim_ids`): *"`tests_unmodified` rows ARE the tamper guard and
behavioral rows ARE `tests_passed` — counting either as an independent oracle would double-count
evidence the conjunction already holds."* The gate performs that same double-count in the **deny**
direction, unacknowledged.

> **Provenance, added 2026-08-28 — the measurement below cannot be re-derived.** The 2,055-card
> corpus it reads was destroyed on 2026-08-10
> ([record](../engineering-history/evidence-store-loss-2026-08-10.md)); no scorecard predating that
> date survives, and the extant corpus is 198 cards over 25 cases. The numbers stand as recorded on
> 2026-08-08 and are **not retracted** — they were measured honestly against evidence that existed at
> the time. But they are now **unfalsifiable**: a reader cannot re-query the split, and a future
> finding that contradicts them cannot be adjudicated against the source. Treat them as a historical
> measurement, not a standing one.

**Measured, 2,055 stored scorecards, no new runs.** 118 carry `unsatisfied_claim`, split by
co-presence of `validation_failed` as a proxy for the kind:

| group | n | grader passed |
|---|---|---|
| `unsatisfied_claim` ∧ `validation_failed` | 63 | **54 (86%)** |
| `unsatisfied_claim` ∧ ¬`validation_failed` | 55 | 17 (31%) |

And the result that settles it: **in 19 of the 23 cases that emit the reason, the failed-id set is
byte-identical on every run.** MCB-01 emits the same nine ids regardless of what the agent produced.
*A signal that does not vary with the run is not measuring the run.* (**Explained 2026-08-08** —
not minting, but the two-boolean collapse plus an unstable id space; see Known limits and
#84. It turns the correlation below into a
proof.)

So the reason is derivative and over-park-correlated in one half, independent and
correct-park-correlated in the other. Answering the Gate-2 question either way would be wrong for
half the population.

## Decision

### 1. Classify the REASON, not the arm

A per-arm allowlist split was considered and rejected: it is the F71/F79 defect class (*the same rule
at a second origin*), and the drift had already begun — `escalate_arm.py` imported the **private**
`_GIVE_UP_ALLOWED_REASONS` across a module boundary. Two named sets with a shared base is worse
still: a base-plus-deltas is precisely how the next reason lands in the base and silently changes
both arms, or lands in neither.

`REASON_CLASS: dict[GateReason, ReasonClass]` is **total** over the Literal:

| class | meaning | admissible to a disposition arm |
|---|---|---|
| `objection` | someone or something found a real problem with the work or its review | **no** — the park stands on its own terms |
| `shortfall` | an evidence bar was not met, with nothing objecting | **yes** — this is the class the arms exist for |
| `incidental` | no independent information: it rides along, or it is silence | **yes** |
| `tamper` | an integrity violation | **never**, by any arm, under any posture |

### 2. The classification lives beside the Literal, in `packages/policies`

`gate.py` is CODEOWNERS-protected, and that is the point rather than the cost: declaration and
classification land in one edit, under one review. The gate **classifies**; it does not decide
admission. *Which* classes a control admits is that control's policy and lives with the control —
`disposition.py` states `("shortfall", "incidental")` once and derives its membership. The gate must
not grow knowledge of the disposition arms.

### 3. Totality is enforced by a test, not by an AST guard

`typing.get_args(GateReason)` is a **runtime-truthful** read of the Literal's members. An AST scan
would copy `check_state_keys.py`'s *form* rather than its *reason* — that guard parses because a
`TypedDict`'s inherited keys are not cheaply introspectable across files, which is not the case here,
and a second weaker derivation of a fact Python already hands us is the very defect class this ADR
closes. `test_gate_reason_classification.py` asserts both directions (unclassified reason; stale
entry), proves the check on synthetic input so it cannot pass by vacuity, AST-walks `gate.py` for
**emitted-but-undeclared** reasons, and pins that no module holds a second copy of the allowlist.

Trade-off, stated: a test runs under `make test`, not `make lint`. `make ci` runs both. A lint rung
would cost three further protected surfaces (`Makefile`, `CLAUDE.md`, `coding-standards.md`) for a
strictly weaker check.

**Falsified against a reproduction of the original defect, not merely asserted.** Adding an
unclassified member to the `GateReason` Literal — exactly what ADR-0079 Wave 2 did — leaves
`test_disposition.py`, `test_escalate_arm.py` and `test_disposition_sweep.py` **green (exit 0)**,
which is how #68 shipped in the first place, and fails the new guard (exit 1) with a message naming
the reason. A guard that has never been shown to fail is not evidence.

### 4. MR1 is behaviour-neutral, and is pinned as such

`give_up_allowed_reasons()` must reproduce ADR-0075's shipped frozenset **exactly** —
`{validation_failed, reviewer_unknown, iteration_limit, oracle_unverified}`. `unsatisfied_claim` is
therefore classified `objection` **for now**, which is wrong for its behavioural half and is recorded
as wrong in the table itself. Changing that literal is changing the admission policy: that is MR2,
and it needs its own ADR pass and red team, not a test edit.

### 5. The kind is recorded, so the split stops being a proxy

`failed_claim_kinds` counts failed claims per `oracle_kind` onto the bench scorecard. The 2026-08-08
measurement had to infer the class from `validation_failed` co-presence because nothing recorded the
kind; MR2's argument should rest on a direct read, not on a proxy.

## Consequences

**Good.** The class of defect that produced #68 cannot recur silently: a new `GateReason` either
arrives with a class or fails a test that names it. Both arms have one origin for their membership,
and the private cross-module import is gone. The Gate-2 question is reframed from unanswerable to
answerable-per-class, and the evidence to answer it is now recorded rather than proxied.

**Accepted residuals.**
- **`unsatisfied_claim` remains misclassified**, deliberately and in writing. MR1 buys the mechanism,
  not the fix. Over-park is untouched: **36.1% before, 36.1% after.**
- **The reason split (MR2) carries a migration hazard already identified and not yet costed:** the
  gate-stall breaker fingerprints `sorted(set(reasons))`, so splitting one reason into three changes
  the fingerprint and therefore ADR-0069's breaker behaviour. **Replay analysis is mandatory** before
  MR2 lands, along with the downstream string readers (`run_diagnosis`, `critic_policy`, `persist`,
  `standards`, `bench/harness`, `bench/cli`).
- **The ESCALATE arm's predicate is still evaluated at two points against three states of
  `gate_decision`** — absent on iteration 1, **stale** on iteration ≥ 2 (it is written in
  `nodes_review` and never cleared on the deny→plan edge), and real at the API. Both disagreement
  directions are live today. MR3, and it is blocked on extracting the arm's block out of
  `nodes_plan.py`, which is at 499 of 500 lines.
- **The ask is a leading question.** Every proposal the ESCALATE arm offers lowers or moves the bar,
  with no option that rejects the producer's objection — while the arm's own refusal text says *"this
  must never become a way to blame the tests."* Nothing records that an acceptance was amended, so
  admitting claim reasons to that arm before fixing it would make over-park an unfalsifiable metric.
  A condition of MR2, recorded here so it is not lost.
- **The 19-of-23 constancy — EXPLAINED 2026-08-08, and it STRENGTHENS this ADR**
  (#84,
  [record](../engineering-history/claim-constancy-2026-08-08.md)). Not a minting bug. Two causes:
  **(a) within a version** — the id→kind partition is a pure function of the brief *and* all three
  behavioural kinds resolve to `state["tests_passed"]` verbatim, so a case's behavioural ids fail
  together or not at all; **18 of 24 cases mint no structural claim at all**. **(b) across versions**
  — the id space is **not stable**: commit `5bcae6e` (2026-08-03) rewrote the sentence splitter and
  halved it, so three cases' stored cards cite ids no current brief can mint, and
  `models_claims.py`'s documented `(item_id, claim_id)` *"cross-run key"* is false across that
  boundary.
  **Consequence for the Decision above:** *"a behavioural `unsatisfied_claim` restates
  `validation_failed`"* is no longer an inference from an 86% correlation — it is a **proof from the
  mechanism**, with N computable per case from the brief alone. Pinned by
  `packages/core/tests/test_claim_constancy.py`, which fails the moment a behavioural kind gains a
  per-claim oracle (i.e. exactly when this premise stops holding).
  **The measurement in Context was re-checked across the splitter boundary** rather than assumed:
  on single-version data post-`5bcae6e` the split is **88% (n=50) vs 30% (n=54)**, with pre-boundary
  cards a 14-of-118 minority. The argument never depended on id identity — it partitions on gate
  reasons and grader outcome — but that had to be demonstrated.

**Amends ADR-0079.** Wave 2's claim contract stands; its "ONE stable reason string" decision is
narrowed — the string is stable *per evidence class*, and the granularity question is reopened.

**Amends ADR-0075.** Its allowlist is replaced by a derivation from the classification table. Its
convertible class 2 and its independence limit **stand and are re-affirmed**: ADR-0075 is right that
a fresh test authored from the acceptance is not independent of the acceptance — that argument is
correct, and it applies to the structural kind, which is exactly the kind the measurement shows is
correctly parked.
