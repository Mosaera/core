# ADR-0082: The gate asks a question, not for a verdict — decisions, and the standards they appeal to

- Status: **accepted** (2026-08-05, owner-ratified)
- Date: 2026-08-04 (accepted 2026-08-05)
- Owners: @Ashura
- Related: [ADR-0079](ADR-0079-claims-first-class-artifacts.md) (per-claim dispositions — the option
  source), [ADR-0080](ADR-0080-intake-clarification.md) (§1 answers at backlog time; the deferred
  `ApproveBody.answers` footgun), [ADR-0047](ADR-0047-project-onboarding-and-the-durable-map.md) (the trusted
  charter and its deliberately-prose constraints), [ADR-0072](ADR-0072-structural-spec-oracle.md)
  (the retired constant — the failure this ADR must not rebuild), [ADR-0081](ADR-0081-control-liveness-ladder.md)
  (liveness; the DoD below is stated in its terms), [ADR-0006](ADR-0006-durable-transcript-and-honest-outcomes.md)
  (honest parking)

## Context

The delivery gate today hands the operator **evidence** and asks for a **verdict**: a wall of
reviewer text, findings and claim rows, resolved by `approve(run_id, approved: bool, feedback: str)`.
Two problems, and they are different.

**The surface is wrong for the person using it.** An operator needs to know what will happen if they
choose each available thing. What they get is a report and a binary. The information that would
change their mind is mixed indiscriminately with information that would not.

**And the decision evaporates.** Every approval is a one-off. Answer "the shape is fine, correctness
is what matters" today and the same question is asked identically next week, because nothing durable
was minted. That is not merely tedious — it is the mechanism behind the suite's remaining
`false_ship`: **MCB-05 and MCB-15 disagree with the engine because the contract was never written
down.** Both briefs say only "a short orchestrator (a handful of statements)"; their graders assert
`<= 6` and `<= 7`. Two readers, one sentence, two numbers, and 6.9% of runs scored as dishonest
successes for a requirement nobody stated. ADR-0072 already retired the engine's own attempt to
derive that constant from prose, calling it provably unsound. Nothing replaced the missing contract.

The pattern that works is one we already use: `CharterProposal` takes chat prose, emits a
**structured** value, and the operator confirms *that* — with the red-team requirement recorded in
the code itself: *"the parsed posture is the truth, the chat prose is decoration."*

## Decision

### 1. The gate presents options, not evidence

Each open gate renders **actions with consequences**, one marked recommended:

> *Send it back with these notes* — adds one revision (2 of 3 remaining)
> *Accept the gap on record* — ships with `c3` unverified; the receipt says so
> *Ask Atlas whether our standards care about this*
> *Something else…*

- **The option set is computed, never authored by a model.** One option per disposable gate reason
  and per claim disposition (ADR-0079 already produces both). A model may write the *wording*; it may
  not decide what the choices are. This makes it structurally impossible to surface an option the
  evidence does not support.
- **The honest-park option is always present**, by construction, not by the generator's good manners
  (ADR-0006).
- **"Recommended" is derived and must state its reason**: prefer the choice preserving the most
  evidence while still unblocking — send back while revision budget remains, accept-the-gap-on-record
  once it does not, override last and always labelled as an override.
- **Progressive disclosure has a testable rule:** *the summary must contain any fact that would change
  which option is chosen.* Everything else belongs behind a drawer. This is reviewable, and it is the
  line between operator-first and hiding the inconvenient part.
- **`Something else…` shapes free text into a structured proposal** the operator confirms or edits.
  Editing modifies the **structured field** (`advisory` → `<= 8`), never a sentence that is re-parsed.
  The moment a value can be re-derived from prose we have rebuilt the MCB-05/15 failure one layer up.

### 2. Three tiers, and a clause is an appeal — not an exception

**Tier 1 — standing standards.** Authored deliberately, changed deliberately: the secure-coding
framework, structural limits, what code here should look like. **Bootstrapped from the standards this
repo already enforces deterministically** — the 500-line module ceiling, the one-way layer direction,
the doc-link and liveness guards — because those already have teeth, so tier 1 starts as fact rather
than aspiration.

