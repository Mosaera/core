"""apply_reliability_sensitivity — the #51 self-stop budget dial (ADR-0056), offline + pure."""

from __future__ import annotations

from mosaera_core.config import Settings
from mosaera_core.graph.build import apply_reliability_sensitivity, recursion_limit_for


def _budgets(s: Settings) -> tuple[int, int, int, int, int]:
    return (
        s.max_iterations,
        s.max_escalations,
        s.stall_limit,
        s.tester_step_limit,
        s.plan_stall_limit,
    )


def test_balanced_is_identity() -> None:
    # The default level returns the SAME object — provably zero regression, all user knobs intact.
    s = Settings()
    assert apply_reliability_sensitivity(s) is s
    assert _budgets(
        apply_reliability_sensitivity(Settings(reliability_sensitivity="balanced"))
    ) == (
        3,
        1,
        3,
        15,
        2,
    )


def test_cautious_tightens_every_budget() -> None:
    # A weak model self-stops early: fewer iterations/escalations, tighter stall + Proctor + plan.
    assert _budgets(
        apply_reliability_sensitivity(Settings(reliability_sensitivity="cautious"))
    ) == (
        2,
        0,
        2,
        8,
        1,
    )


def test_persistent_grants_more_rope_within_the_ceiling() -> None:
    # A strong model gets more rope (more delivery attempts) — but never above the hard ceiling.
    assert _budgets(
        apply_reliability_sensitivity(Settings(reliability_sensitivity="persistent"))
    ) == (6, 2, 4, 20, 3)
    p = apply_reliability_sensitivity(
        Settings(reliability_sensitivity="persistent", max_iterations_ceiling=4)
    )
    assert p.max_iterations == 4  # min(ceiling, …) clamp holds (ADR-0046 composability)


def test_every_level_is_idempotent() -> None:
    # Applied in both build_graph and recursion_limit_for → double application must be a no-op.
    for level in ("cautious", "balanced", "persistent"):
        once = apply_reliability_sensitivity(Settings(reliability_sensitivity=level))
        assert _budgets(apply_reliability_sensitivity(once)) == _budgets(once)


def test_unknown_level_fails_safe_to_balanced() -> None:
    # An env-set out-of-choices value must fall back to today's budgets, never crash.
    assert _budgets(apply_reliability_sensitivity(Settings(reliability_sensitivity="bogus"))) == (
        3,
        1,
        3,
        15,
        2,
    )


def test_derives_from_user_config_at_the_bound() -> None:
    # min/max means a user's own (more tolerant / more conservative) config still shows through.
    assert (
        apply_reliability_sensitivity(
            Settings(reliability_sensitivity="persistent", stall_limit=7)
        ).stall_limit
        == 7
    )
    assert (
        apply_reliability_sensitivity(
            Settings(reliability_sensitivity="cautious", max_iterations=1)
        ).max_iterations
        == 1
    )


def test_recursion_limit_scales_with_persistent() -> None:
    # persistent raises max_escalations, so the recursion budget must grow with it — else the run
    # crashes with GraphRecursionError instead of parking (the seam applies in recursion_limit_for).
    assert recursion_limit_for(
        Settings(reliability_sensitivity="persistent")
    ) > recursion_limit_for(Settings())
