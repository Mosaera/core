# ADR-0031: Deliver on reviewer silence with deterministic validation (drop the tester-oracle requirement)

- Status: accepted
- Narrowed by: [ADR-0034](ADR-0034-only-executed-evidence-may-ship.md) — this ADR left `tests_passed is True` as the whole bar; ADR-0034 additionally requires `validation_strength == "suite"`. **The current delivery condition is ADR-0034.**
- Date: 2026-07-13
- Owners: Alejandro Rengifo
- Supersedes the delivery condition of: [ADR-0029](ADR-0029-reviewer-as-veto.md) (reviewer-as-veto)
- Related: [ADR-0025](ADR-0025-behaviour-smoke-gate.md) (the independent behaviour-smoke floor folded into `tests_passed`), [ADR-0020](ADR-0020-autonomous-correctness-gate.md) (the tester oracle), [ADR-0006](ADR-0006-durable-transcript-and-honest-outcomes.md) (honest outcomes)
- Related threat model: docs/threat-models/TM-0001

## Context

ADR-0029 made the reviewer a **veto, not a required sign-off**: an autonomous run whose
only blocker is the reviewer's SILENCE (`reviewer_unknown` — no parseable verdict) delivers
instead of false-parking, *provided an independent oracle vouched* (`oracle_verified` — the
tester's spec-derived acceptance suite ran and passed). That requirement had a hole: the
**tester is off by default** (`tester_enabled=False` — it costs a model call). So in the
default local configuration `oracle_verified` is always False, the ADR-0029 backstop can
never fire, and a **correct, fully validation-passing autonomous run parks whenever the
local reviewer emits no verdict** — which local models do often (the code notes ~75% on
MCB-21). This is the single biggest depressor of local autonomous delivery (it is why
MCB-11 parks despite passing its own tests and the behaviour-smoke floor). A false-park is
a working deliverable thrown away — the same failure class as the ADR-0025 `--help` bug,
one layer up.

## Decision

Drop ADR-0029's requirement that the **tester oracle** be present for the reviewer-silence
backstop. An autonomous run delivers on reviewer silence when the run's own **deterministic
validation is green** — `tests_passed is True`, which folds in the executed test suite
**and** the independent behaviour-smoke floor (ADR-0025) — and there are no security
findings (guaranteed by construction: any finding adds another reason, so the sole-blocker
check `core == ["reviewer_unknown"]` already excludes it).

Concretely, in `autonomous_resolution` (`packages/policies/mosaera_policies/gate.py`) the
condition changes from
`core == ["reviewer_unknown"] and oracle_verified and tests_passed is True`
to
`core == ["reviewer_unknown"] and tests_passed is True`.

Unchanged: a real objection (`reviewer_blocked` / `reviewer_requested_changes`) still hard-
vetoes; failing or absent validation (`validation_failed` / `validation_unavailable`) still
parks (those reasons stay in `core`); security findings still park; the backstop is
autonomous-only (human-gated runs never call it). `oracle_verified` is still **computed and
reported** on the decision — it is no longer a gate *condition*, but it keeps the outcome
honest about *which* evidence delivered (executed self-tests + smoke, vs the stronger
independent tester suite).

## Why this is acceptable (the trade-off, stated honestly)

Delivery still rests on **positive, executed evidence** — real tests plus the independent
behaviour-smoke floor plus a clean scan — never on the *absence* of an LLM objection. That
is the ADR-0029 principle; ADR-0031 only removes an oracle gate that was unavailable in the
default config. The honest cost: the coder's own tests are weaker than the tester's spec-
derived suite (the coder can write thin tests), so this raises the ship-wrong risk on tasks
where self-tests are shallow. Bounds on that risk: the behaviour-smoke floor is an
*independent* deterministic check (not coder-authored); the security scan must be clean; it
is autonomous-only (human runs still gate on silence); and an operator who wants the
stronger bar can enable the tester (`tester_enabled`) — then `oracle_verified` is True and
delivery rests on the independent suite, as before. The right long-term shape is per-tier
(a hardened profile re-requires the oracle) — deferred to the profiles work.

## Options considered

- **Enable the tester by default.** Rejected for now — adds a model call to every run
  (cost/latency) and reverses a deliberate default; ADR-0031 fixes the false-park without
  that cost, and the tester stays available for operators who want the stronger oracle.
- **Make the reviewer verdict more reliable (better parse / retry / stronger model).**
  Doesn't eliminate silence (local models still sometimes emit nothing); a band-aid, not a
  fix for the structural false-park.
- **Status quo (require the oracle).** Rejected — it parks most correct local runs by
  default, which is exactly the "stable Python" blocker this ADR exists to remove.

## Consequences

- Good: removes the biggest default-config false-park; autonomous local delivery rises
  without enabling the tester; delivery remains grounded in executed evidence; the gate
  decision is now self-consistent (`evaluate_gate.action` and `autonomous_resolution` agree
  for the silence case via the shared resolution path). Pinned by the `test_gate.py` backstop
  tests (delivers-without-oracle below the cap and at it; still parks on failing/absent
  validation, on findings, and on a real objection).
- Cost/risk: a slightly higher ship-wrong risk on tasks with thin self-tests (bounded above);
  it relaxes the gate's trust posture → recorded in TM-0001.
- Follow-up: make the delivery bar a per-tier setting when profiles land (solo trusts
  deterministic validation; hardened re-requires the independent oracle).
