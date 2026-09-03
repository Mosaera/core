# ADR-0107 — Decision-specific admission: one classification, one decision table per arm

- **Status:** Accepted
- **Date:** 2026-08-21
- **Supersedes/amends:** amends [ADR-0090](ADR-0090-gate-reason-classification.md) (fifth `ReasonClass`, its own stated Review trigger); implements [ADR-0092](ADR-0092-claim-reason-split.md) §3's named successor
- **Related:** [ADR-0075](ADR-0075-engine-blocked-give-up-conversion.md), [ADR-0076](ADR-0076-independent-security-gate.md), [ADR-0082](ADR-0082-gate-decisions-and-standards.md), [ADR-0091](ADR-0091-clarification-proposal-kind.md), [ADR-0099](ADR-0099-undeclared-destruction.md)
- **red-team:** done 2026-08-21 — 3 rounds, 6 agents (see *Red team* below)

## Context

`REASON_CLASS` classifies every gate reason into `objection` / `shortfall` / `incidental` /
`tamper`. Three different controls then intersect that one partition to answer three different
questions:

| arm | question | what happens if it says yes |
|---|---|---|
| Layer-2 close-the-gap | may this parked run be **delivered**? | deletes tests, commits, opens an MR |
| ESCALATE (`escalate_arm`) | may I **ask** the operator a question? | writes one clarification onto a backlog item |
| supervise give-up | should the run **stop**? | ends the run honestly |

Those do not carry the same risk. The ask ships nothing, edits nothing and approves nothing — its
entire effect is `set_item_clarification` with `proposal_kind="direction"`, and ADR-0091 enforces at
the store boundary that such a proposal can never become acceptance text.

**Measured 2026-08-21, run `20260821-185000-08c6c2`.** LedgerCLI item #113 was driven into a genuine
oracle conflict. The run parked `incomplete` with an honest `termination_reason`, the audit recorded
`escalate-arm.suppressed | a gate objection rode the park`, and the item carried **no
clarification**. The objection was `security_unverified`. `graph/build.py` routes a supervise
give-up (and a plan-unworkable park) **straight to the gate, bypassing `scan_node`**, so an absent
scan is guaranteed on the only path that can reach this arm. The ask was refused 100% of the time.

`nodes_scan.security_unavailable_cause` had already measured this: **73 firings, all never-scanned.**
The knowledge existed and was deliberately kept out of admission, correctly, while every consumer of
admission was a ship decision.

**The exclusion's stated provenance was false.** `escalate_arm.py` claimed *"exactly the exclusion
ADR-0075 red-teamed twice."* ADR-0075 is dated 2026-07-23; this module was built 2026-08-06;
`ask_withheld_reason` 2026-08-21. Neither red-team round mentions a security reason — both attacked
a false **ship** (supersession deleting a human test, green-by-omission, the who-tests-the-test
residual). Decisively, on 2026-07-23 the reason **could not occur on this path**: `gate_node`
defaulted absent security to `"clean"` until `5677e7fc` (2026-08-07). ADR-0075 excluded a case that
did not exist; the case arrived later from an unrelated gate-tightening and landed in a clause
nobody re-read. ADR-0076's own R1 ACCEPT #1 scopes it out: *"the bypass routes rely on the
validation gate."*

And `security_unverified` is `objection` for no reason of its own — ADR-0090 MR1 was
behaviour-preserving **by construction**, required to reproduce ADR-0075's hand-written set exactly.
That ADR already records one knowingly-wrong entry from the same inheritance (`unsatisfied_claim`).
This is a second, unexamined one.

## Decision

