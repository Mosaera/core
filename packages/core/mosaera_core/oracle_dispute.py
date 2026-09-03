"""The gate's human-facing explanations: the priced residual, and the two-bars dispute.

Both are computed AFTER the verdict, change nothing about it, and exist so the human's
approval accepts a NAMED thing rather than a mystery. They live together because they are the
same kind of object -- a sentence the gate owes the operator -- and apart from `nodes_review`
because that file is at its size ceiling and neither needs the graph.

## Two bars disagree

**The measurement.** On the 0.6.3 sweep (150 runs,
`docs/engineering-history/over-park-anatomy-2026-08-30.md`) 26 over-parks were an authored assertion
refusing a tree the hidden grader passed 100%. In **24 of 26** the repository's OWN standing suite
vouched for that same tree. The engine held a second, human-written opinion that was right almost
every time and never consulted it, because `evaluate_oracle`'s OR short-circuits at
`tester_vouched`.

On the design's exact trigger — authored bar refused AND standing suite vouched — the tree was
genuinely correct in **31 of 34** runs (91%). The 3 misses are why this only ever *asks*.

**Why this is not a widening (ADR-0062).** The engine may not mechanically widen the acceptance
class. Nothing here advances, delivers, relaxes an assertion or alters a verdict: the gate decision
is already made before this is computed, and this module returns a *sentence*. A control may refuse
to act, never to speak (ADR-0107). The failure mode of a wrong question is a wasted review; the
failure mode of a wrong pass is a false ship, and this cannot produce one.

**Why it is needed at all.** The existing ask (`is_oracle_conflict_escalation`) needs the CODER to
raise its hand, and fired on **0 of those 26 runs** — 19 never tripped the progress breaker, so
never reached any ask path. They failed validation, looped, hit the gate, and parked as
`validation_failed`: a reason that asserts the IMPLEMENTATION was at fault, which on these runs is
false. That is an Honest Parking defect, and the operator acts on the reason.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

# The gate reasons that mean "a bar refused this tree", as opposed to a reviewer opinion, a security
# gap, or a tamper. `tests_tampered` is deliberately absent: when the coder edited a test the park
# stands on its own terms and re-reading it as "the bar was wrong" is exactly the excuse the tamper
# guard exists to refuse.
_BAR_REFUSED = frozenset({"validation_failed", "claim_behavioral_failed"})

_NOT_EVALUATED = "not_evaluated"


def dispute_note(
    *,
    gate_reasons: Sequence[str],
    oracle_legs: dict[str, Any],
    tests_modified: bool,
    failing_tests: Sequence[str],
    standing_suite: Callable[[], bool],
) -> str:
    """The operator-facing question, or ``""`` when the two bars do not disagree.

    ``standing_suite`` is a callable because it walks the workspace: it is invoked ONLY when a bar
    has already refused and the short-circuiting OR never asked, so a delivering run pays nothing.
    Any fault yields ``""`` — a diagnostic may never break a run, and silence is the safe direction
    for a channel that only speaks.
    """
    reasons = set(gate_reasons or ())
    if tests_modified or not (reasons & _BAR_REFUSED):
        return ""

    vouched = oracle_legs.get("standing_suite") if oracle_legs else None
    if vouched is None or vouched == _NOT_EVALUATED:
        try:
            vouched = bool(standing_suite())
        except Exception:
            return ""
    if vouched is not True:
        return ""

    named = ", ".join(list(failing_tests)[:3]) or "the authored suite"
    more = "" if len(failing_tests) <= 3 else f" (+{len(failing_tests) - 3} more)"
    return (
        "TWO BARS DISAGREE about this tree. The authored acceptance suite REFUSED it "
        f"({named}{more}), but the repository's own standing suite PASSES on it and covers the "
        "change. One of the two is wrong and the engine cannot tell which, so it is refusing and "
        "asking rather than guessing. Measured on 34 runs where this held, the tree was correct "
        "31 times (91%) — the authored assertion was the thing at fault. Read the assertion above "
        "before approving: if it pins something the task never required, the bar is the defect."
    )


def dispute_for_state(
    ctx: Any, state: Any, gate_reasons: Sequence[str], oracle_legs: dict, covered: Any
) -> str:
    """`dispute_note` bound to a run's state — the whole adapter, so the gate node keeps one line.

    Separate from `dispute_note` on purpose: the predicate is pure and unit-testable without a
    workspace, a graph, or a run, and this is the only part that needs any of them.

    `covered` is PASSED IN, not read from state: the coverage map is a local the gate derives
    from `changed_lines_covered` under the `oracle_coverage` knob, and re-reading an undeclared
    key here would be permanently empty (ADR-0026) -- the state-keys guard caught exactly that.
    """
    from mosaera_core.eligibility import effective_test_output
    from mosaera_core.oraclecheck import standing_suite_is_independent_oracle
    from mosaera_core.progress import parse_failing_tests
    from mosaera_core.quality import changed_files

    return dispute_note(
        gate_reasons=gate_reasons,
        oracle_legs=oracle_legs,
        tests_modified=bool(state.get("tests_modified")),
        failing_tests=parse_failing_tests(effective_test_output(state), cap=10),
        standing_suite=lambda: standing_suite_is_independent_oracle(
            ctx.workspace,
            state.get("integrity_baseline"),
            changed_files(state.get("diff", "")),
            covered,
        ),
    )


def residual_note(*, structural_vouched: bool, gate_reasons: Sequence[str], mutation: Any) -> str:
    """The PRICED RESIDUAL (ADR-0071 amendment, owner-ratified 2026-08-03).

    When a vouched refactor is still blocked, say EXACTLY what is proven and what is not: the
    human's approval accepts a named residual, never a mystery.
    """
    if not (structural_vouched and "oracle_unverified" in set(gate_reasons) and mutation is False):
        return ""
    return (
        "shape: proven (structural claim satisfied) · equivalence: passes on all "
        "sampled inputs · UNPROVEN: at least one mutation of the changed code "
        "survives the suite (an input region no test or generated input reaches) — "
        "approve to accept this residual on record, or add a covering test (#62 "
        "will target it automatically)"
    )
