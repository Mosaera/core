# The Verb Arc — Claim → Refute → Gate

- **Status:** PROPOSED — DIRECTION. No production implementation authorized by this document.
- **Date:** 2026-08-08
- **Owner:** Mosaera core
- **Tracking issue:** #82 (Wave A)
- **Companion:** [`environment-arc.md`](environment-arc.md) (parked; this arc precedes it)
- **Authority:** subordinate to [`../architecture/north-star.md`](../architecture/north-star.md) and the ADRs. This document
  proposes; it decides nothing until each slice lands an issue and, where required, an ADR.

## Why this arc exists

The engine can only **add**.

Every mechanism we built is shaped for one verb: the coder writes files, the Proctor authors *new*
acceptance tests, the delivery gate certifies "a test that did not pass now passes," and delivery is
a diff that grows the tree. This is stated in our own source — `graph/_amendment.py`:

> *"A delivered test is currently a permanent, unamendable assertion, so the engine can only ADD —
> any item whose purpose is to CHANGE behaviour deadlocks against the test encoding the old
> behaviour. LedgerCLI hit it at item four: a five-line deletion took three runs and ~4M tokens and
> never shipped, with every control behaving correctly."*

Item 88 repeated it at larger cost: five runs, ~2.9M tokens, four findings — and the reason it never
shipped was none of them. Its acceptance required untracking a git file, which no tool performs.

The gap is not a missing tool. It is a **missing oracle per verb**:

| Verb | Tool gap | Evidence gap — the real one |
|---|---|---|
| **Add** | none | a new test passes ✓ |
| **Modify** | none | changing behavior requires an *existing* test to change; the tamper guard reads that as attack |
| **Subtract** | can delete a file (admin-opt-in), cannot untrack, cannot remove a dep | a deletion makes tests *disappear*; nothing can prove "nothing that mattered went with it" |
| **Refactor** | regex search only; no symbol rename, no AST | behavior preservation has no oracle beyond "tests still pass" — a weak proof |
| **Diagnose** | no debugger, no logs, no running app | the question cannot be asked |
| **Operate** | nothing | — |

## What the evidence says

Findings that drove the design (2026-08-08 research sweep; full citations in the session record).

**The work is mostly not authorship.**
- Xia et al. (ICSE 2018; 78 professionals, 3,148 measured hours): **~58% of engineering time is
  program comprehension.** Seniors spend a *smaller fraction* than juniors.
- Bacchelli & Bird (ICSE 2013): 44% of developers name defect-finding as their top reason for code
  review, but **only ~14% of review comments address defects.** The binding constraint on review
  quality is *context*; reviewers without it produce shallow comments.
- DORA's capability catalogue — the ~24 capabilities linked to the four key metrics — is almost
  entirely **infrastructure for feedback and reversibility**, not coding practice.

**Every non-additive verb needs an oracle for what must not change.** Refactoring needs
behavior-preservation evidence; deletion needs **proof of non-use** (strictly harder than proof of
use); delta debugging collapses without a reliable failure predicate; performance work needs
trustworthy measurement. Where the oracle is absent the activity degrades into rewriting-and-hoping,
and the literature's uniform response is to **stop and escalate** — Meta's SCARF deletes millions of
lines and drops tables autonomously, and asks a human wherever it cannot establish safety.

**A producer-owned oracle can invert the sign of the loop.** Reflexion made MBPP-Python *worse*
(80.1 → 77.1, −3.0), attributed to false positives from self-generated tests: correct solutions
discarded because the agent's own oracle was wrong. This is ADR-0013's separation of duties,
measured.

**Independence is asymmetry, not headcount.** Olausson et al. (ICLR 2024), the only cost-controlled
study: GPT-4 writing feedback for *GPT-3.5's* code beat both models' own self-repair. Human feedback
took repair success 33.3% → **52.6%** (1.58× over GPT-4 self-repair). Erroneous feedback: humans
**7/80**, GPT-4 **32/80**. Their verdict — *the bottleneck is the model's ability to critique its own
code.*

