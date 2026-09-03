# ADR-0110 — A producer may not disown a failure without evidence

- **Status:** Accepted (owner-ratified, 2026-08-23)
- **Owners:** @rengi
- **Related:** [ADR-0085](ADR-0085-oracle-defect-detection-strategy.md) (§1, the case-specific
  detector freeze), [ADR-0090](ADR-0090-gate-reason-classification.md) (`REASON_CLASS`, the
  classification-table pattern), [ADR-0107](ADR-0107-decision-specific-admission.md) (one decision
  table per arm), [ADR-0087](ADR-0087-test-contracts-and-renegotiation.md) (the contract registry that already
  records ownership), [ADR-0013](ADR-0013-adding-an-agent.md) (the one ownership
  boundary that is fully built), [ADR-0046](ADR-0046-posture-and-autonomy-governance.md) (posture can
  only tighten)
- **Related issue / MR:** LedgerCLI operator session 2026-08-23, runs `20260823-220123-d624b9`
  (misroute) and `20260823-210924-b6cfe2` (correct route). Slices:
  #111 (environment truth),
  #112 (ownership taxonomy),
  #113 (role context); the observed
  defect is #114 (F81)
- **Review trigger:** a second ownership class is proposed with no tool evidence behind it, or a
  measurement shows the ownership taxonomy changed a containment outcome

## Context

Driving LedgerCLI to a finished product on 2026-08-23 produced **both halves of the team-behaviour
question inside one session**, which is why this is worth deciding from evidence rather than
designing cold.

**It routed correctly once.** Item #122's acceptance test asserted `assertNotIn('', content)` where
`content` is an empty CSV. In Python `'' in ''` is `True`, so that assertion can never pass whatever
the implementation does. The coder recognised the wall was not its to climb, named the contradiction
precisely, and escalated for a decision. The operator authorised an amendment; the **Proctor**
rewrote the test; the producer never touched its own acceptance bar.

That was not luck, and not model quality. It is **encoded three times over**: `prompts.py`'s
`_CODER_TESTS_PROTECTED` states the boundary in words, `tools/repo/factory.py` physically refuses the
write and re-checks by hash, and ADR-0087's contract registry records `owner_item_id` per test file
so the escalation could name the owner.

**It misrouted twice.** Item #126 asked the coder to distinguish a missing data file from an empty
one. It wrote `_validate_csv_file`, hit an `UnboundLocalError` in its own new code, and concluded:

> *"there's a discrepancy between what I'm editing and what's being executed — likely due to Python
> caching or installation issues"*

It escalated twice on that theory, across two rounds of operator correction, and never delivered.
The defect was a local variable read on a path where it had not been assigned — entirely inside the
producer's own accountability.

**The difference is the presence of a control, not the presence of intelligence.** Where an ownership
boundary is encoded and tool-enforced, the producer routes correctly. Where it is not, the producer
*guesses* — and a producer facing a question it has no instrument to answer will invent an answer
rather than park.

### This defect class is not new, and the prior art constrains the fix

**F87 is the same shape, already measured** (`docs/roadmap.md`, fixed 2026-08-21). `sandbox_exec`
probed with the engine's interpreter while validation ran `.venv/bin/python`, so every probe raised
`ModuleNotFoundError`. Run `20260821-023819-4ad38a` spent **291,846 coder tokens ($0.93)** concluding
*"the tests are failing due to network issues with installing dependencies"* — while validation ran
the same suite to **79 passed**. The code had been correct throughout. Pointing the probe at
`project_interpreter(workspace)` measured **−62% coder tokens** on a comparable item.

So the producer has now invented *"network issues"* (F87) and *"Python caching"* (today) for the same
underlying situation: **it cannot see its own environment, so it narrates one.**

**ADR-0085 §1 forbids the obvious next move.** `tools/repo/_exec.py::_uninstalled_note` is already a
hand-written detector for exactly one misdiagnosis — it fires only when an import failure coincides
with a missing venv. Adding a second note for "caching" would be the fifth-detector pattern that
freeze exists to stop. The answer must be a **general fact surface**, not another special case.

