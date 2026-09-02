"""A control must be able to reach BOTH of its outcomes on a REALISTIC state (ADR-0107).

Coverage says a guard was executed. It does not say the guard was ever executed with its condition
FALSE — and a guard that only ever evaluates one way is not a control, it is a constant. Martin &
Xie's policy-coverage work states the rule directly: condition hit percentage uses a `2 x total`
denominator, and their Change-Rule-Effect mutation operator *"should never create equivalent
mutants unless a rule is unreachable, a strong indication of an error in the policy specification."*

Every one of #68's four defects was this shape, and none was visible to a passing suite:

    ask_withheld_reason(give_up_state) == "a gate objection"      # for EVERY such state

The unit tests were green because they fed it hand-built states. The state the LIVE path actually
produces was never constructed in a test, so the one polarity that mattered — the arm staying quiet
and letting the ask through — was unreachable and nobody could tell.

Hence the load-bearing choice below: witnesses are built by running the REAL gate over the inputs
the REAL bypass edge produces. A hand-written `{"reasons": []}` would pass this file forever while
the live path stayed dead — that is the mistake, not a shortcut around it.
"""

from __future__ import annotations

from typing import Any

from mosaera_core.escalate_arm import ask_withheld_reason, is_oracle_conflict_escalation
from mosaera_policies import evaluate_gate

_FAILING = "FAILED tests/test_add.py::test_row - AssertionError\n1 failed, 2 passed\n"


def _gate_reasons(**over: Any) -> list[str]:
    """The gate's verdict, computed rather than asserted."""
    kw: dict[str, Any] = {
        "tests_passed": False,
        "reviewer_verdict": "UNKNOWN",
        "findings_count": 0,
        "security_status": "unavailable",
        "scan_attempted": False,
        "oracle_verified": False,
        "validation_strength": "suite",
        "iteration": 1,
        "max_iterations": 6,
    }
    kw.update(over)
    return list(evaluate_gate(**kw).reasons)


def _give_up_park(**over: Any) -> dict[str, Any]:
    """What `route_after_supervise -> gate` ACTUALLY produces.

    `graph/build.py` sends a give-up straight to the gate, so `scan_node` and `review_node` never
    ran: security is unavailable-and-never-attempted, the reviewer is silent. This is the exact
    state that made the ask unreachable, reconstructed from the gate itself.
    """
    state: dict[str, Any] = {
        "coder_escalated": True,
        "escalate_reason": "the task conflicts with a test",
        "integrity_baseline": {"tests/test_add.py": "h1"},
        "authored_tests": [],
        "test_output": _FAILING,
        # `test_node` DID run on this branch (route_after_test -> supervise), so the tamper
        # channels it owns are present and clean. Including them is not fixture decoration: their
        # ABSENCE is what the hand-raise test below asserts on, and omitting them here would have
        # made both branches look alike — which is how the tamper hole survived review.
        "tests_modified": False,
        "destroyed_paths": [],
        "gate_decision": {"reasons": _gate_reasons()},
    }
    state.update(over)
    return state


def test_the_give_up_park_really_does_carry_a_not_run_security_reason() -> None:
    """The premise, asserted rather than assumed. If this ever stops holding, the tests below stop
    testing what they claim to and should be rewritten, not deleted."""
    assert "security_not_attempted" in _gate_reasons()
    assert "security_unverified" not in _gate_reasons()


def test_the_ask_can_stay_QUIET_on_the_state_the_live_path_produces() -> None:
    """The polarity that was unreachable — this is the whole file's reason to exist.

    Not "the arm sometimes returns ''", which was already true for hand-built inputs. This asserts
    it on the gate decision the give-up edge really builds."""
    assert ask_withheld_reason(_give_up_park()) == ""


def test_the_ask_can_still_SPEAK_up_on_a_real_objection() -> None:
    """The other polarity. A control that can never refuse is as broken as one that can never
    permit — this half is what keeps the fix from being 'delete the check'."""
    park = _give_up_park(gate_decision={"reasons": _gate_reasons(findings_count=3)})
    assert ask_withheld_reason(park) == "a gate objection"


def test_both_polarities_for_the_tamper_and_veto_exclusions() -> None:
    """Each remaining exclusion, exercised in both directions on the same realistic base."""
    assert ask_withheld_reason(_give_up_park(tests_modified=True)) == "a tamper verdict"
    assert ask_withheld_reason(_give_up_park(tests_modified=False)) == ""

    vetoed = _give_up_park(outcome_verdict={"vetoed": True})
    assert ask_withheld_reason(vetoed) == "a critic veto"
    assert ask_withheld_reason(_give_up_park(outcome_verdict={"vetoed": False})) == ""


def test_the_conflict_predicate_reaches_both_outcomes_on_realistic_states() -> None:
    """`is_oracle_conflict_escalation` gates the STOP. Same treatment: it must be able to say yes
    on the state the give-up edge builds, and no when a failing test is one the producer owns."""
    assert is_oracle_conflict_escalation(_give_up_park()) is True
    # A coder-owned failure — the code may simply be wrong, and this must never blame the tests.
    owned = _give_up_park(
        test_output="FAILED tests/test_mine.py::test_x - AssertionError\n1 failed\n"
    )
    assert is_oracle_conflict_escalation(owned) is False


def test_a_hand_raise_that_never_VALIDATED_cannot_get_an_ask() -> None:
    """Red-team R1, with an executed reproduction: `tests_modified` and `destroyed_paths` are
    written ONLY by `test_node`, and a coder hand-raise routes implement -> capture -> supervise,
    bypassing it. Both keys are absent, `.get()` is falsy, and the gate mints no tamper reason from
    missing state — so ADR-0107's class exclusion had nothing to exclude.

    A producer could weaken a baselined test, raise its hand, and have the arm carry 600 characters
    of its own words to the operator as "this item's acceptance cannot be met as written". Before
    the widening, `security_unverified` blocked that path; the widening opened it.

    Absent tamper state is UNKNOWN, never clean — the same rule the security half already got."""
    park = dict(_give_up_park())
    park.pop("tests_modified")
    park.pop("destroyed_paths")
    assert ask_withheld_reason(park) == "no tamper check ran on this branch"


def test_a_positive_tamper_verdict_still_wins_over_the_unknown_branch() -> None:
    """Ordering matters: a REAL tamper must report as tamper, not as "we didn't check"."""
    assert ask_withheld_reason(_give_up_park(tests_modified=True)) == "a tamper verdict"
    assert ask_withheld_reason(_give_up_park(destroyed_paths=["README.md"])) == "a tamper verdict"
