# ADR-0097 — A behaviour change must know who it breaks

- **Status:** accepted
- **Date:** 2026-08-09
- **Amends:** [ADR-0079](ADR-0079-claims-first-class-artifacts.md) (an eighth oracle kind), [ADR-0092](ADR-0092-claim-reason-split.md) (a fifth evidence class), [ADR-0094](ADR-0094-eligibility-structural-claim-widening.md) (the widening must not reach behaviour changes)
- **Scope:** `packages/core/mosaera_core/{claims,claim_oracles,consumer_impact,nonuse}.py`, `packages/policies/{gate,standards}.py`, `bench/cases/MCB-28`
- **Invariants:** *Evidence-Gated Advancement*, *Deterministic Final Authority*, *Honest Parking*
- **Implements:** verb-arc slice 4 (MODIFY)

> **ADR-number collision:** 0095 (slice 1) and 0096 (slice 3) are claimed on unmerged branches.
> Last to merge renumbers (CLAUDE.md's shared-namespace rule).

## Context

Slice 1 gave SUBTRACT an oracle. MODIFY had the mirror-image gap, and it **deadlocks or launders**:

When an item deliberately changes behaviour, the test asserting the OLD behaviour fails. The gate
sees `validation_failed` — **indistinguishable from "the code is wrong."** So the run grinds to the
iteration cap against a test it may not touch, or the coder edits that test and the change ships
with its own contract rewritten. Nothing records that the failure was the point.

ADR-0087 built the legitimate path (operator authorizes a scope, the Proctor rewrites the test) but
keys on freeform operator text, is one-shot, and is default OFF. There was no first-class statement
that *this item is a behaviour change*, and no record of **who depends on the behaviour being
changed** (Hyrum's Law).

Measured before building: `Change \`load_config\` to return …` mints `acceptance_test` today, whose
oracle is `state["tests_passed"]` **verbatim**. So MODIFY did not mint *nothing* — it minted a claim
that cannot tell *"the test failed"* from *"the test was supposed to fail."* Those are the same
boolean.

## Decision

**A `consumer_impact` claim kind**, minted on a leading MODIFY imperative or explicit passive,
ordered below `_REMOVAL` (a removal's oracle is stronger) and **above** `_BEHAVIOURAL` (which would
otherwise swallow it and restate `tests_passed`).

**The oracle is the discriminator, not the pattern.** A MODIFY verb is how ordinary work is
described, so the filter is a fact no regex can see: **did anything already depend on this symbol?**

| situation | verdict |
|---|---|
| nothing depended on it at HEAD | `satisfied` — new code, not a modification |
| it did; consumers found, ≥1 is a test | `satisfied` — witnessed; the blast radius is named |
| it did; consumers found, **none is a test** | `failed` — a behaviour change nothing asserts |
| unaskable (no symbol, unparseable) | `failed` — deny-by-default, slice 1's rule |

This **inverts slice 1**: `_REMOVAL` had to be narrow only because `non_use_proven` could not make
this distinction. Here over-matching is harmless by construction, which is the better property.

**Gate reason `impact_unassessed`**, its own `impact` evidence class, `objection`, `PROOF_BEARING`.
Its own class for slice 1's reason: Layer 2 verifies by authoring a **behavioural** test and
mutating it — precisely the evidence a behaviour *change* invalidates — so it would convert a change
nothing witnesses, against criteria derived from the behaviour being replaced. Pinned with
ADR-0094's widening knob ON.

**MCB-28**, the corpus's first MODIFY case. Not in the original plan — see below.

## The measurement that reversed the plan

The plan asserted *"no new bench case — MCB already has MODIFY-shaped cases"*, justified by a grep
claiming 19 of 25 briefs contained a MODIFY verb. **Both were wrong.**

The grep counted any occurrence anywhere, including prose. The real figure is 14 sentences across
25 briefs — and inspecting all 14, **not one is a behaviour-change item**:

- *"persist the change"* — `change` as a **noun**
- *"after your change:"* — a discourse marker
- *"Do not change any observable behaviour — this is a pure refactor"* — the **opposite** claim
- *"`update_user(...)`"* — an API name

So the pattern mints **0 of 372** real claims, and that is correct: the corpus has no MODIFY item,
exactly as it had no SUBTRACT item before MCB-27. Widening the pattern to catch those 14 would mint
on a refactor's *preservation* clause — the inverse of this claim. The slice was unmeasurable
without a case, so MCB-28 was added on evidence.

## Red team (1 pass — `packages/policies`)

- **R1 — can it turn a park into a ship?** No finding. Downgrade-only across the `tests_passed`
  sweep; 19 declared reasons, 19 classified.
- **R2 — can the filter be fooled into `satisfied`? CONFIRMED, FIXED.** A symbol **moved** to a new
  file read as "new code" (its new file is absent at HEAD) and its consumers went unassessed — a
  false `satisfied`, the only unsafe direction. Fixed by asking the better question: a **pre-existing
  consumer** is itself proof the behaviour could already be depended on. Hyrum's Law is about
  dependants, so that is the right predicate, not a patch.
  A second self-inflicted defect was caught in review before the red team reached it: the filter was
  first written **file-level**, which called a brand-new function in an existing file a modification.
- **R3 — can the witness test be trivially passed?** No finding. A test that does not reference the
  symbol is not a consumer, and a self-reference inside the defining file is excluded — counting the
  definer would make "someone depends on this" true for every symbol that exists.

## Consequences

A new way to park, on a verb class that appears in ordinary work. The oracle filter is the only
thing standing between that and a park storm, which is why the mint rate was measured against the
real corpus (0 of 372) rather than argued.

**Owed:** ~~MCB-28 executed end to end (needs the sandbox; queued), and~~ **— MCB-28 is DONE** (measured 2026-08-11, `docs/engineering-history/mcb28-slice4-measurement-2026-08-11.md`; then delivered `clean_deliver` with zero gate reasons once ADR-0100 landed, `mcb28-delivers-2026-08-11.md`; corrected 2026-08-18, `docs/audits/adr-corpus-review-2026-08-18.md`). Still owed: the ADR-0087 wiring — once a
behaviour change is a claim, the amendment path can key on it instead of on freeform operator text.
That is the natural successor and is deliberately not built here.
