"""The structural-claim eligibility widening (ADR-0094) — what it admits, and what it must not.

MEASURED 2026-08-09 over 193 runs: 74 honest parks, 13 eligible. **Every one of those 13 was on
work the hidden grader PASSED.** The WRONG column was empty, so Layer 2's 12 refusals could not be
scored as correct — there was nothing wrong to catch, and its discrimination is UNDEFINED, not good.

17 parks were turned away on `claim_structural_failed` ALONE: 10 grader-right, 7 grader-wrong. It
is the only MIXED bucket, and therefore the only one that can put a known-wrong delivery in front
of the gate. Every other bucket is degenerate — reviewer objections were 8-for-8 on wrong work,
validation-failed cannot ship on principle, and `security_unverified` is never the sole blocker, so
relaxing it would unlock zero runs while giving up Sentinel's veto.

These tests pin the narrowness. The widening is worth nothing if it leaks.
"""

from __future__ import annotations

from typing import Any

from mosaera_core.eligibility import (
    convertible_decline_reason,
    convertible_park_class,
    is_oracle_unverified_park,
)


def _park(*reasons: str, **over: Any) -> dict[str, Any]:
    final: dict[str, Any] = {
        "gate_decision": {"reasons": list(reasons)},
        "tests_passed": True,
        "tests_modified": False,
    }
    final.update(over)
    return final


def test_default_off_the_structural_park_stays_refused() -> None:
    """The 17-park bucket, at the shipped default. Nothing changes unless someone opts in."""
    final = _park("claim_structural_failed")
    assert is_oracle_unverified_park(final) is False
    assert convertible_park_class(final) is None


def test_knob_on_admits_the_structural_only_park() -> None:
    """The measured bucket, admitted. This is the whole point of the knob."""
    final = _park("claim_structural_failed")
    assert is_oracle_unverified_park(final, admit_structural_claim=True) is True
    assert convertible_park_class(final, admit_structural_claim=True) == "oracle_unverified"


def test_knob_on_still_admits_the_original_class() -> None:
    for reasons in (("oracle_unverified",), ("oracle_unverified", "claim_structural_failed")):
        assert convertible_park_class(_park(*reasons), admit_structural_claim=True) is not None


def test_the_knob_admits_NOTHING_else() -> None:
    """The blast radius, pinned reason by reason.

    Each of these was measured as a real control doing real work: reviewer objections were 8-for-8
    on wrong deliveries, `security_unverified` is Sentinel's veto, a critic veto is a held-out model
    finding a genuine defect, and a tamper must never be laundered into a ship. The knob must widen
    exactly ONE reason — if any of these rides in alongside it, the widening has become a hole.
    """
    for extra in (
        "security_unverified",
        "reviewer_requested_changes",
        "reviewer_conflict",
        "critic_vetoed",
        "validation_failed",
        "validation_unavailable",
        "validation_not_attempted",
        "tests_tampered",
        "claim_behavioral_failed",
        "claim_integrity_failed",
    ):
        final = _park("claim_structural_failed", extra)
        assert convertible_park_class(final, admit_structural_claim=True) is None, (
            f"the widening admitted a park also blocked by {extra!r} — it must widen exactly one "
            "reason, and every one of these was measured as a control doing real work"
        )


def test_an_empty_reason_set_is_never_admitted() -> None:
    """The subset test replaced an equality test; `set() <= anything` is True, so without an
    explicit non-empty check a park with NO blocking reason would have become convertible."""
    assert convertible_park_class(_park(), admit_structural_claim=True) is None
    assert convertible_park_class(_park("iteration_limit"), admit_structural_claim=True) is None