**Executed feedback beats prose feedback 4–6×.** Self-Debugging (ICLR 2024) held the loop constant
and varied only the feedback source: **+2–3%** with the model's own explanation, **up to +12%** with
executed unit tests. LDB pushed further with runtime variable state (+9.1 vs +7.3 for
explanation-based). The ordering *mechanical execution state > natural-language explanation* is
consistent across three papers.

**Context is no longer a lever.** NoLiMa (ICML 2025): **12 of 13 models claiming ≥128K have an
effective length ≤8K**; 11 of 13 fall to ≤50% of base at 32K. HELMET (ICLR 2025, 51 models): no
synthetic long-context task correlates >0.8 with real downstream performance, and needle-in-a-haystack
correlates *worst* — so never measure our own context handling with a needle test.

**The durability test for anything we build:**

> **Scaffolding that supplies evidence the model cannot generate about itself survives model
> turnover. Scaffolding that compensates for a model weakness decays within ~18 months.**

Durable: the deterministic gate, the Proctor, held-out oracles, execution feedback, independent
verification. Decaying: edit-format hand-holding, stuck hints, prompt scaffolding, role-splitting for
its own sake. (Cognition published *Don't Build Multi-Agents* in Jun 2025 and shipped multi-Devin
coordination in Mar 2026; Anthropic deleted a sprint-contract construct outright when a stronger
model landed.)

**Caveat on all of it.** These magnitudes come from benchmarks that measure single-shot,
add-a-feature, oracle-already-exists work. **There is no published benchmark for subtract, for
refactor-with-behavior-preservation, or for a governed multi-slice project.** The direction is
well-supported; the numbers are not transferable. Every slice below must be measured on our own
corpus.

## The spine

One artifact, three separations.

```
FORGE claims  →  ENGINE refutes mechanically  →  GATE checks completeness
(context, cheap,   (executed, engine-owned,        (deterministic,
 producer evidence, never the producer's)          final authority)
 inadmissible alone)
```

- **Forge owns the claim.** It just did the work, so it has the context Bacchelli says review
  quality depends on. Cheap and high-quality — and *never sufficient alone*.
- **The engine owns the evidence.** Refutation is a mechanical check that **runs**, not an essay.
  This is the 4–6× result and the Reflexion −3.0 guard, in one move.
- **The gate owns the decision.** A verdict string is an opinion; a structured claim is checkable —
  is every altered behavior accounted for, is there a consumer list, is there evidence per consumer.
  *Deterministic Final Authority* finally operating on evidence rather than parsing a narrative.

This satisfies *Independent Approval* by its own definition — independence from **evidence ownership
+ decision authority**, not from two prompts told to behave.

**Why one artifact covers three verbs:**

