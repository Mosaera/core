# ADR-0016: Deterministic mid-run model escalation — the escalation ladder, made runtime

- Status: accepted
- Date: 2026-07-12
- Owners: Alejandro Rengifo
- Related: [ADR-0002](ADR-0002-deterministic-first-and-model-agnostic.md) (the escalation ladder + `get_chat_model` seam this operationalizes), [ADR-0015](ADR-0015-tester-contract-scope.md) (the over-specification signal the diagnosis reads), [ADR-0007](ADR-0007-capability-benchmark-suite.md) (the benchmark that drives + measures it), [ADR-0012](ADR-0012-cohesive-team-supervision.md) (the honest-incomplete terminal signals reused for diagnosis)

## Context

The DNA escalation ladder (ADR-0002) — *cached evidence → deterministic tool → local small
model → local coder/reasoning model → cloud → human* — was doctrine but had no runtime
mechanism: a role was bound to one model for a whole run, and a run that failed because *that
model* wasn't strong enough simply parked. The MCB tester sweep (2026-07-12) made this concrete
and measurable: a **weak local** tester (`qwen3-coder:30b`) is net-negative, a **strong cloud**
tester (`claude-sonnet-4-6`) net-positive. The open question the user posed: rather than
hardwiring the tester to a cloud model (expensive, off-box), can we **start cheap and escalate
only when a run proves it needs to** — and do so *deterministically*, since choosing which model
to escalate is exactly the kind of decision that must be code, not another LLM call?

Two hard requirements fall out of the DNA: the escalation decision is **deterministic-first**
(no model call diagnoses the bottleneck), and it is **cost-disciplined** (escalate the one role
that's the bottleneck, never the whole team).

## Decision

**1. A per-role escalation ladder (`Settings.role_escalation`).** `role → [RoleModel]`, an
ordered list of tiers; tier 0 is the cheapest starting model, the last the strongest fallback.
Empty by default → no escalation. Configured by env JSON (`MOSAERA_ROLE_ESCALATION`) or
`settings.json`. **Cloud tiers are operator-configured — there is no default cloud tier**, so
escalation never auto-sends repo content off-box unless the operator explicitly put a hosted
model on a ladder.

**2. A deterministic diagnosis — `diagnose_bottleneck(final_state, settings) -> Role | None`.**
A pure function of the terminal run state's own honest signals (the gate's `reasons`, the parsed
reviewer verdict, the per-loop stall counters, the tester flag) — no model call. Priority,
most-specific first:
- planner never produced a grounded plan → **pm**;
- `validation_failed` **and the reviewer APPROVES** (or the explicit over-specification
  hand-raise, ADR-0015) → **tester** (its own suite blocks a reviewer-approved change);
- `validation_failed` otherwise → **coder** (no passing implementation);
- reviewer stuck on BLOCK with a tripped review-stall → **reviewer**, else the producer **coder**;
- `security_findings` → **coder**;
- otherwise `None` — nothing attributable, so escalate nothing.

**3. The scoped escalation — `escalate_role(settings, role) -> Escalation | None`.** Bumps only
that role one tier up its ladder (via `dataclasses.replace` — a new `Settings`, the rest of the
team untouched), or returns `None` when the role has no ladder or is already at the top tier
(the caller then ends honestly incomplete). It carries a human-readable path label
(`tester: ollama/gpt-oss:20b -> anthropic/claude-sonnet-4-6`).

**4. Benchmark-driven first cut, with a grader-informed success bar.** The
`diagnose → escalate → re-run` loop is wired into the **benchmark harness only** (`bench/cli.py`).
A run counts as a success only when it **delivers AND passes the hidden acceptance suite** — so two
failure shapes both count as a bottleneck: a non-delivery (a park) *and* a **false-positive ship**
(the run delivered, but the grader shows it fails acceptance — e.g. a too-lenient tester whose own
suite passed and whom the reviewer approved, so the run itself saw no failure). The run cannot
detect that false positive for itself; only the grader can, so the benchmark grades every attempt
and feeds `acceptance_failed` into the diagnosis (→ the tester when enabled, else the coder). The
culprit role is bumped and the work re-run — up to `max_model_escalations` — with the path recorded
in the scorecard. Live runs are unchanged (and, lacking a hidden grader, could only ever act on the
delivery signal — a reason the false-positive detection stays benchmark-scoped for now). The pieces
live in `mosaera_core/bench/escalation.py` (the diagnosis reuses the reviewer verdict parser from
`mosaera_agents`, which core proper must not import; the bench, an app-level consumer, already
does). Opt-in via `model_escalation_enabled` (default OFF).

## Consequences

- The escalation ladder is now an executable mechanism, not just doctrine: start the tester on
  `gpt-oss:20b`, and a failed run deterministically identifies the tester as the bottleneck and
  escalates it to `claude-sonnet-4-6` — cheap-first, cloud only on proven need.
- Attribution is fully deterministic and unit-tested offline; no model call decides who escalates.
- **Threat surface:** auto-escalation to a *cloud* tier sends repo content off-box automatically,
  which the base BYOM flow only did on an explicit per-run binding. This is gated (default OFF, no
  default cloud tier, operator must place the hosted model on the ladder), and in this first cut is
  benchmark-only — it cannot fire on a live run. Recorded in TM-0001. No allowlist/policy change.

