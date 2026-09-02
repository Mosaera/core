# ADR-0100 — The critic may not veto a claim the gate itself discards

- **Status:** ACCEPTED — 2026-08-11
- **Scope:** `packages/core/mosaera_core/critic_policy.py` (`dispose`)
- **Amends:** [ADR-0065](ADR-0065-held-out-critic.md) (the held-out veto), the residual-jurisdiction
  rule from the aborted 2026-08-03 A/B
- **Relates to:** [ADR-0079](ADR-0079-claims-first-class-artifacts.md) (claims),
  [ADR-0092](ADR-0092-claim-reason-split.md) (dispositions),
  [ADR-0062](ADR-0062-proctor-faithfulness-detector.md) (the premise-sentence class)
- **Invariants:** *Deterministic Final Authority*, *Honest Parking*, *Independent Approval*
- **Red team:** DONE 2026-08-11 — **R1 CONFIRMED (ACCEPTED, documented)** · R2 clean · R3 clean
  (see *Red team* below)

## Context — measured, not argued

The held-out critic's veto fired **9 times across 260 runs** (both mutation-veto arms plus the
MCB-28 measurement) and was **wrong all 9 times**: every firing refused work the hidden grader
confirms was correct. **8 of the 9 quote a premise sentence** — a description of the state the item
exists to change:

| case | claim | quoted requirement |
|---|---|---|
| MCB-18 ×4 | `task-c7` | *"crashes on the first malformed op…"* |
| MCB-18 | `task-c6` | *"It works when every op is valid but is naive: it applies ops in a loop and crashes…"* |
| MCB-27 | `task-c3` | *"`reporting/__init__.py` still re-exports the dead one"* |
| MCB-28 ×2 | `task-c3`, `task-c10` | *"The existing test asserts the OLD unrounded result"* |
| MCB-08 | `task-c7` | *"Fix the implementation, not the tests"* (spurious evidence quote) |

**A correct fix necessarily falsifies a premise.** The better the work, the more certainly it is
refused. On MCB-28 this is decisive: on the two runs where slice 4's mechanism worked perfectly —
`tests_tampered`, `validation_failed` and `claim_behavioral_failed` all cleared, every claim
satisfied — `critic_vetoed` was the **only** remaining gate reason.

### The cause is structural

```
unmatched sentence → classify_sentence → ("none", material=True)      claims.py
                   → evaluate_claims   → "unbound"                    claim_oracles.py
                     ref: "no oracle bound (intake's job, never the gate's)"
                   → the GATE DISCARDS it            (owner decision, 2026-08-03)
                   → dispose(): residual = {"unbound", "unevaluable", ""}   ← it could still veto
```

So a **model** could park a run on evidence the **deterministic layer had explicitly refused to
gate on**. That is *Deterministic Final Authority* inverted: the deterministic decision was
"this does not gate", and a model overrode it in the only direction it can — refusal.

**The regex route is exhausted.** `_PREMISE` exists precisely for this class and already carries
`currently (fails|crashes|is)` and `crashes with raw tracebacks`; **none of the eight matched**.
This is the third recurrence (MCB-03, MCB-13, MCB-28), so a fourth pattern list trips the STOP rule,
and [ADR-0085](ADR-0085-oracle-defect-detection-strategy.md) §1 disfavours semantic detectors in
the deterministic layer regardless.

## Decision

**`unbound` is removed from the critic's residual jurisdiction.** The critic may veto only
`unevaluable` dispositions (an oracle exists and could not run this time) and absent ones (a claim
determinism never reached).

A premise sentence is always `oracle_kind: none` → `unbound`, so this closes the entire class **by
construction** rather than by pattern.

**Verified against the measured record:** all **9 of 9** vetoes were on claims minted
`oracle_kind: none` — re-derived by minting each case's claims and looking up the vetoing claim id.
Every one is prevented.

**Nothing is silenced.** A refused refutation is still recorded in `rows` and reaches the human gate
panel; only its authority to park the run is withdrawn.

## Two records disagree, and both are stated