**Tier 2 — derived clauses.** A clause **cites a tier-1 standard** and applies it locally. It is not a
carve-out; it is an application. Clauses may be **conditional**, which is the shape most real
decisions take:

> *There is no fixed statement count for this function — but if the module would cross the 500-line
> ceiling, shorten it or split the file.*

**Tier 3 — inferred taste.** Learned from what the operator actually accepts and rejects. Taste
**orders and phrases options; it never gates.** It may pre-select the likely choice and use the
operator's own vocabulary. It may never bind an oracle or resolve a claim — taste is induced from
behaviour, and behaviour includes mistakes.

### 3. Scope is inherited, and clauses do not expire

**Scope is not a field anyone chooses — it is the scope of the standard being cited.** Cite a project
standard, the clause is project-wide; cite an item's acceptance criteria, it is that item's. Widening
a clause therefore requires changing the standard it appeals to, which is a visible, deliberate act
rather than a slider.

**No expiry dates.** A derived clause's validity is a *function* of its parent, so when the parent
changes every clause appealing to it is stale **by construction** and is re-derived or flagged.
Provenance-based invalidation, not calendar ceremony — a dated review nobody actions is worse than
none, because it looks like a control.

### 4. A clause binds a registered parameter — that is what keeps taste away from proof

```
clause  id: cl-0004
        cites: standards/module-ceiling         # tier-1 parent; scope comes from here
        binds: structural.body_statements       # a REGISTERED oracle parameter
        value: advisory                         # advisory | <number> | unbounded
        when:  module_lines < 500               # optional condition
        because: "correctness over line count"  # prose — decoration, never parsed
        author: <operator>  ratified_at: …  provenance: gate <run_id>, counsel <role>
```

Two independent limits, either sufficient:

- **Structural:** a clause can only name a **registered oracle parameter**. "Remove the oracle from
  this claim" and "change the verdict" are not expressible, because there is no field for them.
- **Deny-list:** no clause may address a proof-bearing reason — `validation_failed`,
  `security_unverified`, tamper. Checked at write **and** read time, so a clause minted before the
  list grew cannot grandfather a waiver in.

**A clause may rebind a threshold its parent leaves open. It may never waive the requirement for
evidence.** "Six or seven statements does not matter, correctness does" is taste. "Ship without
passing tests" must remain inexpressible through this mechanism (North Star: no instruction silently
waives a control).

### 5. The approval contract, without ADR-0080's footgun

`ApproveBody` gains `option_id` (and optionally a clause to ratify). The frozen flat `gate_decision`
string is untouched. **An unknown `option_id` is REJECTED, never auto-approved** — the direct
mitigation for the hazard ADR-0080 recorded when it deferred `answers`: *"the runner auto-approves
unknown interrupt actions — a new action is a footgun."*

### 6. Counsel is DIRECTION, deferred to its own ADR

Routing a gate to Atlas / Quincy / Sentinel for a whole-project read is the intended companion, and it
is **not decided here**: it needs a holistic-context design and its own independence analysis. When it
lands, the invariant is already fixed by this ADR — **counsel drafts a clause proposal; the operator
ratifies it.** A model never mints a clause unattended, and counsel's text is an artifact on the
receipt, quoted and attributed, never a hidden prompt that produced a verdict.

## North Star implementation test

- **Artifact:** the tier-1 standard, the tier-2 clause (structured, with provenance), and the recorded
  option chosen at each gate.
- **Authority:** the operator ratifies; the gate remains deterministic. Agents propose only.
- **Independence:** the option set is computed from reasons the producer did not author; counsel (when
  built) may not advise on its own work.
- **Evidence:** the clause cited, the reason class it addressed, and the receipt naming both.
- **Failure:** an unknown option is rejected; a clause touching a proof-bearing reason is refused at
  write and read; absent a clause the gate behaves exactly as today. **Fails closed.**
- **Audit:** every gate resolution names the option and any clause applied, on the receipt.
- **Model substitution:** the option set and the clause semantics are model-free; only wording is
  generated.
