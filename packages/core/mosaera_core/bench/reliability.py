"""Reliability classification — which TERMINAL bucket a benchmark run landed in, and the
clean-conclusion rate that is the #43 run-reliability arc's scoreboard (ADR-0053).

A run reaches a CLEAN terminal state when it either delivers correct work OR parks honestly with
an accurate reason — *without looping or thrashing* toward the iteration/escalation caps (see
``docs/roadmap.md`` #43). This module maps one finished run + its hidden-grader verdict to ONE of
five buckets and computes the fraction that concluded cleanly. It is PURE over its inputs — it
reads only the terminal signals the run already produced (it adds NO new run-state) — mirroring
``bench/escalation.py::diagnose_bottleneck``, so it is unit-testable without driving the graph.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

# The five terminal buckets a finished run can land in.
CLEAN_DELIVER = "clean_deliver"  # approved AND the hidden grader passes (or none) — true success
HONEST_PARK = "honest_park"  # did not deliver, but stopped promptly on an accurate reason
THRASH_PARK = "thrash_park"  # did not deliver AND ground to the no-progress breaker / iteration cap
FALSE_SHIP = "false_ship"  # approved BUT the hidden grader FAILS — a dishonest "success"
CRASH = "crash"  # an exception escaped the run

OUTCOMES: tuple[str, ...] = (CLEAN_DELIVER, HONEST_PARK, THRASH_PARK, FALSE_SHIP, CRASH)

# The two buckets that satisfy the arc: "either stop when they should, or truly succeed."
CLEAN_OUTCOMES = frozenset({CLEAN_DELIVER, HONEST_PARK})

# Most-severe first. The representative bucket for a case run N times is the WORST that occurred
# (deny-by-default: surface a single false-ship among green runs, don't average it away).
_SEVERITY: tuple[str, ...] = (CRASH, FALSE_SHIP, THRASH_PARK, HONEST_PARK, CLEAN_DELIVER)


def classify_outcome(
    final: Mapping[str, Any],
    *,
    errored: bool,
    acceptance_failed: bool,
    max_iterations: int | None = None,
) -> str:
    """The terminal bucket for one finished run.

    - ``errored``           — an exception escaped ``run_case`` (``RunOutcome.error`` is set).
    - ``acceptance_failed`` — it delivered, but the hidden grader RAN and FAILED (the false-ship
      signal the bench already computes: ``approved and grader.ran and not grader.all_passed``).
    - ``max_iterations``    — the run's effective iteration cap. When given, a park at ``iteration
      >= max_iterations`` is thrash even though the gate's ``iteration_limit`` reason never reached
      ``final`` (see below). None keeps the pre-#51 behaviour.

    Priority is most-severe first, so a crash or a false-ship is never masked by the delivery flag.
    A delivery with no grader (``acceptance_failed`` False) counts as clean here — reliability asks
    *did it conclude honestly*; whether an ungraded delivery is CORRECT is the grader's own job.
    """
    if errored:
        return CRASH
    if final.get("approved"):
        # A delivery is clean only if the ground-truth grader doesn't contradict it.
        return FALSE_SHIP if acceptance_failed else CLEAN_DELIVER
    # Did not deliver → it parked. Clean iff it stopped PROMPTLY; a breaker trip (``stalled``) or a
    # ride to the iteration cap means it thrashed first. Measurement fix (#51, ADR-0056): the gate's
    # ``iteration_limit`` reason is appended only inside a gate visit that then PARKS (autonomous)
    # and is never resumed, so it never commits to ``final`` — a reviewer-revise loop that rode to
    # the cap would mis-bucket as honest_park. ``final["iteration"]`` IS committed (each super-step
    # bumps it), so read it directly against the effective cap. Keep the reasons check for any
    # resumed/guided drive that DID commit ``iteration_limit``.
    reasons = (final.get("gate_decision") or {}).get("reasons") or []
    rode_to_cap = (
        max_iterations is not None and int(final.get("iteration", 0) or 0) >= max_iterations
    )
    if final.get("stalled") or "iteration_limit" in reasons or rode_to_cap:
        return THRASH_PARK
    return HONEST_PARK


def _stalled_kind(final: Mapping[str, Any]) -> str:
    """Best-guess which loop tripped the fingerprint stall — the kind with the highest streak in
    ``stall_by_kind`` ({kind: [fp, streak]}). "unknown" when the map is absent/empty."""
    by_kind = final.get("stall_by_kind") or {}
    kind, best = "unknown", -1
    if isinstance(by_kind, Mapping):
        for k, v in by_kind.items():
            streak = int(v[1]) if isinstance(v, (list, tuple)) and len(v) > 1 else 0
            if streak > best:
                kind, best = str(k), streak
    return kind


def classify_park_cause(final: Mapping[str, Any], *, max_iterations: int | None = None) -> str:
    """A DIAGNOSTIC label for the terminal MECHANISM of a non-delivering run — *why* it parked.

    A measurement companion to ``classify_outcome`` (same purity; reads only terminal signals, adds
    no run-state), so a park's cause is visible instead of inferred. Every branch maps 1:1 to a
    ``classify_outcome`` verdict, so ``thrash_cause`` always explains the bucket:

    - ``give_up`` / ``plan_unworkable`` — the honest early stops (→ ``honest_park``).
    - ``stalled:<kind>`` — the fingerprint-stall breaker tripped on ``<kind>`` loop
      (test/review/hygiene/plan) (→ ``thrash_park``).
    - ``iteration_limit`` — a committed gate iteration_limit reason, resumed/guided (→ thrash).
    - ``rode_to_cap`` — ``iteration >= max_iterations`` with no honest stop (→ ``thrash``).
    - ``parked`` — fell through: an autonomous gate park below the cap (→ ``honest_park``).

    Returns ``""`` for a delivered/approved run (the cause question is about parks).
    """
    if final.get("approved"):
        return ""
    if final.get("give_up_reason"):
        return "give_up"
    if final.get("plan_unworkable_reason"):
        # Wave 3 (ADR-0080 §2): the intake park mints its reason through this seam with a
        # distinguishing prefix — a DIAGNOSTIC split only (both are honest_park; the frozen
        # classifier above is untouched).
        if str(final.get("plan_unworkable_reason", "")).startswith("under_specified"):
            return "under_specified"
        return "plan_unworkable"
    if final.get("stalled"):
        return f"stalled:{_stalled_kind(final)}"
    reasons = (final.get("gate_decision") or {}).get("reasons") or []
    if "iteration_limit" in reasons:
        return "iteration_limit"
    if max_iterations is not None and int(final.get("iteration", 0) or 0) >= max_iterations:
        return "rode_to_cap"
    return "parked"


def is_clean(outcome: str) -> bool:
    """Whether ``outcome`` counts toward the arc's clean-conclusion target."""
    return outcome in CLEAN_OUTCOMES


