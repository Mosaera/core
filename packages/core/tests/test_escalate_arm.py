"""The ESCALATE arm predicate (`#64` F49).

The mirror of `test_disposition`'s close-the-gap cases: that arm needs the failures to be the
engine's own NEW files so they can be retracted and the run shipped; this one needs them to be files
the producer may NOT edit, so re-planning cannot help — and its outcome is to STOP and ask, never to
ship. The deny-by-default half is over-tested on purpose: this must never become a way to blame the
tests for a real defect.
"""

from __future__ import annotations

import mosaera_core.disposition as disp
import mosaera_core.escalate_arm as arm

# --- the ESCALATE arm (#64 F49) ----------------------------------------------------------------
#
# The mirror of the close-the-gap arm: that one needs the failures to be the engine's own NEW files
# so they can be retracted and the run shipped; this one needs them to be files the producer may NOT
# edit, so re-planning cannot possibly help — and its outcome is to STOP and ask, never to ship.
#
# Measured on `#64`: the producer diagnosed the broken bar correctly in 6 of 6 runs and was
# re-scoped back at the same wall every time. The predicate is what lets the engine tell that case
# from a genuine code defect, so the deny-by-default side is the half worth over-testing.

_BASELINED_FAIL = (
    "FAILED tests/test_add.py::TestAdd::test_add_writes_a_row - AssertionError\n"
    "1 failed, 2 passed\n"
)


def _escalation_final(**over: object) -> dict[str, object]:
    """A run where the producer raised its hand and the only failure is a PRE-EXISTING test."""
    final: dict[str, object] = {
        "coder_escalated": True,
        "escalate_reason": "the task conflicts with a test: it pins a date never supplied",
        "integrity_baseline": {"tests/test_add.py": "h1"},
        "proctor_edits": {},
        "authored_tests": [],
        "test_output": _BASELINED_FAIL,
        "gate_decision": {"reasons": ["validation_failed", "iteration_limit"]},
    }
    final.update(over)
    return final


def test_an_unfixable_hand_raise_qualifies() -> None:
    final = _escalation_final()
    assert arm.is_oracle_conflict_escalation(final) is True
    assert arm.blocking_protected_tests(final) == ("tests/test_add.py",)


def test_a_protectors_authored_test_also_qualifies() -> None:
    # The Proctor's own authored suite is protected from the coder too, so a failure there is
    # equally unfixable by the producer.
    final = _escalation_final(integrity_baseline={}, authored_tests=["tests/test_add.py"])
    assert arm.is_oracle_conflict_escalation(final) is True


def test_a_concluded_escalation_still_qualifies() -> None:
    # supervise_node clears the hand-raise channels when it concludes, recording WHY in
    # give_up_reason with an engine-controlled prefix. Without this the arm would only ever see
    # a live hand-raise and miss every run that already stopped.
    final = _escalation_final(
        coder_escalated=False,
        escalate_reason="",
        give_up_reason="escalation unresolved: the task conflicts with a test",
    )
    assert arm.is_oracle_conflict_escalation(final) is True


# --- deny-by-default: the half that must not become "blame the tests" -------------------------


def test_one_coder_owned_failure_disqualifies_the_whole_run() -> None:
    # The code may genuinely be wrong. A single failure the producer COULD have fixed means the
    # park stands on its own terms.
    final = _escalation_final(
        test_output=_BASELINED_FAIL + "FAILED tests/test_mine.py::test_x - AssertionError\n"
    )
    assert arm.is_oracle_conflict_escalation(final) is False
    assert arm.blocking_protected_tests(final) == ()


def test_no_parseable_failures_disqualifies() -> None:
    final = _escalation_final(test_output="everything exploded, no pytest summary here")
    assert arm.is_oracle_conflict_escalation(final) is False