## Alternatives considered

- **Reuse cost-modes as the tiers.** Cost-modes swap *whole-team* profiles; escalation must bump
  *one* diagnosed role. A dedicated ordered per-role ladder expresses that directly.
- **Let an LLM decide which model to escalate.** Rejected on the DNA: the decision is cheap to make
  from signals the graph already emits, so it must be deterministic code, not a model call.
- **Wire the loop into the live runner now.** ~~Deferred~~ **— DISCHARGED by ADR-0022** (noted 2026-08-18, `docs/audits/adr-corpus-review-2026-08-18.md`): the same pure pieces now run live in `apps/api/mosaera_api/app_context/_escalation.py`; only Amendment 1's no-op detector remains owed. Deferred at the time because: auto re-runs cost tokens/latency and can
  trigger off-box egress. Prove and measure it on the benchmark first (the scope chosen here), then
  graduate the same pure pieces to the runner behind the same flag.

## Amendment 1 — 2026-08-10: an escalation is believed only if the escalated role spoke

**Measured.** Across the stored corpus, **45 of 61 recorded escalations produced ZERO model calls
from the escalated role** — every one of the 45 binding `anthropic/claude-sonnet-5` on an unfunded
key. The 16 that did make calls all targeted on-box `ollama` tiers.

**Why that was worse than a wasted rung.** `_run_with_escalation` returned the FINAL attempt
unconditionally, so a no-op escalation *replaced* the tier-0 outcome that had really happened. The
run recorded `error=None`, and `escalation_path` still named the model — so a failed escalation was
indistinguishable from *"a stronger model tried and could not."* Read the second way, six MCB runs
produced conclusions that inverted when the same cases were re-run at tier 0:

| | escalated (void) | tier 0 (real) |
|---|---|---|
| MCB-27 `grader_passed` | False 3/3 | **True 2/2** |
| MCB-28 `grader_passed` | False 3/3 | **True 2/2** |

**Why the existing gate did not catch it.** `models.cloud_tier_allowed` requires egress consent and
a `model_prices` entry — correctly, because that is what lets the USD cap bound the spend. But
**priced is not funded**: an exhausted key, a revoked key and a typo'd model name all clear it
identically. Reachability cannot be established before a call is made, so no pre-check can close
this. The bench comment predicted the failure (*"binds an unpriced/unreachable cloud tier that
no-op's and OVERWRITES the tier-0 outcome"*) and guarded the *unpriced* half; the hole was
*unreachable*.

**Decision.** After an escalated attempt, `cost.role_calls(rollup, role)` asks whether the escalated
role made any calls — a signal that already existed, since a role with no successful calls
contributes no `by_agent` row. Zero calls ⇒ **discard the attempt, return the retained tier-0 pair,
and stop the ladder** (a further rung binds the same unreachable provider). The attempt is still
recorded in `escalation_path`; it is discarded, not hidden. The role→label mapping is
`AgentSpec.label` — the same field `agent_by_node` attributes spend with, so it cannot drift — and a
parametrised test pins every role, because a wrong mapping would read zero for all of them and
silently discard every escalation.

**Recording.** The card gains `escalation_outcome`: `""` (none attempted) · `"applied"` ·
`"no_calls_discarded"`. `escalation_path` only ever said what was *attempted*; nothing said whether
it *ran*, which is why the 45 cards are indistinguishable from real ones without this audit.

**The live path is NOT the same defect, and was deliberately unchanged at the time.**
`app_context/_escalation.py` re-launches the item as a *new run* with its own record, so a failed
escalation produces a confusing history rather than a destroyed one — no result is overwritten. The
same detector belongs there, but it needed the escalated role threaded into the run session, which
that change did not do. Recorded as owed rather than half-built.

> **Owed item DISCHARGED — 2026-08-24 (#119).** The escalated **role** is now threaded through
> `launch_item(escalation_role=…)` into the re-run, and `_after` asks `cost.role_calls(rollup,
> role)` before anything else. Zero calls ⇒ the outcome is recorded as `no_calls_discarded` with
> the role and attempt named, **and** written to the project note where an operator actually looks
> — an audit row alone would repeat this defect one layer up: recorded, never surfaced. The
> vocabulary is the bench's verbatim (`ESCALATION_APPLIED` / `ESCALATION_NO_CALLS`), pinned by a
> test, so a live escalation and a benchmarked one stay comparable. Nothing is discarded on the
> live path (there is no earlier result to overwrite); what was missing was the record itself.
> The detector is driven BOTH ways per role in `apps/api/tests/test_escalation_no_op_live.py` —
> a wrong role→label mapping would read zero for every role and silently report every escalation
> as a no-op, which is the failure inverted.

**Owed.** The 45 affected cards are catalogued in
[`engineering-history/escalation-no-op-audit-2026-08-10.md`](../engineering-history/escalation-no-op-audit-2026-08-10.md);
no card is deleted, and any aggregate spanning them carries that caveat.