- **Scope:** counsel, posture-scaled clause types (#31), and any generic Team API are explicitly out.

## Definition of done — pre-registered

Stated before building, in ADR-0081's terms:

1. **Clauses must not move `false_ship`.** A bench A/B, clauses ON vs OFF, **validated by
   `experiment_report` before it is scored**. A policy layer that opens a ship channel is a failure
   regardless of how good the UX is.
2. **The rubber-stamping metric:** the fraction of gates resolved by an *existing* clause versus a new
   one. Trending to 100% means the gate has stopped asking anything, which is the failure mode of this
   whole design and must be watched, not assumed away.
3. **C4 before any effectiveness claim** — the feature's own controls enter the liveness registry and
   must prove arm divergence before any result is cited (ADR-0081 Decision 4, forward-enforced).
4. **The first use case is MCB-05/15.** If a clause cannot express "correctness over line count" and
   change how those two cases behave, the design has not worked. That is the honest test, because it
   is the case that motivated it.

## Consequences

- The gate becomes a place where standards are *applied*, and occasionally authored — a larger UI
  commitment than a binary approval, and the reason the surface (1) and the artifact (2–5) ship before
  counsel (6).
- Tier 1 must be bootstrapped from the existing guards before tier 2 is useful: a clause with nothing
  to cite is the free-floating exception this ADR exists to avoid.
- Some current gate copy disappears. The reviewer's full text, findings and claim rows move behind
  disclosure; none of it is deleted, and the summary rule above decides what is promoted.
- **This ADR does not decide MCB-05/15.** It builds the mechanism by which that decision can be
  *recorded* rather than re-argued. The grader-alignment call remains the owner's — the evidence is
  assembled in `docs/engineering-history/grader-alignment-brief-2026-08-04.md` (pending on !323).

---

## Status note (2026-08-05) — what was built, and one addition

**Accepted by the owner**, and tiers 1-2 are built. The trigger was evidence rather than argument:
a paired A/B measured the day before acceptance moved control 0/6 to treatment 5/6 grader-clean
(Fisher exact p = 0.015) by stating a number the brief had left open — and the repair was authored
by hand, so nothing recorded it and the next item would have asked again. That is precisely the
gap this ADR names.

**One design addition, not in the ADR as written.** §4 gives two limits on what a clause may say
(a registered oracle parameter; the proof-bearing deny-list). The implementation adds a third that
is strictly stronger and nearly free: **each tier-1 standard declares the parameters it leaves
OPEN**, and a clause may only bind one of those. `standards/module-ceiling` fixes the 500-line
limit and leaves `structural.body_statements` open — so `module.max_lines` is not in the parameter
registry at all, and "waive the god-file ceiling" is unsayable for the same structural reason as
"change the verdict": no name exists for it. This turns §4's prose ("may rebind a threshold its
parent leaves open; may never waive the requirement for evidence") into data, and leaves the
deny-list a genuinely independent second net rather than the only one.

**Built:** tier 1 (code-declared, bootstrapped from the four guards that already fail CI), tier 2
(the clause artifact, Alembic 0021, ratify + read paths, the oracle overlay, the prompt block, the
`GET /standards` + clause routes). Behind `clauses_enabled`, default OFF.

**§1/§5 BUILT 2026-08-07 — the gate surface's own cut.** `gate_outcomes()` computes the available
answers with their real consequences, and **an answer that cannot function is not offered**: at the
iteration cap there is no send-back, because denying there ends the run and discards the notes
(F61, ~1.1M tokens). Options are computed from run state, never authored by a model; an override is
labelled as one and is never the recommendation; at most one option is ever recommended. A third
finalizing exception nobody had recorded — the gate-stall breaker making a denial terminal *as a
consequence of the denial* — is predicted and labelled. `ApproveBody.option_id` landed with an
unknown id **rejected (400), never auto-approved**, validated before the decision slot is claimed so
a typo leaves the park answerable; its real value is catching a **stale screen**, which honest labels
alone cannot do. The anti-drift property is enforced by construction: `route_after_gate` and the
presentation read ONE predicate, pinned across all 32 routing combinations.
**Still DIRECTION:** `Something else…` shaping free text into a structured proposal (§1's last
invariant), §6 counsel routing, tier-3 taste.

~~**Deliberately NOT built, and still DIRECTION:** §1/§5 the computed gate option surface and
`ApproveBody.option_id` — the first real use case turned out to be **intake**, not the delivery
gate, so the gate surface earns its own cut; §6 counsel routing; tier 3 taste.~~

> **Struck 2026-08-18** (`docs/audits/adr-corpus-review-2026-08-18.md`) — **it contradicted the paragraph directly above it.** Written while
> §1/§5 were deferred, it was left standing when they landed two days later. The code sides with
> BUILT: `gate_outcomes()` in `graph/_gate_outcomes.py`, and `option_id` in
> `apps/api/mosaera_api/schemas.py` with its own comment *"An unknown id is REJECTED (400), never
> auto-approved."* **Genuinely still DIRECTION** is the accurate remainder: §1's "Something else…"
> proposal shaping, §6 counsel routing (needs its own ADR), and tier-3 taste.

**Still owed, per this ADR's own definition-of-done:** the clauses ON-vs-OFF bench A/B validated by
`experiment_report` before scoring (DoD 1), the clause-resolution rate as the rubber-stamping metric
(DoD 2), and C4 before any effectiveness claim (DoD 3). Note `experiment_report` still has no
production caller, and `clauses_enabled` is not a *posture* knob, so `check_control_liveness.py`
will stay silent about it — that silence is not compliance. DoD 4 (MCB-05/15 expressible) is met:
the clause `structural.body_statements = 5` citing `standards/house-style` is exactly the decision
those cases needed, and it is a test.

## Amendment (2026-08-24) — a clause enters the criteria of an item that left it open, and no other

§4 says a clause **binds a registered parameter**. What it did not say is where the *rendered
sentence* is allowed to appear, and the implementation wove it into **every** brief regardless of
whether the item had left that parameter open. On the 0.6.3 candidate sweep that cost MCB-01
(greenfield, "build a todo CLI") **five of five runs**, each parking at ~1.7M tokens on a tree the
hidden grader passed 8/8.

The mechanism is worth recording precisely, because it is not "the reviewer was too strict":

- the brief asked for nothing structural, so the clause bound **no oracle** — the claim rendered
  `[ENTAILED → none]`, and the run's own scorecard reported `clauses_applied: []`;
- but the sentence was in the task text, and the **reviewer** read it as a requirement, returning
  `REQUEST_CHANGES` on every iteration for a 6-statement function;
- `reviewer_requested_changes` is an `objection` in `gate.py` and can never ship.

So an unbound criterion is not a stricter standard. It is an **unbounded model judgement with veto
power and no termination condition** — the shape *Deterministic Final Authority* exists to prevent —
and it reached that position through the one channel §4's registered-parameter limit does not
police: the prose the agents read.

**Amended rule.** A clause is rendered into an item's acceptance criteria **only where it actually
binds** — the same `extract_structural_constraints → apply_to_constraints → applied_marks` test the
claim oracle already uses to decide whether a clause *engaged*. Weaving and engagement can no longer
disagree; before this they could, and the disagreement was invisible in the record.

Three properties are deliberate:

- **The item's own number is never overruled.** `apply_to_constraints` already refused to; now the
  text agrees with it.
- **Relevance is judged on the whole item**, not the acceptance field alone — a structural ask is
  routinely typed into the title or description, and dropping a clause because of where the operator
  typed it would be the same defect with the sign flipped.
- **A parameter this test cannot judge is kept, not dropped.** Every registered parameter is
  structural today, so that path is unreachable; but silently discarding a ratified operator
  decision would be a waiver with extra steps.

**Unchanged:** the clause value, its ratification, and bench default-on. Post-amendment it applies to
**MCB-05 and MCB-15** — exactly the two cases DoD 4 names and the owner ratified it for (verified
across all 26 cases). `clauses_enabled` remains `False` in the product, so this corrects a latent
path there and a live one in the bench.