def test_a_hand_raise_that_never_validated_disqualifies() -> None:
    """No evidence, no arm. The `capture → supervise` branch skips `test`, so `test_output` can be
    absent — and absent must never be read as "everything failing is protected" (F70, #75)."""
    final = _escalation_final()
    del final["test_output"]
    assert arm.blocking_protected_tests(final) == ()
    assert arm.is_oracle_conflict_escalation(final) is False


def test_the_coders_own_validation_is_read_when_the_engine_has_none() -> None:
    final = _escalation_final()
    del final["test_output"]
    final["coder_test_output"] = _BASELINED_FAIL
    assert arm.blocking_protected_tests(final) == ("tests/test_add.py",)
    assert arm.is_oracle_conflict_escalation(final) is True


def test_the_two_readers_never_disagree_about_which_output_counts() -> None:
    """`blocking_protected_tests` narrows the FILES and `blocking_test_ids` narrows the NODE IDS,
    each by parsing the output itself. Two parses of "which output counts?" is the drift that puts
    a control and its operator surface out of step, so both go through `effective_test_output`.

    Asserted on the fallback path AND on the precedence conflict — the two shapes where a second
    copy would diverge silently."""
    fallback = _escalation_final()
    del fallback["test_output"]
    fallback["coder_test_output"] = _BASELINED_FAIL
    assert arm.blocking_test_ids(fallback) == ("tests/test_add.py::TestAdd::test_add_writes_a_row",)

    # Engine output present and DISAGREEING: the ids must come from the engine's run, not the
    # coder's — a mismatch here would name a test the file set does not contain.
    conflict = _escalation_final(
        coder_test_output="FAILED tests/test_add.py::TestAdd::test_other - E\n"
    )
    assert arm.blocking_test_ids(conflict) == ("tests/test_add.py::TestAdd::test_add_writes_a_row",)


def test_the_SHIPPING_arm_never_sees_the_coders_own_validation() -> None:
    """#75 red team, FIX-NOW. The fallback was argued for the arm that STOPS and asks a human. The
    close-the-gap arm RETRACTS tests and DELIVERS, and it happens to share `_failing_test_files` —
    so routing the fallback through that helper handed producer-timed evidence to the one arm
    whose output is a shipped commit. The two arms must not be coupled by a shared default."""
    shipping = {
        "authored_tests": ["tests/test_new.py"],
        "integrity_baseline": {},
        "proctor_edits": {},
        "coder_test_output": "FAILED tests/test_new.py::test_a - AssertionError\n",
        # no `test_output` — the engine never validated
    }
    assert disp.trapping_engine_tests(shipping) == ()
    # And with the engine's own run present it works exactly as before.
    shipping["test_output"] = "FAILED tests/test_new.py::test_a - AssertionError\n"
    assert disp.trapping_engine_tests(shipping) == ("tests/test_new.py",)


def test_a_tamper_is_never_re_read_as_the_test_being_wrong() -> None:
    assert arm.is_oracle_conflict_escalation(_escalation_final(tests_modified=True)) is False


def test_a_critic_veto_stands() -> None:
    final = _escalation_final(outcome_verdict={"vetoed": True, "reason": "missing requirement"})
    assert arm.is_oracle_conflict_escalation(final) is False


def test_a_real_gate_objection_stands() -> None:
    final = _escalation_final(gate_decision={"reasons": ["validation_failed", "security_findings"]})
    assert arm.is_oracle_conflict_escalation(final) is False


def test_a_run_that_never_raised_its_hand_does_not_qualify() -> None:
    # A no-progress breaker trip is the close-the-gap arm's territory, not this one.
    final = _escalation_final(coder_escalated=False, escalate_reason="", blocked_reason="")
    assert arm.is_oracle_conflict_escalation(final) is False


def test_the_two_arms_do_not_both_claim_the_same_run() -> None:
    """A hand-raise belongs to exactly one arm. is_engine_blocked_give_up already excludes
    coder_escalated; this asserts the pair stays disjoint rather than trusting that by reading."""
    final = _escalation_final()
    assert arm.is_oracle_conflict_escalation(final) is True
    assert disp.is_engine_blocked_give_up(final) is False
