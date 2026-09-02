# ADR-0092: The claim gate reason splits by EVIDENCE CLASS — a message, never a permission

- Status: accepted
- Implementation: shipped (the split, the classed contract, the admission change, the red team)
- Date accepted: 2026-08-08
- Owners: Mosaera core
- Related issue / MR: #68 (F62) — MR2 · evidence in #84
- Supersedes / Superseded by: — (**amends** [ADR-0090](ADR-0090-gate-reason-classification.md), [ADR-0079](ADR-0079-claims-first-class-artifacts.md), [ADR-0075](ADR-0075-engine-blocked-give-up-conversion.md); supersedes nothing)
- Related threat model: [TM-0001](../threat-models/TM-0001-mosaera-lite-repo-agent.md) — the Layer-2 row **does** change here, unlike MR1
- Review trigger: a fourth claim evidence class is proposed, or the ESCALATE arm gains its own class tuple
- Amended by: [ADR-0094](ADR-0094-eligibility-structural-claim-widening.md), [ADR-0095](ADR-0095-non-use-oracle-subtract.md), [ADR-0097](ADR-0097-consumer-impact-modify.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.

**Decision summary:** `unsatisfied_claim` splits into `claim_behavioral_failed` /
`claim_structural_failed` / `claim_integrity_failed`, classified `shortfall` / `objection` /
`tamper`. **The split never suppresses**: it emits one reason per evidence class present, and never
drops one. Core partitions oracle kinds into classes; policies declares only the three-member class
vocabulary. Only `claim_behavioral_failed` becomes admissible to the disposition arms.

## Context

ADR-0090 landed the classification table and deliberately left `unsatisfied_claim` **misclassified**,
recording it as wrong in the table itself. That misclassification is what shut the Layer-2 converter
off on the dominant over-park shape (#68/F62).

Two things re-scoped this MR before it was written.

**The feared blocker is not the dangerous part.** ADR-0090 called a stall-fingerprint replay analysis
mandatory. The breaker compares fingerprints **within a run only** (`stall_by_kind["gate"]`, a
RunState field); nothing persists or cross-compares one. Both visits use the same code version, so a
split changes the hash *value* and not the equality *relation*. Split-only is a surjection, so trips
can only be lost, never gained.

**The dangerous part is suppression, and this ADR does not do it.** ADR-0090 floated "stop emitting a
behavioural reason when `validation_failed` is present." Suppression is the *only* mechanism that can
empty `reasons` or reduce them to exactly `["reviewer_unknown"]` — i.e. flip a park into a **ship**
through `_resolve` — and the only one that can *gain* a stall trip. Dropping suppression removes both
hazards and still achieves the goal, because the converter is unblocked by **classification**, not by
omission.

That produces the scoping this ADR is written under, and the two halves carry different obligations:

> **Gate-deny-preserving by construction. Disposition-widening by intent.**

## Decision

### 1. Split, never suppress — and prove the permission is unchanged

`evaluate_gate` has exactly four ship-or-revise predicates, every one a **positive** test against a
fixed literal: `not reasons` · `core == ["reviewer_unknown"]` (+ `tests_passed is True` +
`strength == "suite"`) · `set(reasons) == {"reviewer_requested_changes"}` ·
`action = "deliver" if not reasons else "require_human"`. Emitting k ≥ 1 reasons exactly where the
old code emitted 1 leaves `bool(reasons)` invariant and can only *grow* the list, so all four are
pointwise invariant. This is `a33e86e`'s argument — *"splits a MESSAGE, never a permission"* — with
the audit written down.

The audit is a property of *this* gate's source, not a law, so it ships as
`test_gate_monotonicity.py`: an exhaustive cross-product over every gate input × the failed-class
powerset, asserting `bool(reasons)`, `action`, `autonomous_resolution` and the **surjection** (every
new reason collapses back to exactly the old one). **That test is what replaces the replay analysis.**

Two constraints keep the proof valid and are easy to break: the claim append must stay the **last
content-bearing append** (`core == ["reviewer_unknown"]` is a *list* equality, so reordering weakens
it), and a new reason must land under a re-run sweep rather than the argument alone.

### 2. Core partitions; policies declares only the class vocabulary

The gate receives claim **ids** and cannot see oracle kinds, and `packages/policies` may not import
`mosaera_core` where `ORACLE_KINDS` lives. Declaring the six kinds inside `gate.py` would have
**recreated ADR-0090's own defect at a new seam** — a vocabulary owned by core, mirrored where
nothing forces the copies to move together; a seventh kind would bucket as unknown and emit nothing.
That is #68 with the labels changed, shipped by the MR that exists to prevent #68.

So `CLAIM_EVIDENCE_CLASS` lives in `mosaera_core/claims.py` beside `ORACLE_KINDS`, **total** over it
and guarded by `test_claim_evidence_class.py`; policies declares `ClaimEvidenceClass` and receives
`claims_failed_classes`. The flat id list is **unchanged**, so `GateDecision.unsatisfied_claims` — and
the receipt seal computed over it — stay byte-for-byte.

### 3. The admission matrix

| reason | class | Layer 2 | why |
|---|---|---|---|
| `claim_behavioral_failed` | `shortfall` | **admits** | the oracle is `state["tests_passed"]` verbatim, so it restates `validation_failed`, which the arms already admit. #84 proved this from the mechanism; 88% grader-PASS over n=50 |
| `claim_structural_failed` | `objection` | denies | the one kind that reads the delivered tree — genuine independent evidence, and 69% grader-FAIL over n=54, i.e. those parks are mostly right |
| `claim_integrity_failed` | `tamper` | never | the tamper guard wearing a claim's name |

**The ESCALATE nuance is deliberately out of scope.** ADR-0090's matrix wanted structural denied to
Layer 2 but admitted to ESCALATE. `reasons_of_class` is class-granular, so "ESCALATE admits
`objection`" would admit *every* objection — `security_findings`, `reviewer_blocked`,
`reviewer_conflict`, `critic_vetoed`, `validation_unavailable` — which `escalate_arm.py` holds out by
the allowlist and by nothing else. That is a permission change two modules from where it would be
written. Per-arm class tuples are the architecturally correct successor and are **not** a second
origin (classification stays single-origin; only per-control policy differs), but they are
precondition-gated on MR3's stale-`gate_decision` defect: admitting a class to an arm that reads a
stale input means you cannot state what you just permitted.

### 4. `unsatisfied_claim` is kept, not removed

`give_up_allowed_reasons()` is evaluated against **stored** reason arrays on live paths — the API
disposition sweep, `convertible_decline_reason`, the bench park-reason tally. Removing the member
would make every historical park carrying it non-admissible again: **#68's shape re-created over
stored data**, across 118 scorecards. Its class stays `objection` — reclassifying the legacy union
would retroactively admit all of them to Layer 2, a permission change hiding in a compatibility line.

It also remains the honest **fallback** when a caller supplies ids without classes: *"a claim failed,
we cannot say which kind"* is exactly what the string has always meant, and being an `objection` makes
it the least admissible answer.

### 5. `claim_integrity_failed` is emitted despite being redundant today

The `tests_unmodified` oracle is `bool(state["tests_modified"])`, and `nodes_review` passes
`tests_tampered` from the *same* boolean — so it can never fire alone. Emitted anyway: no suppression
argument to defend, and a guard for the day the two diverge.

## Red team — 3 rounds, and R3 broke a decision in this ADR's own plan

**R1 — gate permission monotonicity.** The exhaustive cross-product, green, shipped as a test.
Verdict: **no finding.** Deny-preservation holds over the whole input space.

**R2 — what newly ships.** The intended win converts; adding `claim_structural_failed` blocks;
`claim_integrity_failed` blocks; the legacy union stays non-admissible. **One finding, ACCEPTED:**
a structural claim whose row is `unevaluable` rather than `failed` emits no structural reason, so a
park can convert with the requested AST shape unproven. This is pre-existing (`unevaluable` has never
emitted a reason — deny-by-default in both directions, the `structural_spec_ok` None semantics), and
MR2 makes it *reachable* rather than introducing it. Accepted because the alternative — treating
"could not measure" as "failed" — would park correct work on the engine's own inability to look, and
Layer 2's own evidence gates still apply. Recorded, not fixed.

**R3 — stored data, terminal readers, and the breaker. FIX-NOW against this ADR's own plan.**
All 299 stored cards replayed through `give_up_allowed_reasons()` old vs new: **0 admissibility
changes**. Then the plan's D5 — *fingerprint reason CLASSES instead of strings, to stop the split
losing stall trips* — was tested and **refuted twice over**:

1. **It does not fix the case it was written for.** `behavioral` and `structural` are different
   classes, so a run whose failing claim changes class still gets a different fingerprint.
2. **Where it does differ from strings, it is actively wrong.** `validation_failed` and
   `oracle_unverified` are both `shortfall`, so a run progressing from one blocker to a genuinely
   different one would have its streak *held* and be cut off — precisely the guardrail ADR-0069
   built: *"a CHANGED deny reason (progress through different blockers) RESETS the streak, so a run
   still working toward a ship is never cut off."*

**Reverted.** And the premise was wrong too: the trip "loss" from a split is not a regression, it is
ADR-0069 working as designed at finer granularity — finer reasons mean finer progress detection and
fewer premature stops, which is the direction that ADR wants. **ADR-0069 is therefore untouched by
this ADR**, contrary to the plan it was implemented from. The rejected design and its two refutations
are recorded in `stall_signature`'s docstring so it is not re-proposed.

**One further FIX-NOW, self-inflicted, found during implementation:** the first draft's
no-classes fallback emitted `claim_behavioral_failed` — a `shortfall`, i.e. the **most** permissive
class. A fallback that is not the least admissible answer is not a default. Changed to the legacy
union (`objection`).

**STOP rule:** not tripped. R2 and R3 surfaced different defect classes.

## Consequences

**Good.** The Layer-2 converter is unblocked on the dominant over-park shape without any change to
what the gate permits, and that is *proved* rather than argued. The `ORACLE_KINDS` seam gets the same
totality guard as the reason seam, so the next oracle kind fails loudly instead of silently emitting
nothing. And a red team run against the plan — not just the code — removed a change to a frozen
control that would have made the breaker more aggressive.

**Accepted residuals.**
- **Eligibility is not conversion.** `disposition_gap_close` remains default OFF with zero production
  conversions ever. This makes the dominant shape *eligible*; whether Layer 2 converts it, and with
  what mutation outcome, is the next measurement.
- **The unevaluable-structural gap** (R2's finding above).
- **The ESCALATE arm's class tuple**, gated on MR3.
- **`bench/compare.py`'s `park_reasons`** tallies raw strings, so old and new cards split into
  separate buckets across this boundary — it under-counts each rather than breaking.
- **`bench/containment.py`** substring-greps the truncated `give_up_reason` prose for `"test"` /
  `"oracle"` to route a measured bucket, and carries a dead branch on `tampered_integrity`, a reason
  string that has never existed. The give-up sentence is now truncated structurally (whole reasons
  dropped with a `+N more` marker, count position unchanged) specifically so that exposure is not
  newly perturbed — but the prose-grep itself remains wrong and is filed.

**Amends ADR-0090** — §4's deliberate misclassification is resolved, and its migration-hazard residual
is discharged with the smaller measured shape. **Amends ADR-0079** — its "ONE stable reason string"
becomes one string *per evidence class*; the ids still ride the decision. **Amends ADR-0075** — the
allowlist's *membership* changes, not just its origin. **ADR-0069 is NOT amended** (see R3).