| Verb | What the claim must assert, and what refutes it |
|---|---|
| **Subtract** | "these referenced X; the enumeration is now empty" — **proof of non-use** (SCARF's shape) |
| **Modify** | "behavior X changed; consumers are A, B; evidence they still work is T" — the Hyrum's Law question |
| **Refactor** | "**no** observable behavior changed; the oracle establishing it is T" |

**Corollary that sets the tool order:** Forge needs the **comprehension** apparatus (find-callers,
symbol search, history); the refuter needs the **execution** apparatus. The artifact specifies which
tools are required, so we build what the evidence demands instead of guessing at a wishlist.

## Invariants each slice must name

**Advances:** *Evidence-Gated Advancement* (evidence per criterion, mechanically), *Independent
Approval* (three separations, not three agents), *Honest Parking* (park when the oracle is absent —
SCARF's own posture), *Capability through Auditability* (recording precedes opening),
*Deterministic Final Authority* (the gate reads structure, not verdict prose).

**Must not violate:** *Control Points, not Headcount* — no slice adds an agent. *Deterministic-First*
— refutation is a deterministic check, never a model call. ADR-0026 — any new state key is declared.
ADR-0046 — nothing here relaxes a posture.

---

## Slice 0 — `run_tests` takes a selector

**Pulled to the front:** small, safe, no trust-boundary change, and it speeds every slice after it.

`run_tests` currently takes **no arguments** (`tools/repo/factory.py`) — every check is the whole
validation plan. Every refutation in slices 1–5 wants to run *one* thing. The `run_tests` repeat-STOP
directive (3 identical failures) also currently fires on whole-suite identity, which is coarse.

**Evidence:** a run that changes one module verifies against a subset and the round-trip count drops
measurably on the bench; the repeat-STOP still fires on genuine no-progress.

## Slice 1 — SUBTRACT, end to end

**Status 2026-08-09 — 1.1/1.2/1.3/1.4/1.5 LANDED ([ADR-0095](../adr/ADR-0095-non-use-oracle-subtract.md)).**
The deadlock was reproduced before anything was built (every removal phrasing classified
`('none', True)` — a material claim with no oracle), then closed: a `non_use` oracle kind, a
deterministic non-use oracle, `delete_file` as the capability (git deferred), a `removal_unproven`
gate reason in its own evidence class, and MCB-27, the corpus's first subtract case. **Still owed:**
the slice's own success criterion — the two replayable failures re-run end to end.

**Goal:** an item whose purpose is removal either delivers with proof, or parks naming the capability
it needed. Today it deadlocks.

| # | Item | Notes |
|---|---|---|
| 1.1 | **Removal claim** — Forge states what it removed and what referenced it | Declared RunState key (ADR-0026); persisted; producer evidence, inadmissible alone |
| 1.2 | **Non-use oracle** — engine-owned mechanical enumeration of references to the removed thing, asserted empty | The load-bearing piece. Deterministic, no model call |
| 1.3 | **The removal capability** — scope precisely: `delete_file` is admin-opt-in; untracking has no tool | **Trust-boundary → red-team-required.** "Delete a file" and "untrack a file" are different blast radii; git may wait |
| 1.4 | **Gate integration** — `removal_unproven`: removal without a non-use proof cannot ship | `packages/policies` — CODEOWNERS |
| 1.5 | **A subtract bench case** | MCB covers greenfield/bug-fix/feature/refactor/robustness. No subtract case exists; without one the slice is unmeasurable |

**Evidence:** item 88 and LedgerCLI item 4 — both real, both failed, both replayable — deliver or park
with an accurate capability reason; the new bench case moves off zero.

## Slice 2 — Execution feedback

**Goal:** close the largest measured harness gap.

| # | Item | Notes |
|---|---|---|
| 2.1 | **Raise the `sandbox_exec` ceiling** — today 30s / 4KB / read-only mount / Docker-only | The read-only mount is a deliberate ADR-0059 fail-closed property. An **opening**, not a knob turn → red-team-required |
| 2.2 | **Runtime state, not just stdout** (the LDB result) | Largest unknown in the arc; deferral candidate |

## Slice 3 — Attribution, re-scoped

**Goal:** make "the model couldn't" falsifiable — the prerequisite for ever answering *where is the
model's ceiling*.

| # | Item |
|---|---|
| 3.1 | Record **feedback-signal degradation only**: execution unavailable / truncated / never ran; `done_reason == "length"` per role; a claim that could not be checked. **Not** view caps |
| 3.2 | One declared RunState key, two readers: `Run.diagnosis` (live) and bench `meta` (the ceiling question) |
| 3.3 | **ADR:** a model-ceiling claim is **inadmissible** when a harness limit bound during that run; recording precedes opening (ADR-0063) |

Deliberately ~⅓ of the originally drafted instrument. The research is clear that the constraints that
matter degrade the *feedback signal*; counting `_MAX_LISTING` hits is bookkeeping.

## Slice 4 — MODIFY · Slice 5 — REFACTOR

**Slice 4 status 2026-08-09 — LANDED ([ADR-0097](../adr/ADR-0097-consumer-impact-modify.md)).**
A `consumer_impact` claim + `impact_unassessed`, reusing slice 1's reference walk. The design
INVERTS slice 1: the oracle is the discriminator (did anything already depend on this symbol?), so
over-matching is harmless — `_REMOVAL` had to be narrow only because its oracle could not tell.
**MCB-28 added**: measured, the corpus had no MODIFY item (all 14 modify-verb sentences are nouns,
discourse markers, API names, or a refactor's *preservation* clause). **Slice 5 remains BLOCKED** —
its diff-scoped mutation oracle is the mechanism the 2026-08-09 sweep is finding may not
discriminate at all.

Same artifact, harder oracles.

- **4** — behavior-change claim + consumer enumeration (Hyrum's Law). Connects to ADR-0087's
  amendment path, which already half-exists.
- **5** — behavior-*preservation* claim, with **diff-scoped mutation testing** as the oracle
  (Petrović & Ivanković: mutants restricted to the diff, arid lines suppressed — the trick that made
  it affordable over ~2B lines).

## Slice 6 — Comprehension apparatus for Forge

find-callers, symbol-level search, git history read. **Deliberately last of the verb slices** —
pulled by what 4 and 5 demonstrably need, never guessed at now.

## Slice 7 — Project lifecycle · Slice 8 — Doctrine

The vision's actual centre of gravity; last because they are worth nothing on runs that cannot
finish. Owner-stated 2026-08-08:

> *"Doctrine should bind but be pivotable. If someone builds a project for themselves like a
> self-hosted one and then decides this would be a great SaaS, then now they need to build the scale
> and everything else to function for the masses rather than a homelab."*

- **7** — project **charter** (class + elicited parameters, not an enum: public surface? persistent
  data? multi-user? secrets? operated by someone else?) · the **slice** as the unit of work above the
  item · **class promotion emits a gap backlog** — which is the North Star's brownfield promise made
  mechanical · the **rebuild-recommendation** artifact, i.e. *"this foundation is wrong"* as a
  slice-level output.
- **8** — doctrine in three layers: **global capability catalogue** (DORA-derived — the only field
  doctrine with outcome data behind it), **class profile** selecting which capabilities bind, and
  **project charter** which may tighten and record explicit exceptions, never loosen silently
  (ADR-0046's principle applied to class). Prove **one capability checkable end to end** before any
  catalogue.

**Guardrail:** class moves **up freely, down only as a recorded exception** — otherwise "let's call
this a homelab tool again" becomes a way to make auth stop being required.

**Doctrine must not encode folklore.** The research sweep flagged as unsupported: the 100×
cost-to-fix curve (traced to a study that does not exist), "10× developers," the Standish CHAOS
family, Lehman's increasing-complexity law (invalidated in most replications), Project Aristotle's
specific ranking (the psychological-safety *construct* is well-founded; Google's ordering is
unpublished and unreplicated), and Team Topologies' cognitive-load quantification (well-argued
practitioner theory, no validated instrument).

## The unit of work

Falls out of the vision rather than being chosen:

```
Project  (class + charter: which standard binds)
  └─ Slice   ← the unit. leaves the product shippable and standard-meeting
       └─ Item   ← what Quincy already produces
            └─ Run  ← what exists today
```

We have the bottom two; a project is currently a flat bag of items with no notion of *"MVP"* or
*"this stage is complete."* The helper-script repo is the degenerate case — **one slice, one item,
lowered standard** — which is what makes the system feel like a firm rather than a bureaucracy.

## What this arc explicitly does not do

- **Does not add an agent.** *Control Points, not Headcount*; and role-splitting is the decaying kind
  of scaffolding by the durability test above.
- **Does not spend further on context.** 32K is already where most models sit at ≤50% of base.
- **Does not pull in the environment arc** (persistent sandbox, dev servers, git-in-environment)
  beyond the narrow execution-feedback opening in slice 2. That arc stays parked.
- **Does not rebuild Rook wholesale.** The claim artifact lands *beside* the existing verdict; the
  verdict is retired only once the artifact outperforms it.
- **Does not define a class enum.** Elicited parameters, with human-friendly presets over them.

## Where this lands in existing work

Most of this arc is **already tracked**. Opening parallel issues would be the second-origin defect
class applied to the backlog, so the mapping is recorded here and the umbrella is
#82.

| Slice | Existing issue | Why it is the same work |
|---|---|---|
| 0, 2 | **#55** *[arc] Coder reliability toolkit (sandbox_exec probe + rich failure feedback + diagnose loop)* | Open 20 days; this arc **is** slices 0 and 2, already scoped |
| 1.1–1.2 (the claim artifact) | **#67** *[F57] a criterion the tests never mention ships unimplemented — no criterion-to-test coverage check* | The claim artifact is the mechanism #67 has always lacked (F67: six of nine claims "satisfied" by one shared fact, no criterion→test attribution) |
| 3 | **#71** *[F39] an unreachable model endpoint is reported as the agent failing* | F39 shipped **planner-only**; slice 3 is its generalization |
| 7, 8 | **#6** *Capability profiles + fit/scope step (Atlas seed)* | ADR-0089 already declared itself "first real content behind #6" |

**Needs new issues:** slices 1.3–1.5 (removal capability, `removal_unproven`, the subtract bench
case), 4, 5, 6 — to be filed as each slice is sharpened, not up front.

### Must come first

- **#58 — `sandbox-e2e` is green by vacancy** (skips ~105 Docker/DB-gated tests, reports success).
  Hard blocker on slice 2: raising the `sandbox_exec` ceiling is a trust-boundary opening requiring a
  red team, and red-teaming an opening whose verification job does not execute is theatre.
- **#68 (F62) — the `unsatisfied_claim` allowlist gap.** Not a dependency, but the live named critical
  path, and an ADR question rather than an edit. Cheap; blocks a measurement.
- **#29 — the coverage ledger is "written but never read."** Slice 0's selector and slice 4's consumer
  enumeration may both be *reads of that ledger*. **Verify before building slice 0.**

### Would be rework without this arc

- **#54** — a Quincy-owned test-steward that *owns* the project's tests is the modify-verb problem.
  Building it before the claim artifact ships an owner with no oracle — the Reflexion −3.0 failure
  mode with a governance label. **Sequence after slice 4.**
- **#52** — "missing-behavior false-ship" is #67's shape; a separate detector is exactly what
  ADR-0085 warns against ("a photograph of a defect we already saw").
- **#23** — the durable cross-run work-packet store. If the claim artifact is the first real registry
  use case, the North Star's *"no generalized artifact platform before the first registry use case is
  proven"* Not-Yet clause is finally satisfied rather than pending.

## Open questions

1. ~~**Slice 1.3's exact scope**~~ — **ANSWERED 2026-08-09 ([ADR-0095](../adr/ADR-0095-non-use-oracle-subtract.md)):
   `delete_file` alone, no git capability in this arc.** The non-use oracle supplies the proof and
   `delete_file` performs the removal; untracking is a different blast radius that neither
   replayable failure needs. Deferred, not dropped.
2. **Where the claim artifact lives** — a declared RunState key, a `decisions` row, or the first real
   use case for the artifact registry the North Star names as DIRECTION.
3. **Whether slice 3 should precede slice 1.** Slice 1 has a concrete success criterion (two replayable
   failures), so it can be judged without general instrumentation — but slice 3 is what makes the
   *ceiling* question answerable, which is the arc's ultimate purpose.
