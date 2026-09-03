"""Deterministic model escalation (ADR-0016): the diagnosis attributes a failed run's
bottleneck to one role, and escalate_role bumps only that role up its ladder. Both are
pure over the terminal state / settings — no model calls, fully offline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mosaera_core.bench.escalation import diagnose_bottleneck, escalate_role
from mosaera_core.config import RoleModel, Settings, _parse_role_escalation

_LADDER = {
    "tester": [
        RoleModel(provider="ollama", model="gpt-oss:20b"),
        RoleModel(provider="anthropic", model="claude-sonnet-4-6"),
    ],
    "coder": [
        RoleModel(provider="ollama", model="qwen3-coder:30b"),
        RoleModel(provider="anthropic", model="claude-sonnet-4-6"),
    ],
}


def _state(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"gate_decision": {"reasons": []}, "review": "", "approved": False}
    base.update(over)
    return base


# --- diagnose_bottleneck ---------------------------------------------------


def test_tester_over_specification_is_diagnosed_as_the_tester() -> None:
    # The MCB signal: validation fails but the reviewer APPROVES → the tester's own
    # (over-strict) suite is what blocks a correct change.
    s = Settings(tester_enabled=True)
    state = _state(
        gate_decision={"reasons": ["validation_failed"]},
        review="VERDICT: APPROVE — looks correct",
    )
    assert diagnose_bottleneck(state, s) == "tester"


def test_false_positive_ship_is_the_tester_when_enabled() -> None:
    # Benchmark ground truth: the run DELIVERED (clean state) but the hidden grader shows
    # it fails acceptance → a too-lenient tester let wrong code through.
    s = Settings(tester_enabled=True)
    assert diagnose_bottleneck(_state(approved=True), s, acceptance_failed=True) == "tester"


def test_false_positive_ship_is_the_coder_without_a_tester() -> None:
    s = Settings(tester_enabled=False)
    assert diagnose_bottleneck(_state(approved=True), s, acceptance_failed=True) == "coder"


def test_explicit_over_specification_handraise_is_the_tester() -> None:
    s = Settings(tester_enabled=True)
    state = _state(escalate_reason="test_x over-specifies beyond the contract: wants exit 2")
    assert diagnose_bottleneck(state, s) == "tester"


def test_tamper_is_diagnosed_as_the_coder() -> None:
    # The coder edited the tester's protected acceptance tests (out of depth → cheating the
    # contract). The strongest "escalate the coder" signal (ADR-0026).
    s = Settings(tester_enabled=True)
    state = _state(tests_modified=True, stalled=True)
    assert diagnose_bottleneck(state, s) == "coder"


def test_tamper_outranks_the_tester_over_specification_rule() -> None:
    # An approved-tamper (reviewer APPROVE + validation_failed + tamper) must attribute to
    # the CODER, not be misread as a weak/over-strict tester by the rule below it.
    s = Settings(tester_enabled=True)
    state = _state(
        tests_modified=True,
        gate_decision={"reasons": ["validation_failed"]},
        review="VERDICT: APPROVE — looks correct",
    )
    assert diagnose_bottleneck(state, s) == "coder"


def test_validation_fail_without_reviewer_approve_is_the_coder() -> None:
    s = Settings(tester_enabled=True)
    state = _state(
        gate_decision={"reasons": ["validation_failed"]},
        review="VERDICT: REQUEST CHANGES — the search is case-sensitive",
    )
    assert diagnose_bottleneck(state, s) == "coder"


def test_validation_fail_with_approve_but_tester_off_is_the_coder() -> None:
    # No tester in the loop → an approving reviewer + failing validation is the coder's
    # own test/impl mismatch, not a tester over-specification.
    s = Settings(tester_enabled=False)
    state = _state(gate_decision={"reasons": ["validation_failed"]}, review="VERDICT: APPROVE")
    assert diagnose_bottleneck(state, s) == "coder"


def test_degraded_plan_is_the_pm() -> None:
    s = Settings()
    state = _state(escalate_reason="planner produced no grounded plan (budget exhausted or empty)")
    assert diagnose_bottleneck(state, s) == "pm"


def test_stuck_blocking_reviewer_is_the_reviewer() -> None:
    s = Settings()
    state = _state(
        gate_decision={"reasons": ["reviewer_blocked"]},
        review="VERDICT: BLOCK — I will not approve",
        stall_by_kind={"review": ["fp", 3]},
    )
    assert diagnose_bottleneck(state, s) == "reviewer"


def test_reviewer_requested_changes_without_stall_is_the_coder() -> None:
    s = Settings()
    state = _state(
        gate_decision={"reasons": ["reviewer_requested_changes"]},
        review="VERDICT: REQUEST CHANGES",
    )
    assert diagnose_bottleneck(state, s) == "coder"


def test_security_findings_are_the_coder() -> None:
    s = Settings()
    state = _state(gate_decision={"reasons": ["security_findings"]})
    assert diagnose_bottleneck(state, s) == "coder"


def test_clean_run_has_no_bottleneck() -> None:
    # A delivered/all-clear run has nothing to escalate.
    assert diagnose_bottleneck(_state(approved=True), Settings()) is None


# --- escalate_role ---------------------------------------------------------


def test_escalate_bumps_the_role_one_tier() -> None:
    s = Settings(role_escalation=_LADDER, tester_model="gpt-oss:20b")
    esc = escalate_role(s, "tester")
    assert esc is not None
    assert esc.role == "tester"
    assert esc.settings.tester_model == "claude-sonnet-4-6"
    assert esc.settings.role_providers["tester"] == "anthropic"
    assert "gpt-oss:20b -> anthropic/claude-sonnet-4-6" in esc.label
    # The escalation is scoped: the coder's binding is untouched.
    assert "coder" not in esc.settings.role_providers


def test_escalate_returns_none_at_the_top_tier() -> None:
    s = Settings(
        role_escalation=_LADDER,
        tester_model="claude-sonnet-4-6",
        role_providers={"tester": "anthropic"},
    )
    assert escalate_role(s, "tester") is None


def test_escalate_returns_none_without_a_ladder() -> None:
    assert escalate_role(Settings(), "tester") is None


def test_escalate_moves_an_off_ladder_binding_onto_tier_zero() -> None:
    # A role whose current binding isn't on the ladder escalates onto tier 0.
    s = Settings(role_escalation=_LADDER, tester_model="some-other-model")
    esc = escalate_role(s, "tester")
    assert esc is not None
    assert esc.settings.tester_model == "gpt-oss:20b"


# --- config wiring ---------------------------------------------------------


def test_parse_role_escalation_typed_and_drops_junk() -> None:
    parsed = _parse_role_escalation(
        {
            "tester": [{"provider": "ollama", "model": "gpt-oss:20b"}, {"bad": "entry"}],
            "nope": [{"provider": "x", "model": "y"}],  # unknown role dropped
            "coder": [],  # empty ladder dropped
        }
    )
    assert parsed == {"tester": [RoleModel(provider="ollama", model="gpt-oss:20b")]}
    assert "nope" not in parsed and "coder" not in parsed


def test_role_escalation_from_env_json(tmp_path: Path) -> None:
    env = {
        "MOSAERA_HOME": str(tmp_path),  # isolate from any real .mosaera/settings.json
        "MOSAERA_ROLE_ESCALATION": (
            '{"tester": [{"provider": "ollama", "model": "gpt-oss:20b"},'
            ' {"provider": "anthropic", "model": "claude-sonnet-4-6"}]}'
        ),
        "MOSAERA_MODEL_ESCALATION": "1",
        "MOSAERA_MAX_MODEL_ESCALATIONS": "3",
    }
    s = Settings.from_env(env)
    assert s.model_escalation_enabled is True
    assert s.max_model_escalations == 3
    assert len(s.role_escalation["tester"]) == 2
    assert s.role_escalation["tester"][1].provider == "anthropic"