def tally(outcomes: Iterable[str]) -> dict[str, int]:
    """Per-bucket counts, with EVERY known bucket present (0 where unseen) for a stable shape."""
    counts = Counter(o for o in outcomes if o in OUTCOMES)
    return {b: counts.get(b, 0) for b in OUTCOMES}


def merge_counts(dicts: Iterable[Mapping[str, int]]) -> dict[str, int]:
    """Sum several ``{bucket: count}`` maps into one (known buckets only)."""
    total = {b: 0 for b in OUTCOMES}
    for d in dicts:
        for bucket, n in d.items():
            if bucket in total:
                total[bucket] += int(n)
    return total


def worst_outcome(outcomes: Iterable[str]) -> str | None:
    """The most-severe bucket among ``outcomes`` (the representative for N repeats), or None."""
    seen = {o for o in outcomes if o in OUTCOMES}
    return next((b for b in _SEVERITY if b in seen), None)


def clean_conclusion_rate(counts: Mapping[str, int]) -> float:
    """Fraction of runs that concluded cleanly (true-deliver or honest-park), 0..1. 0.0 when no
    runs. The #43 arc target is ~0.99 — the scoreboard headline."""
    total = sum(int(n) for n in counts.values())
    if total == 0:
        return 0.0
    clean = sum(int(counts.get(b, 0)) for b in CLEAN_OUTCOMES)
    return clean / total