`dispose`'s docstring asserted the critic's residual record "is 5-for-5". **That figure has no
source anywhere in `docs/`** — it exists only in that comment. The 260-run corpus reads
**0-for-9**. Rather than overwrite one with the other: if those 5 were `unevaluable` claims, this
narrowing preserves exactly that authority and both records stand. If they were `unbound`, the
figure is contradicted by an order of magnitude more evidence. Recorded so the next reader can tell.

## Consequences

- **The critic keeps a real, narrower job.** `unevaluable` is where an oracle exists and could not
  run — a genuine gap where a model judgement adds information. Pinned by a positive control
  (`test_jurisdiction_an_UNEVALUABLE_claim_still_vetoes`), without which this change would be
  indistinguishable from disabling the veto.
- **Unverifiable requirements now gate nowhere.** A material claim with no oracle is discarded by
  the gate *and* unvetoable by the critic. That is coherent — one owner decision, applied
  consistently — but it means "must be secure"-style asks are carried, shown to the human, and
  enforced by nothing automatic. This is the honest status quo made visible, not a new gap.
- **Residual risk:** a genuine requirement that happens to mint `oracle_kind: none` loses its only
  automatic enforcement. Bounded by the same 0-for-9 record, and by the human gate.
- **MEASURED 2026-08-11 — the prediction held.** MCB-28 **delivered for the first time**:
  `clean_deliver`, **zero gate reasons**, hidden grader passed
  ([record](../engineering-history/mcb28-delivers-2026-08-11.md)). Delivery *given Proctor
  compliance* went **0 of 2 → 1 of 1**: every compliant run used to be vetoed by this control,
  and now ships. The headline rate (1/10) is held down by compliance, which is a model
  property, not a mechanism.

## Red team (2026-08-11) — 3 rounds, trust-boundary domain (the veto path)

The unsafe direction for a *narrowing* is a MISSED veto shipping bad code, so the rounds hunt for
protection lost, not protection gained.

**R1 — CONFIRMED. Prose requirements lose their held-out enforcement. Disposition: ACCEPT.**
Driven through the real `classify_sentence`, these all mint `oracle_kind: none, material: True` —
identical to a premise, and therefore no longer vetoable:

```
"Never log the user's password"                        -> none/material
"Secrets must never be written to disk"                -> none/material
"The endpoint must not expose internal stack traces"   -> none/material
"Do not introduce new dependencies"                    -> none/material
"Performance must not regress"                         -> none/material
```

This is a real reduction: the held-out critic was the only *independent, different-model* control
over this class. No structural separator distinguishes "describes the required end state" from
"describes the starting state" — that is precisely the semantic judgement `_PREMISE` failed at
three times, so a targeted restoration would re-enter the STOP rule.

**Accepted because the class is not left unguarded, verified by driving `evaluate_gate`:**

| control | still fires? |
|---|---|
| the **reviewer** (separate model, first pass) | `reviewer_requested_changes` → `require_human` ✔ |
| the **security scanner** (ADR-0076) | `security_findings` → `require_human` ✔ |
| the **human** at the delivery gate | the claim is carried and displayed ✔ |

What is lost is one layer of *independence* on prose requirements, against a measured 9-for-9 record
of that same layer refusing correct work. Recorded rather than argued away: if a real prose-security
miss is ever observed, this is the decision to revisit first.

**R2 — clean.** `oracle_kind: none` is reachable only through `claims_from_acceptance`, which is
ENTAILED-only and mints from **operator** text; a model cannot manufacture an `unbound` claim to
hide behind. And the change only ever *removes* model authority, so there is no escape it opens
that the gate did not already ignore.

**R3 — clean.** `unbound` is produced by exactly one path (`kind == "none"`). Every fault route —
unknown oracle kind, evaluator exception — degrades to `unevaluable`, which **remains vetoable**.
So nothing silently falls out of the critic's jurisdiction; this was the failure mode worth
checking, because a degradation-into-unvetoable would have been invisible.

**STOP rule:** not triggered — the three rounds found three different classes.