**1. Split the security reason on whether the scanner ran.** `security_not_attempted` when
`scan_node` was never entered; `security_unverified` when it ran and produced no verdict. This
copies the `validation_unavailable` / `validation_not_attempted` split (F39, #71) for the same two
bypass edges, and inherits its governing property verbatim: `_resolve` is a positive allowlist, so a
new reason can only ever park. **This splits a message, never a permission.** `scan_attempted` is
not an inference — `scan_node` is the sole writer of `security_status`, so the raw key's absence is
proof, exactly as `validation_plan` proves `validation_attempted`.

**2. Add a fifth `ReasonClass`: `not_run`.** Holding `security_not_attempted` and
`validation_not_attempted`. It names the state the table had collapsed: *the check did not run*, as
against *the check ran and objected*. Reasons meaning "it ran and produced nothing usable"
(`security_unverified`, `validation_unavailable`) stay `objection` — only the never-entered case
moves.

**3. Each arm declares its own admissible classes.** `reasons_of_class` was already built for this:
*"this module classifies, it does not decide admission. Which classes a given control admits is that
control's policy and lives with the control."*

- SHIP arm — `("shortfall", "incidental")`, **unchanged**. `give_up_allowed_reasons()` is
  byte-identical, and `test_the_admission_set_is_exactly_what_adr_0092_authorised` passes untouched.
- ASK arm — `("shortfall", "incidental", "not_run")`, declared in `escalate_arm` beside the control.

Derived, never hand-written. A literal frozenset would be ADR-0090's stale-list defect at a fourth
origin. It also keeps the whole `tamper` family out by construction — which is what excludes
`content_destroyed`, since `ask_withheld_reason`'s own tamper check reads `tests_modified` while
ADR-0099 derives `content_destroyed` from `destroyed_paths`.

**4. Exhaustiveness is enforced.** `test_arm_admission_exhaustive.py` fails until every arm has
dispositioned every class as admitted or refused. Because admission is `set(reasons) - allowed`, an
unconsidered class silently defaults to *refused* — which is precisely how the ask died. `mypy`
cannot catch it: a `tuple[ReasonClass, ...]` typechecks fine while being short a member.

## Why this restores ADR-0075 rather than violating it

ADR-0075 is a delivery ADR. Its own module states the purpose: *"what keeps a security-objected or
critic-vetoed park from ever reaching an automated ship."* Every risk its red teams measured —
supersession deleting a human test, green-by-omission, the who-tests-the-test residual — is
structurally absent from writing a question onto a backlog item. Applying it to the ask was a
category transfer, not an inheritance.

Meanwhile the status quo violated three named invariants: **Honest Parking** (the arm reported a
suppression reason that was a routing artifact), **Capability through Auditability** (a control that
had never fired and could not), and **Control Points, not Headcount** (a control point with zero
liveness is not one).

## Prior art

The tri-state is standard everywhere it has been thought through, and we are the outlier:
XACML 3.0's `Indeterminate` is a first-class decision the PDP refuses to coerce into `Deny`; Rego
holds `undefined` apart from `false` and requires an explicit `default` to collapse them; SARIF
2.1.0 forbids a severity from attaching to any result whose kind is not `fail`; Kubernetes makes
"the check did not run" a separate knob (`failurePolicy`) from the webhook's verdict. SSVC states
the governing rule for reuse: shared *decision points* are fine, a shared *decision table* is not.

ISA-18.2 supplies the safety framing — it does not forbid suppression, it forbids **invisible**
suppression (§16.5: unauthorized suppression *shall* be detected, target zero), and notes that some
alarms are designed to disallow shelving at all. NFPA 72 §26.5.4.1.3 requires that placing
protection in bypass itself annunciate. Named in the North Star as **Unsuppressible Ask**.

## Consequences

- On a give-up park whose reasons carry no positive objection, the arm now writes a clarification
  instead of emitting `escalate-arm.suppressed`. Nothing else changes.
- `security_not_attempted` is `PROOF_BEARING` (its sibling's rule): whether a reason carries proof
  and which decisions may admit it are different questions — the whole of this ADR.
- The gate parks identically either way. No run ships that would not have shipped before.
- **Not addressed here:** `claim_structural_failed` remains `objection` with a measured 69%
  grader-FAIL justification, so it is a second suppression path. Our one live conflict carried
  `claim_behavioral_failed` instead; n=1. Measure co-occurrence before claiming the ask is live.
- **Not addressed here:** `is_oracle_conflict_escalation` still reads `gate_decision` at supervise
  time, where it can be stale. Inert on the give-up path today (the key is typically absent), but
  the drift ADR-0090 MR3 fixed for the ask exists one hop upstream for the stop.

## Red team

Three rounds, six independent agents, scoped to the merged change.

**R1 (3 agents).** The false-ship lens could not break the core claim: SHIP admission byte-identical
(proven by parsing the pre-commit table and diffing, not by reading), Layer-2 unreachable,
`_resolve` a genuine positive allowlist, no string-prefix escape, the `standards.py` partition
enforced at import, ADR-0091's boundary enforced in code, no XSS, and the clarification never
entering Quincy's context. Two HIGH defects, both introduced by this arc: the `effect` resume field
was dropped at `_resolve_escalation` (Slice 0a inert in production, found independently by two
agents), and the widening let a TAMPERING hand-raise reach the ask.

**R2 (2 agents).** The fix for the second was wrong in BOTH directions — over-block (it killed the
ask on the hand-raise branch this ADR exists to serve) and under-block (a stale clean verdict was
still trusted). Same defect class two rounds running on one control: **STOP rule tripped**, escalated
to a successor rather than patched a third time. R2 also found `amend_tests` ending the run while
promising it continues, and that this ADR's *Unsuppressible Ask* was true only in its "recorded" half.

**R3 (1 agent), verifying the successor.** `test_node` proven behaviourally unchanged by
DIFFERENTIAL EXECUTION against `b065bf37^` over six real workspaces. Over-block and under-block
closed on every reachable path. **Verdict: HOLDS**, no FIX-NOW, and no third instance of the defect
class the STOP rule was tripped on.

**The lesson, since it cost two rounds:** hardening a reader cannot fix evidence that was never
gathered. `tests_modified` / `destroyed_paths` were written only by `test_node`, which the
hand-raise bypasses, so every reader saw a falsy `.get()` and read it as *clean*. The successor puts
the computation on the branch (`graph/_tamper.py`, called from `capture_node`), which closes both
directions at once because they were the same bug. #75/F70 had already made this move for
`test_output`, on this same branch.

Open and accepted, none security-bearing: `tamper_signals_for_handraise` is not atomic, so a git
lock can report "no tamper check ran" for a check that ran clean (fails closed, reason inaccurate);
the withheld-ask project note is clobbered by the sweep (the audit row and the run decision are the
durable surfaces); `escalate-arm.suppressed` is reused for the legitimate already-affirmed case; and
a run parked across the deploy withholds once until it re-runs.

## Review trigger

A sixth `ReasonClass`, or a fourth arm intersecting this classification.
