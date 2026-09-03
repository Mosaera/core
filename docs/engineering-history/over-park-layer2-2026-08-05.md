# The over-park arc — Layer 2's larger class has been dead since 2026-08-02

Follow-on to [rebaseline-2026-08-05](rebaseline-2026-08-05.md) (see its CORRECTION section) and
[ADR-0074](../adr/ADR-0074-layer2-park-to-ship-disposition.md)/[ADR-0075](../adr/ADR-0075-engine-blocked-give-up-conversion.md).

**Verdict: the arc did not measure what it set out to measure, because the thing it was measuring
was switched off. That is the finding.**

---

## Stage 1 — over-park was understated 4.5×

The re-baseline reported over-park at 5.6% (4 runs) counting only `thrash_park`s. Re-reading all 60
stored scorecards with the full rule — any non-crash run that did not deliver, whose hidden grader
passes — gives **18 of 25 parks, which is 18 of 60 runs (30%)**. The 14 missed stopped *promptly*,
so they classified `honest_park`: honest about stopping, wrong about the work.

`parked` and `grader_passed` were BOTH already on every card. Nothing crossed them. Now the
`Fidelity` dimension computes it on every run (commit `47a9ae3`), scoring the terminal decision
against the grader in both directions — a false ship and an over-park are one defect pointing
opposite ways, and only one was ever reported.

## Stage 2 — the sweep, and what stopped it being informative

18 runs, 6 cases, `--layer2`, `--repeat 3`, `MOSAERA_MODEL_PM=gpt-oss:20b`. Trimmed from the planned
33 by the owner once the structural finding landed.

```
MCB-01  thrash_park*  thrash_park*  clean_deliver
MCB-02  clean_deliver clean_deliver clean_deliver
MCB-04  clean_deliver honest_park*  clean_deliver
MCB-07  clean_deliver clean_deliver honest_park*
MCB-16  clean_deliver honest_park*  honest_park*
MCB-21  clean_deliver clean_deliver honest_park*    (* = over-park)
```

**7 of 7 parks were over-parks. 0 conversion attempts. 0 false conversions.**

| n | core gate reasons | why Layer 2 declined |
|---|---|---|
| 4 | `unsatisfied_claim + validation_failed` | **the allowlist gap below** |
| 1 | `reviewer_requested_changes + …` | correct — a real objection |
| 1 | `tests_tampered + …` | correct — never launder a tamper |
| 1 | `oracle_unverified` alone | **unknown — not recorded** |

### The finding: `unsatisfied_claim` silently killed class 2

`is_engine_blocked_give_up` rejects any park whose gate reasons fall outside
`_GIVE_UP_ALLOWED_REASONS = {iteration_limit, oracle_unverified, reviewer_unknown,
validation_failed}`. **`unsatisfied_claim` is not in it.** Verified against the real predicate: the
dominant over-park shape returns `convertible_park_class = None`; remove `unsatisfied_claim` from
the reasons and the identical run returns `engine_blocked_give_up`.

- `_GIVE_UP_ALLOWED_REASONS` was written **2026-07-23** (`7c2bd77`, ADR-0075) — the arc that
  measured Layer 2 and closed.
- `unsatisfied_claim` was introduced **2026-08-02** (`f315792`, ADR-0079 Wave 2, the claim contract)
  — ten days later.

A later feature added a gate reason that a deny-by-default allowlist had never heard of, and
narrowed a previously-measured converter to nothing. Every test stayed green. **#76's measurement no
longer describes the engine** — it was taken before claims existed.

That shape is 7 of the 18 stored over-parks, and it reproduced live on **three independent cases**
(MCB-04, MCB-07, MCB-16) in this sweep. This is the same defect class as the dead clause overlay and
the four ADR-0081 liveness incidents — third instance in a week, and the first whose cause is
*another feature landing on top of it*.

**The fix is not a one-line allowlist edit.** `unsatisfied_claim` means the gate's per-claim check
found a material claim unestablished, and Gate 2 (ADR-0061) is precisely "no unestablished material
claim ships". Adding it to the allowlist would ship what Gate 2 forbids — *unless* the disposition's
own independent re-verification (author from acceptance → assertion floor → green → comprehensive
mutation) is accepted as establishing the claim. That is a defensible bridge and a genuine
trust-boundary argument: it needs an ADR and a red team, not an edit.

### The second finding: a decline with no diagnosis

MCB-21 (`20260805-112252-a14a36`) parked with gate reasons `['oracle_unverified']` **alone** — the
exact class-1 shape — and Layer 2 declined it. Those reasons rule out every documented decline:
tests passed (else `validation_failed`/`validation_unavailable`), no tamper (else `tests_tampered`),
reviewer APPROVE (else `reviewer_unknown`), no critic veto (else `critic_vetoed`). The card shows
`stalled: False` and empty `give_up_reason` / `plan_unworkable_reason`.

The only remaining candidates are `blocked_reason` and `escalate_reason` (a coder hand-raise) — and
**the scorecard records neither.** The run's final state is gone (the bench uses an in-memory
checkpointer), so the cause is unrecoverable.

The repo already learned this lesson: the `vouch` field exists because *"a control whose non-firing
is invisible costs a day of archaeology — this field cost 6 lines"* (`nodes_review.py`). Layer 2's
decline has no equivalent. `layer2_class: None` and nothing else.

## Pre-registered predictions, dispositioned

| | prediction | outcome |
|---|---|---|
| P1 | class-1 attempt on every `oracle_unverified` park | **NOT ANSWERED** — one valid-shape park occurred and was declined for an unrecorded reason |
| P2 | unknown class-2 conversion fraction | **answered structurally: zero**, before any evidence gate runs |
| P3 | zero conversions from excluded classes | not falsified |
| P4 | `false_ship` must not increase | held **vacuously** — zero conversions buys no safety evidence |

## Dispositions

- **FIX-NOW:** record WHY the disposition declined (a `layer2_decline` diagnosis, the `vouch`
  treatment), and add `blocked_reason`/`escalate_reason` to the scorecard. Both are recording gaps,
  not engine changes.
- **ESCALATE (needs an ADR + red team):** whether the disposition's independent re-verification may
  establish an unsatisfied claim. This is the load-bearing question for closing 7 of 18 over-parks.
- **SHELVED:** the stall-path convertible class (planned stage 3). With class 2 dead for the
  dominant shape, widening a second door builds on a lever that does not currently turn.
- **CARRY:** `disposition_gap_close` stays **default OFF**. This sweep produced no evidence it is
  safe to enable, and "no conversions occurred" is not that evidence.

## Caveats

18 runs, one model, `qwen3.6:35b` unavailable so the PM ran `gpt-oss:20b`. Case-level variance is
large and was visible throughout: MCB-01 parked 3/3 in the stored sweep and delivered 1/3 here;
MCB-02 parked in the stored sweep and delivered 3/3 here; MCB-07's stored `oracle_unverified` shape
did not recur once. **Conversion rates here describe the parks this sweep produced, not the stored
18.** The structural finding does not depend on any of that — it is a predicate read, confirmed by
direct execution.
