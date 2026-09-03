# ADR-0091: A clarification declares what its proposals ARE, and the consumer denies by default

- Status: accepted
- Implementation: shipped (the discriminator, the refusal, the `bar_stands_retry` disposition, and the affirmation suppression)
- Date accepted: 2026-08-08
- Owners: Mosaera core
- Related issue / MR: F80; surfaced while scoping [ADR-0090](ADR-0090-gate-reason-classification.md)'s MR2
- Supersedes / Superseded by: — (**amends** [ADR-0080](ADR-0080-intake-clarification.md) §1; supersedes nothing)
- Related threat model: — (no new capability and no new deny at the delivery gate; this REMOVES a path by which an operator's bar could be replaced by a sentence about replacing it)
- Review trigger: a fourth clarification producer is added, or a third `proposal_kind` is proposed

**Decision summary:** A clarification records **what its proposals are** — `acceptance` (each is a
complete replacement acceptance text) or `direction` (each is guidance for a human). The resolve
endpoint honours a proposal index **only** for `acceptance`, and treats a missing discriminator as
`direction`. `proposal_kind` is a **required argument with no default** at the store boundary. The
ESCALATE arm additionally gains the operator position it never had: *the bar is right, the code is
wrong.*

## Context

`clarification.proposals` has **one consumer** — `resolve_clarification` — which writes the accepted
proposal into `backlog_items.acceptance` **verbatim**, through the same validated `enhance` path
every backlog edit uses. That is correct, and it is the contract two of three producers were written
against:

- the PM prompt states it — *"each proposal is the COMPLETE acceptance text the item would have if
  accepted (observable behaviour — inputs, outputs, errors — never vague qualities)"*;
- `intake_ask.divert_undecidable_to_asks` passes an `enhance` op's acceptance and says why —
  *"an `enhance` op already carries a complete replacement acceptance, which is exactly what a
  clarification proposal is."*

**The ESCALATE arm, added later, writes instructions to a human into the same field:**

```python
proposals=[
    f"Amend the acceptance criteria so {named} can pass as written.",
    f"Drop or rewrite the requirement {named} is checking.",
    "Add the missing input to the item so the test's expectation becomes reachable.",
]
```

`ClarifyCard` renders each proposal as a **button whose label is the proposal text**. So one click
set an item's acceptance to literally *"Amend the acceptance criteria so tests/test_add.py can pass
as written."* — destroying the operator's bar. The next run then minted every ENTAILED claim from
that sentence (`claims_from_acceptance` is pure and re-runs at launch; ids are positional
`{item_id}-c{n}`, so `42-c1` silently re-points to a different sentence).

`escalate_arm` is ON on the live instance, so this was reachable in production. It is reproduced end
to end in `test_an_escalate_proposal_can_never_become_the_acceptance`, which failed on the real arm
driving the real route before this change.

**This is ADR-0090's defect one layer out:** a later feature landing on a contract nobody had written
down, with every test green. There it was a gate reason a deny-by-default allowlist had never heard
of; here it is a producer whose strings mean something different from every other producer's.

## Decision

### 1. The channel declares its kind; the consumer denies by default

`PROPOSAL_KINDS = {"acceptance", "direction"}`, validated at the store's write boundary.
`set_item_clarification` takes `proposal_kind` and `axis` as **required arguments with no default** —
that is the whole mechanism. A default would silently readmit the defect the moment a fourth producer
forgets, which is exactly how the third one arrived. Forgetting is now a `TypeError` at the boundary.

`resolve_clarification` honours `accepted_proposal_index` only for `acceptance`. **A row with no
`proposal_kind` — every row already in the live database — is treated as `direction` and refused.**
Defaulting legacy rows the other way is the tempting migration and would preserve the defect for
every existing row. Operator-authored `edited_text` is always accepted, on any ask, so no one is
locked out.

### 2. The axis vocabulary is reused, not re-minted

`axis` is [ADR-0089](ADR-0089-intake-reachability.md)'s existing triple — checkability /
decidability / **reachability** — and the ESCALATE arm's situation *is* reachability. Minting a
parallel enum for the same distinction is the F62/F58 failure this repo has measured twice.

### 3. The arm keeps writing prose, and is not given a model

Rejected: have the arm author real candidate acceptance texts so the buttons could stay. Not for
*Deterministic-First* — that is only SHOULD on a post-run sweep — but for **provenance**. An accepted
proposal becomes the acceptance, from which everything mints as **ENTAILED**, while `claims.py`
states *"INFERRED claims (model proposals) enter via ADR-0080's clarification path, never here."* A
model-authored proposal plus one click would launder INFERRED into ENTAILED — a worse defect than the
one being fixed, and a contradiction of the arm's own charter (*"only the operator owns
requirements"*). The arm is deterministic; it knows the blocking paths and the producer's words, and
it does not know what the bar should become.

### 4. The ask stops being a leading question

Three operator positions exist. The card offered one and a half:

| position | before | now |
|---|---|---|
| the bar was wrong, here is the right one | `edited_text` | unchanged |
| **the bar is right, the CODE is wrong, retry** | **no representation** | `disposition="bar_stands_retry"` |
| not now | `rejected` | unchanged |

`rejected` collapsed the middle position into the button labelled as giving up. **The ask was leading
because of the affordance, not the strings:** every one-click action lowered the bar, keeping it cost
typing, and the free action read as surrender. Fixing only the text would leave that gradient intact.

`bar_stands_retry` leaves the acceptance untouched and **records the affirmation**. That record is
load-bearing, not decorative: the arm re-fires on every sweep and deliberately returns `True` so the
item skips the defer rung and stays visible. Without suppression the operator gets the identical
question forever, and the only answer that makes it stop is the one that lowers the bar. **Asking
once is a question; asking every sweep is pressure.** Suppression is matched per-bar (on the blocking
test names carried in the retained record), so a *different* wall still raises a fresh question.

## Consequences

**Good.** An operator's acceptance bar can no longer be replaced by a sentence about replacing it.
The defect class is closed rather than the instance: a fourth producer cannot repeat it, and mypy
already caught the fourth mirror of this contract (`_ClarificationStore`) during implementation,
which is the shape working. The engine also stops nagging an operator toward the easy answer.

**Accepted residuals.**
- **An acceptance change still leaves no versioned record.** `backlog_items.acceptance` is overwritten
  in place by four separate store writers, the resolve route emits no audit event, and the `"why"`
  passed to `apply_backlog_changeset` is discarded unread — so *"what bar was run R held to"* remains
  unanswerable. That is the companion gap and it needs its own ADR, a new model module (`models.py`
  is at exactly 500/500) and Alembic 0025. **Not closed here.**
- **A lowered bar still inflates a live reported number.** `delivered_items` and
  `calls_per_delivered_item` count `status == "APPROVED"` and are rendered on a card captioned
  *"Deterministic-first discipline"*; a trivially-satisfiable acceptance moves both in the flattering
  direction, and the number that would contradict them (over-park/Fidelity) is bench-only and does not
  exist live. This change removes the one-click route to that outcome; it does not instrument it.
- **The arm's second proposal is still hand-rolled.** *"Drop or rewrite the requirement the test is
  checking"* asks for a **test** amendment, which [ADR-0087](ADR-0087-test-contracts-and-renegotiation.md)
  already governs with a versioned registry carrying `authorized_by`, `amend_reason` and
  `amended_from_version`. Routing the ask into that path is the natural successor.
- **Suppression matches on the retained `claim_text`**, not on a stored blocking-path set. It is
  best-effort by construction: a store fault falls through to asking, because a lost suppression costs
  one redundant question while a lost ask costs the operator the question entirely.

**Amends ADR-0080 §1.** The clarification artifact gains two required fields. Its intake behaviour is
unchanged — the honouring producers keep one-click acceptance, asserted by a test, because a fix that
broke intake would be a worse defect than the one it closes.