def test_every_other_class1_condition_still_applies() -> None:
    """The widening touches the REASON SET only. Green, tamper, veto and the honest-stop channels
    are untouched — a structural-claim park that trips any of them stays parked."""
    for over in (
        {"tests_passed": False},
        {"tests_passed": None},
        {"tests_modified": True},
        {"outcome_verdict": {"vetoed": True}},
        {"stalled": True},
        {"give_up_reason": "x"},
        {"plan_unworkable_reason": "x"},
        {"blocked_reason": "x"},
        {"escalate_reason": "x"},
    ):
        final = _park("claim_structural_failed", **over)
        assert convertible_park_class(final, admit_structural_claim=True) is None, (
            f"the widening bypassed a class-1 condition: {over}"
        )


def test_decline_reason_stays_in_lockstep_with_the_class() -> None:
    """`convertible_decline_reason` calls the class predicate; if the flag is not threaded to BOTH,
    an admitted park reports a class AND a reason for not being one. That pair is pinned in
    `test_disposition.py`, and the bench writes both onto the same card."""
    final = _park("claim_structural_failed")
    assert convertible_decline_reason(final) != ""
    assert convertible_decline_reason(final, admit_structural_claim=True) == ""


def test_the_reason_class_table_was_not_edited() -> None:
    """`claim_structural_failed` stays an `objection` in REASON_CLASS (ADR-0092).

    Reclassifying it would have been the one-line version of this change — and would have widened
    EVERY consumer of that table at once, including class 2's derived admission policy, silently.
    A narrow named exception in one predicate is what makes this measurable and reversible.
    """
    from mosaera_policies.gate import reason_class

    assert reason_class("claim_structural_failed") == "objection"


def test_the_widening_cannot_reach_the_ship_decision() -> None:
    """Eligibility decides who is ATTEMPTED; only `close_oracle_gap` decides who SHIPS.

    Pinned structurally: the ship test is a positive comparison against "verified", so a park
    admitted here still has to pass green + comprehensive mutation. If this ever fails, eligibility
    has stopped being an attempt filter and become a ship authority.
    """
    import ast
    import inspect

    from mosaera_core import eligibility

    tree = ast.parse(inspect.getsource(eligibility))
    # String CONSTANTS, not a substring scan: "verified" is a substring of `oracle_unverified` and
    # `security_unverified`, so a naive `in src` check passes vacuously and proves nothing.
    literals = {
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert "verified" not in literals, (
        "eligibility.py names the ship verdict — it must not participate in the ship decision"
    )
    called = {
        n.func.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "close_oracle_gap" not in called


def test_the_knob_is_bench_only_and_that_is_deliberate() -> None:
    """RED TEAM R2. The production rung (`_escalation.py`) does NOT thread the flag, so setting the
    env var changes nothing in a live run. That is the containment, not an oversight — the widening
    earns production only after the bench measures it.

    But a knob nothing reads is this repo's most-repeated defect (a declared-but-unread field, F74).
    So the no-op is PINNED here rather than left to be discovered: threading it into production
    means deleting this test, which is a deliberate, reviewed act instead of a silent widening.
    """
    import inspect

    from mosaera_api.app_context import _escalation

    src = inspect.getsource(_escalation)
    assert "admit_structural_claim" not in src, (
        "the production escalation rung now threads the eligibility widening — that moves a "
        "bench-only measurement knob onto the live ship path. If that is intended, it needs an "
        "ADR amendment and its own red-team pass, not just this test deleted."
    )


def test_the_knob_is_env_only_with_no_dashboard_lever() -> None:
    """It must NOT be a UI toggle. Production never reads the flag, so a dashboard switch would be
    a lever wired to nothing — this repo's most-repeated defect (a declared control with no
    consumer, F74). Env-only keeps the widening an explicit operator act on the bench.
    """
    from mosaera_core.config import GENERAL_KNOBS, Settings

    assert not any(k.field == "layer2_admit_structural_claim" for k in GENERAL_KNOBS)
    assert Settings.from_env(env={}).layer2_admit_structural_claim is False
    on = {"MOSAERA_LAYER2_ADMIT_STRUCTURAL_CLAIM": "1"}
    assert Settings.from_env(env=on).layer2_admit_structural_claim is True
