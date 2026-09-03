"""Autonomous correctness gate (ADR-0020): an autonomous run gets the tester + reason-on-stall
overlay so it verifies (an independent, executed oracle) and can't silently ship wrong code —
autonomous-only, opt-out via ``autonomous_verified``. Tests the pure overlay + the config knob."""

from __future__ import annotations

from pathlib import Path

import pytest
from mosaera_api.factory import _verify_overlay
from mosaera_api.schemas import RunSubmit
from mosaera_core.config import Settings


def _req(*, autonomous: bool) -> RunSubmit:
    return RunSubmit(repo="r", task="t", autonomous=autonomous)


# The autonomous oracle posture (#52, ADR-0057; leaned #56, ADR-0060): tester + reason-on-stall
# (ADR-0020) PLUS the deterministic supports — change-coverage + the mutation check. (The gap-fill
# token-saver and the reactive test-review were removed entirely in #56.)
_POSTURE_KNOBS = (
    "tester_enabled",
    "reason_on_stall_enabled",
    "oracle_coverage",
    "oracle_mutation_check",
    "tester_repairs_tests",  # #54
    "proctor_faithfulness_guard",  # #57
)


def _all_off(*, autonomous_verified: bool = True) -> Settings:
    return Settings(
        autonomous_verified=autonomous_verified,
        tester_enabled=False,
        reason_on_stall_enabled=False,
        oracle_coverage=False,
        oracle_mutation_check=False,
    )


def test_overlay_enables_full_oracle_posture_for_autonomous() -> None:
    # autonomous + verified ON → the FULL oracle (all five knobs), not just tester+reason.
    base = _all_off()  # autonomous_verified defaults True
    out = _verify_overlay(base, _req(autonomous=True))
    assert all(getattr(out, k) is True for k in _POSTURE_KNOBS)
    assert base.tester_enabled is False  # the input is not mutated


def test_overlay_noop_when_knob_off() -> None:
    base = _all_off(autonomous_verified=False)
    out = _verify_overlay(base, _req(autonomous=True))
    assert all(getattr(out, k) is False for k in _POSTURE_KNOBS)


def test_overlay_noop_for_non_autonomous_run() -> None:
    # A guided / ad-hoc run (autonomous=False) is untouched even with the knob ON.
    base = _all_off()
    out = _verify_overlay(base, _req(autonomous=False))
    assert all(getattr(out, k) is False for k in _POSTURE_KNOBS)


def test_autonomous_verified_defaults_on_and_allow_listed(tmp_path: Path) -> None:
    from mosaera_core.settings_store import _ALLOWED_KEYS

    assert Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)}).autonomous_verified is True
    assert "autonomous_verified" in _ALLOWED_KEYS
    off = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path), "MOSAERA_AUTONOMOUS_VERIFIED": "0"})
    assert off.autonomous_verified is False


@pytest.mark.parametrize("autonomous", [True, False])
def test_overlay_preserves_other_settings(autonomous: bool) -> None:
    # The overlay only touches the two verify/recover flags — nothing else.
    base = Settings(autonomous_verified=True, max_iterations=7, default_cost_mode="premium")
    out = _verify_overlay(base, _req(autonomous=autonomous))
    assert out.max_iterations == 7 and out.default_cost_mode == "premium"