**ADR-0090 supplies the pattern for the routing half.** `REASON_CLASS` put the classification table
one edit away from the `GateReason` Literal precisely because a privately-held list went stale and
narrowed both disposition arms to nothing (#68/F62). Any ownership map must live under the same
discipline or it will rot the same way.

## Decision

Three slices, sequenced. The sequence is itself the decision — see §*The load-bearing rule*.

### Slice 1 — environment truth

Give the producer a **deterministic fact surface** it can query instead of theorising: for the
package under test, the resolved module file, its hash and mtime, the interpreter in use, whether an
editable install points where the producer believes it does, and `sys.path`.

Extends the existing probe seam (`tools/repo/_exec.py`, reusing
`languages/python.py::project_interpreter`) rather than adding a new tool surface. Per ADR-0085,
`_uninstalled_note`'s special case is **retired into** the fact surface, not joined by a sibling.

This converts *"my edit isn't what's running"* from an unfalsifiable belief into a checkable claim.

### Slice 2 — the failure-ownership taxonomy

Today's escalation vocabulary (`escalate` / `blocked` / `no_progress`, `graph/_supervise.py`) says
*that* the producer is stuck and never *whose problem it is*. Add an ownership classification, one
table, adjacent to the reason vocabulary, so a new reason and its owner land in the same CODEOWNERS
review:

| symptom | owner | evidence required |
|---|---|---|
| a protected test asserts the impossible | Proctor | the failing assertion + the contract-registry row |
| a bar the producer may not edit keeps failing | Proctor / Rook | `escalate_arm.blocking_protected_tests` |
| a traceback in the producer's own new code | **the producer — keep working** | slice-1 facts show the tree is consistent |
| the tool or sandbox contradicts what was written | environment → park | slice-1 facts show the mismatch |
| the acceptance contradicts the brief | Quincy | the brief clause + the criterion |

This **extends `escalate_arm.py`**, which already classifies blocking failures
(`_classify_blocking`, `blocking_protected_tests`, `ask_withheld_reason`) and already separates *may
I SHIP* from *may I ASK*. It does not introduce a parallel mechanism.

**Placement is an open sub-decision to settle before building.** ADR-0090's precedent argues for the
table beside `REASON_CLASS` in `packages/policies`; against that, routing an escalation is not an
admission decision, and `policies` is the trust boundary. If it lands in `policies`, the change is
**red-team-required** under the scoped protocol.

### Slice 3 — role context

Give each agent a structured map of the other accountabilities and their boundaries, assembled from
the six already written in `CLAUDE.md` and delivered as **context** in `agents/prompts.py`. Today the
coder knows the Proctor exists only because ADR-0013 forced the issue, and knows nothing of the
reviewer, the scanner, or the gate.

### The load-bearing rule

**A producer may not classify a failure as "not mine" on its own say-so.** Every branch of the
ownership table must be **tool-backed** — which is why slice 1 ships before slice 2, and why the
table above carries an evidence column rather than a description column.

Get this wrong and the outcome is **strictly worse than the status quo**: today's failure was
visible spinning, and a mis-tuned taxonomy converts it into confident disowning. A run that parks
citing "the environment" reads like a run that reasoned well. Spinning at least announces itself.

## Non-goals

- **No gate relaxation.** *Independent Approval* and *Deterministic Final Authority* remain MUST, and
  ADR-0046's posture-can-only-tighten stands. What grows with maturity is the **posture** — how much
  runs unattended, how often a human is consulted — never the gate's authority. The 2026-08-23
  session is the argument: the gate refused item #126 over four real failures, and that refusal is
  the only reason the two items that passed can be trusted. Agent autonomy is safe *because* the gate
  is unconditional.
- **No conversational agent-to-agent messaging.** It stays on the North Star's *Not Yet* list.
  Handoffs travel as typed, evidence-backed state through the graph. Agents negotiating directly is
  how plausible consensus arrives with no evidence under it.
- **No new agents.** This adds control points, not headcount.
- **No second case-specific detector**, per ADR-0085 §1.

## Consequences

- The producer gains an instrument for the one question it currently answers by narration. F87's
  measurement suggests the cost of *not* having it is large and concentrated in coder tokens.
- The escalation surface gains a *who*, which is what makes "this needs the tester" expressible
  without chat.
- **Residual risk:** a mis-tuned taxonomy teaches producers to disown their own bugs. Mitigated by
  the evidence column, by sequencing the falsifier first, and by measuring the misroute rate rather
  than assuming it fell.
- **Residual risk:** the ownership table is a second thing that can go stale, the failure ADR-0090
  documents. Mitigated by placing it adjacent to the vocabulary it classifies and by an
  exhaustiveness test in the ADR-0107 shape — a new class fails a test until every arm dispositions
  it.

## Evidence required before slice 2 is scoped

Slice 1 is measured in the shape F87 used: a comparable-item A/B on the same project and mode —
**coder tokens, coder calls, and misroute count**, before and after. The claim to prove is *"the
producer stops inventing environment causes."*

The honest failure mode to watch for is a fall in **visible** misdiagnosis with no fall in wasted
iterations — the producer narrating less while still spinning. If the measurement does not show
misdiagnosis actually falling, slice 2 is re-scoped rather than built on an unproven premise. This is
recorded here **before the number is known**.

## Alternatives rejected

- **A better prompt** ("first decide whether the test or the code is wrong" — already present in
  `_CODER_TESTS_OWNED`). It was in force during both failures. Without an instrument, a better prompt
  yields a more confident guess. *Deterministic-First* applies: a tool, not an exhortation.
- **A "caching" note beside `_uninstalled_note`.** Forbidden by ADR-0085 §1 and, on its own terms,
  unbounded — each new misdiagnosis would need its own hand-written detector, and the producer
  invented two different ones for the same underlying blindness.
- **Letting the producer self-declare ownership.** This is the dangerous version of the vision and
  the reason for the load-bearing rule above.
- **Agent-to-agent negotiation.** On the *Not Yet* list, and it would move coordination off the
  artifact trail that makes runs reconstructable.
