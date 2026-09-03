# ADR-0089: Reachability — intake asks whether the engine can BUILD it, not only whether it can be checked

- Status: accepted
- Implementation: shipped (axis + inventory); the ask ships **default OFF**, pending measurement
- Date accepted: 2026-08-07
- Owners: Mosaera core
- Related issue / MR: #78 (F76). First real content behind #6's "capability profiles / fit-scope step"
- Supersedes / Superseded by: — (**extends** [ADR-0079](ADR-0079-claims-first-class-artifacts.md)/[ADR-0080](ADR-0080-intake-clarification.md)'s intake axes; supersedes nothing)
- Related threat model: — (no trust-surface change; no new capability, no new deny at the gate)
- Review trigger: the measured precision of the ask, or a fourth intake axis is proposed

**Decision summary:** Add a third deterministic intake axis — **REACHABLE / UNREACHABLE** — asking
whether an item's acceptance demands work the engine's toolset can actually perform. Make the
capability boundary **machine-readable data** (`OUT_OF_CAPABILITY` in `packages/policies`), render
the PM prompt *from* that data, and match acceptance text *against* the same data so the two cannot
drift. The verdict is derived and displayed always; the **ask ships default OFF** behind
`intake_ask_unreachable`, because the ask-rate is a measured dial and a false ask blocks legitimate
work.

## Context

Item 88 burned **five runs and ~2.9M tokens** across four distinct findings, and the reason it still
could not deliver was none of them: its acceptance required untracking a git file, which no tool
performs. It is perfectly *checkable* (an oracle binds) and perfectly *decidable* (one answer) —
and unbuildable. `checkability` and `decidability` were both satisfied.

**The cost is not only the wasted run; it is the mis-framing.** An unreachable item surfaces at the
escalation gate as a *test* problem. Three of item 88's four findings were first framed that way,
the coder twice blamed a "read-only filesystem" for a missing capability, and the natural operator
repair — amend the blocking test — would have laundered a capability gap into a green run. The run
record shows that refusal was a close call.

**The root cause had never been written down: the capability boundary was prose inside a prompt.**
`_CAPABILITY_FRAMING` named what is out of capability as a **string constant**;
`describe_coder_capabilities` rendered it into Quincy's context; the PM prompt instructed him to
*"silently omit such work from the JSON array."* The deterministic intake checks (`spec_lint` —
pure, no I/O, no model) contained **zero** references to capabilities. The whole control against
unbuildable work was *tell a model what the coder cannot do and hope it filters*. That is an
instruction, not a control point.

## Decision

### 1. The capability boundary is DATA, and one rule reads it

`OUT_OF_CAPABILITY` is a tuple of entries carrying an id, the phrase the PM reads, **the evidence**
(which tool is absent, which guard refuses — so it is a claim about the engine, not an opinion), and
the surface forms an acceptance criterion uses to demand it. `_CAPABILITY_FRAMING` is rendered from
it, so the sentence the PM reads and the list the check matches are the same fact.

This is the direct answer to [ADR-0085](ADR-0085-oracle-defect-detection-strategy.md)'s lesson —
*"each class is a photograph of a defect we already saw"*. That freeze is scoped by name to
`faithfulness.py` and `roundtrip.py`, over authored test code, so it does not govern intake; but its
argument does. **The next unreachable class is closed by naming a capability, never by adding a
seventh regex.**

### 2. Matching is two-part, because a keyword list demonstrably fails

The red test failed on the first attempt: item 88's criterion — *"No file under
src/budget_tracker.egg-info/ remains **tracked** in the **repository**"* — never says "git". A
keyword list missed it, and the naive fix (trigger on `git`) fires on *"the README documents the git
workflow"*, which is ordinary buildable work. So an entry matches on an unambiguous demand **or** on
a weak term in the company of a context word. That failure is recorded here because it is the
evidence for the design, not a detail of it.

### 3. Precision over recall, and precision is what gets measured

A false ask blocks legitimate work behind a question; a miss costs what we already pay today. So the
corpus that governs this axis is **real acceptance text from items that delivered** (LedgerCLI
83–87), not fixtures. `govbench` gains `expect_reachability` beside its two siblings, and the
measurement that decides whether the ask may ship ON is **how often a fired ask was right**.

Two distinctions the first pass got wrong, now pinned: **declaring** a dependency is buildable (the
coder edits the manifest; the install phase reads it) while **running** an installer is not; and
**authoring** a migration is buildable while **applying** one is not. Firing on the first of each
pair would have blocked legitimate items.

### 4. It reuses the clarification channel exactly as it is

`askable_items` already returns `item_id → axis`; `REACHABILITY` is a third label. The clarify card,
the resolve endpoint and the launch block work unchanged — an open ask already blocks a run, with
the operator override intact. One ask per item still holds; reachability is checked last so it never
displaces a sharper question, though it is the ask that saves the most when it fires.

### 5. Default OFF, and asserted inert

`intake_ask_unreachable` mirrors `intake_ask_undecidable`. The **verdict is derived and displayed
either way**, so the signal is visible before it is binding — the posture `decidability` shipped
with. That it does nothing while off is asserted by a test, because a knob that ships off and is
never measured is how `disposition_gap_close` sat at zero conversions.

## Consequences

**Good.** A run that cannot succeed can be stopped before it starts, which is the reliability
program's shape. The capability boundary becomes a fact the system can reason about rather than a
sentence in a prompt — the first real content behind #6's "capability profiles", which had existed
only as a one-line annotation in ADR-0047. And an operator gets told *"this needs git, which the
delivery agent cannot do"* instead of discovering it four findings later.

**Accepted residuals.**
- **Recall is low and unmeasured.** Matching English prose for a required capability is inherently
  semantic; this catches item 88's shape and will miss others. Stated plainly rather than promised
  away — the mitigation is that adding a capability is data.
- **It does not fix the escalation gate's presentation**, where the same class shows up once a run
  has already started. That is the natural companion and belongs with ADR-0082's outcome machinery.
- **It does not make item 88 deliverable** — it makes it stop, and say why.
- The axis judges `todo` items only, like its siblings; a settled item is not re-litigated, and the
  status-blind `diagnose_item` path remains the backfill primitive.
