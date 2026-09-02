"""apply_oracle_posture — the #52 autonomous oracle posture (ADR-0057), offline + pure."""

from __future__ import annotations

from mosaera_core.config import Settings, apply_oracle_posture
from mosaera_core.config._posture import POSTURE_FORCED_KNOBS

# The knobs the posture activates for a verified autonomous run. The gap-fill token-saver and the
# reactive test-review were removed entirely (#56, ADR-0060) — the posture set is exactly these.
_KNOBS = (
    "tester_enabled",
    "reason_on_stall_enabled",
    "oracle_coverage",
    "oracle_mutation_check",
    "tester_repairs_tests",  # #54
    "proctor_faithfulness_guard",  # #57
    "critic_enabled",  # #60
    # #61 claims-protocol critic: activated 2026-08-03 (owner decision, measured: over-vetoes
    # 8->1 p=0.033, catches preserved). Removing it from the posture is the documented
    # rollback — this line is the tripwire that keeps that an explicit act.
    "critic_claim_protocol",  # #61
    # behavior_preservation_guard (ADR-0066) is deliberately NOT here: its posture activation was
    # HELD after the MCB-05 smoke showed a false_ship on the ON arm (the weak model authored too
    # loose a suite). The guidance stays behind its default-OFF knob; the posture must NOT flip it.
    "refactor_oracle_scaffold",  # #60 / ADR-0066 follow-up — the deterministic (safe) successor
    # oracle_structural_spec (ADR-0072) is deliberately NOT here: activated 2026-08-02 on an n=3
    # result, WITHDRAWN the same day when a frozen n=25/arm A/B showed no effect (pooled Fisher
    # p=1.0; 0 false-parks/100 runs — safe but ineffective). The knob stays default-OFF and the
    # posture must NOT flip it; re-test once acceptance claims are first-class. Full record:
    # docs/engineering-history/structural-oracle-ab-2026-08-02.md.
)


def _off(*, autonomous_verified: bool = True) -> Settings:
    return Settings(
        autonomous_verified=autonomous_verified,
        tester_enabled=False,
        reason_on_stall_enabled=False,
        oracle_coverage=False,
        oracle_mutation_check=False,
    )


def test_verified_autonomous_enables_the_full_oracle() -> None:
    # autonomous_verified defaults True → the Proctor + the deterministic supports come on.
    out = apply_oracle_posture(_off())
    assert all(getattr(out, k) is True for k in _KNOBS)


def test_posture_flips_exactly_the_declared_knob_set() -> None:
    # #56 (ADR-0060): the posture set is EXACTLY _KNOBS — a knob added to the posture without this
    # test noticing would silently widen the autonomous surface. Diff the dataclass field-by-field.
    base = _off()
    out = apply_oracle_posture(base)
    changed = {f for f in type(base).__dataclass_fields__ if getattr(base, f) != getattr(out, f)}
    assert changed == set(_KNOBS)


def test_published_constant_matches_what_the_overlay_actually_forces() -> None:
    # POSTURE_FORCED_KNOBS is what the SETTINGS UI reads to tell an operator "this toggle is
    # overridden for autonomous runs". If it drifts from `replace(...)`, the UI starts lying in a
    # new way — a hand-maintained list beside the real writer is exactly the shape that produced
    # the `merged` dead constant. This ties them together.
    base = _off()
    changed = {
        f
        for f in type(base).__dataclass_fields__
        if getattr(base, f) != getattr(apply_oracle_posture(base), f)
    }
    assert set(POSTURE_FORCED_KNOBS) == changed


def test_opt_out_returns_the_same_object() -> None:
    # autonomous_verified=False is the deterministic opt-out — a provable no-op (the same object).
    base = _off(autonomous_verified=False)
    assert apply_oracle_posture(base) is base
    assert all(getattr(apply_oracle_posture(base), k) is False for k in _KNOBS)


def test_idempotent() -> None:
    once = apply_oracle_posture(Settings())
    twice = apply_oracle_posture(once)
    assert all(getattr(twice, k) == getattr(once, k) for k in _KNOBS)


def test_preserves_unrelated_settings() -> None:
    # The posture only flips the declared _KNOBS set — nothing else.
    base = Settings(max_iterations=7, default_cost_mode="premium", stall_limit=5)
    out = apply_oracle_posture(base)
    assert out.max_iterations == 7 and out.default_cost_mode == "premium" and out.stall_limit == 5


def test_input_is_not_mutated() -> None:
    base = _off()
    apply_oracle_posture(base)
    assert all(getattr(base, k) is False for k in _KNOBS)  # replace() returns a new object
