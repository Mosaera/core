"""The oracle's per-leg record must name the leg that actually refused — and change when it changes.

**Why this exists.** `oracle_unverified` is the largest sole cause of an **over-park** on the
125-run baseline (`docs/engineering-history/corpus-baseline-2026-08-11.md`) — a run refusing work
the hidden grader confirms was correct. Nothing recorded WHICH term of

    verified = (four-route independence OR) and mutation_ok and structural_ok

was False, so the cause had to be inferred from a co-recorded field. On 2026-08-11 that inference
produced a confident, wrong hypothesis (25 mutation=`None` over-parks were read as mutation
refusals; only 2 were oracle refusals at all). This module ends the inference.

**The bar these tests hold.** A diagnosis that reads the same however the decision goes is worse
than none — it looks like evidence and carries none. So every leg is driven BOTH ways and the
record must follow. That is the `test_guard_liveness.py` discipline applied to a recording rather
than a guard.
"""

from __future__ import annotations

from typing import Any

from mosaera_core.graph._oracle_legs import LEG_NAMES, NOT_EVALUATED, evaluate_oracle

# Everything present, nothing refusing — the shape a clean delivery has.
_PASS: dict[str, Any] = {
    "tester_vouched": True,
    "standing_suite": lambda: True,
    "test_cmd": True,
    "structural_vouch": True,
    "mutation": True,
    "structural_spec": True,
    "sanctioned_edit": False,
}


def _legs(**over: Any) -> tuple[bool, dict[str, Any]]:
    return evaluate_oracle(**{**_PASS, **over})


def test_a_clean_run_verifies_and_blames_nothing() -> None:
    verified, legs = _legs()
    assert verified is True
    assert legs["blocked_by"] == []
    assert legs["verified"] is True, "the record must carry the SAME value the gate uses"


def test_each_leg_is_named_when_it_is_the_one_that_refused() -> None:
    """THE POINT OF THE MODULE. Drive each term False alone; the record must name that term."""
    for override, expected in (
        ({"mutation": False}, "mutation"),
        ({"structural_spec": False}, "structural"),
        (
            {
                "tester_vouched": False,
                "standing_suite": lambda: False,
                "test_cmd": False,
                "structural_vouch": False,
            },
            "independence",
        ),
    ):
        verified, legs = _legs(**override)
        assert verified is False, override
        assert legs["blocked_by"] == [expected], f"{override} -> {legs['blocked_by']}"


def test_the_record_distinguishes_the_legs_from_each_other() -> None:
    """The positive control for the test above: if `blocked_by` were a constant, or keyed off the
    wrong term, the three cases would be indistinguishable. Assert they are not."""
    blames = {
        tuple(_legs(**o)[1]["blocked_by"])
        for o in (
            {"mutation": False},
            {"structural_spec": False},
            {
                "tester_vouched": False,
                "standing_suite": lambda: False,
                "test_cmd": False,
                "structural_vouch": False,
            },
        )
    }
    assert len(blames) == 3, f"legs are not distinguishable in the record: {blames}"


def test_several_refusing_legs_are_all_named() -> None:
    """A run blocked twice must not read as blocked once — that would hide half the work needed."""
    _, legs = _legs(mutation=False, structural_spec=False)
    assert legs["blocked_by"] == ["mutation", "structural"]


def test_an_unreached_leg_records_not_evaluated_and_is_never_blamed() -> None:
    """`tester_vouched` satisfies the OR, so nothing after it is asked. 'We did not ask' is a
    third state — collapsing it into False would invent refusals that never happened, which is
    the same defect (absence read as proof) this work exists to remove."""
    called = False

    def _suite() -> bool:
        nonlocal called
        called = True
        return False

    verified, legs = _legs(standing_suite=_suite)
    assert verified is True
    assert called is False, "the OR must still short-circuit — the suite leg walks the workspace"
    for leg in ("standing_suite", "test_cmd", "structural_vouch"):
        assert legs[leg] == NOT_EVALUATED
    assert legs["blocked_by"] == []


def test_the_first_true_route_is_the_one_recorded() -> None:
    """Each route in turn carries the OR alone; the record must show which one did."""
    for winner in ("tester_vouched", "test_cmd", "structural_vouch"):
        off = {
            "tester_vouched": False,
            "standing_suite": lambda: False,
            "test_cmd": False,
            "structural_vouch": False,
        }
        verified, legs = _legs(**{**off, winner: True})
        assert verified is True, winner
        assert legs[winner] is True, winner
        assert legs["independent"] is True, winner


def test_a_sanctioned_test_edit_makes_an_UNMEASURED_mutation_refuse() -> None:
    """ADR-0087's named backstop: once the acceptance bar is renegotiated mid-run, the mutation
    floor vouches only on a PROVEN catch. The record must show that the raw value did not change
    — only the rule reading it did — or the two cases look identical in the corpus."""
    _, loose = _legs(mutation=None, sanctioned_edit=False)
    assert loose["mutation_ok"] is True and loose["blocked_by"] == []

    verified, tight = _legs(mutation=None, sanctioned_edit=True)
    assert verified is False
    assert tight["blocked_by"] == ["mutation"]
    assert tight["mutation_raw"] is None, "the raw tri-state must survive alongside the verdict"
    assert tight["sanctioned_test_edit"] is True, "…and so must the reason the rule tightened"


def test_a_proven_false_mutation_refuses_under_either_rule() -> None:
    """The veto whose cost the A/B will measure. Both branches must block on a proven False —
    that is the behaviour under test, and it must not drift while the None case is discussed."""
    for sanctioned in (True, False):
        verified, legs = _legs(mutation=False, sanctioned_edit=sanctioned)
        assert verified is False, sanctioned
        assert legs["blocked_by"] == ["mutation"], sanctioned


def test_none_and_false_are_not_the_same_record() -> None:
    """The distinction the whole 2026-08-11 investigation turned on."""
    _, none_legs = _legs(mutation=None)
    _, false_legs = _legs(mutation=False)
    assert none_legs["mutation_raw"] is None
    assert false_legs["mutation_raw"] is False
    assert none_legs["blocked_by"] != false_legs["blocked_by"]


def test_the_veto_knob_diverts_the_decision_and_nothing_else() -> None:
    """C3_EXERCISED for `oracle_mutation_vetoes`: the knob must CHANGE an outcome, not merely be
    read. A knob whose two arms decide identically makes an A/B unreadable — the failure
    `bench/liveness.py` stamps INVALID_EXPERIMENT_IDENTICAL_EXECUTION.
    """
    on, on_legs = _legs(mutation=False, mutation_vetoes=True)
    off, off_legs = _legs(mutation=False, mutation_vetoes=False)
    assert on is False and on_legs["blocked_by"] == ["mutation"]
    assert off is True and off_legs["blocked_by"] == [], "arm B must actually deliver"
    assert off_legs["mutation_raw"] is False, (
        "arm B RECORDS the surviving mutation, it just stops vetoing on it"
    )
    assert on_legs["mutation_vetoes"] != off_legs["mutation_vetoes"], "the arm must be readable"


def test_arm_B_leaves_the_ADR_0087_absence_backstop_standing() -> None:
    """The safety property that makes arm B a one-behaviour change rather than a weaker posture.

    A sanctioned test edit renegotiates the acceptance bar mid-run, so ADR-0087 requires a PROVEN
    catch there. Arm B drops the proven-False veto — it must NOT also drop that.
    """
    verified, legs = _legs(mutation=None, sanctioned_edit=True, mutation_vetoes=False)
    assert verified is False, "an UNMEASURED mutation after a sanctioned edit must still refuse"
    assert legs["blocked_by"] == ["mutation"]

    # …while the proven-False case in that same branch does stop vetoing. Both, or the arms are
    # not the single-behaviour difference this experiment claims to be.
    ok, _ = _legs(mutation=False, sanctioned_edit=True, mutation_vetoes=False)
    assert ok is True


def test_arm_A_is_byte_identical_to_the_shipped_default() -> None:
    """The knob defaults True, so merging it must change NOTHING. Assert the default arm agrees
    with an explicit True across every combination that reaches the mutation floor."""
    for sanctioned in (True, False):
        for mutation in (True, False, None):
            default, _ = _legs(mutation=mutation, sanctioned_edit=sanctioned)
            explicit, _ = _legs(mutation=mutation, sanctioned_edit=sanctioned, mutation_vetoes=True)
            assert default is explicit, (sanctioned, mutation)


def test_the_mutation_cause_distinguishes_absence_from_proof() -> None:
    """`mutation_raw=None` collapses at least four unrelated situations — never attempted, no
    suite to run, the check faulted, nothing mutable in the changed lines. Under ADR-0087's
    backstop a sanctioned test edit makes a None REFUSE the run, so "we never looked" currently
    parks identically to "we looked and could not tell".

    Measured 2026-08-12: 5 of 47 baseline over-parks are exactly `mutation_raw=None` +
    `sanctioned_test_edit=True`. Diagnostic only — the verdict below is unchanged by the cause.
    """
    verdict_a, legs_a = _legs(mutation=None, sanctioned_edit=True, mutation_cause="not_attempted")
    verdict_b, legs_b = _legs(
        mutation=None, sanctioned_edit=True, mutation_cause="no_mutable_construct"
    )
    assert verdict_a is False and verdict_b is False, "both still refuse — this changes nothing"
    assert legs_a["blocked_by"] == ["mutation"] and legs_b["blocked_by"] == ["mutation"]
    assert legs_a["mutation_cause"] != legs_b["mutation_cause"], (
        "the two situations must be distinguishable in the record even though they park alike"
    )


def test_the_cause_never_changes_the_verdict() -> None:
    """The positive control against scope creep: a diagnostic that altered the decision would be
    a gate change wearing an instrumentation label."""
    for cause in ("", "measured", "faulted:OSError", "no_test_files", "not_attempted"):
        assert _legs(mutation=False, mutation_cause=cause)[0] is False
        assert _legs(mutation=True, mutation_cause=cause)[0] is True


def test_an_ABSENT_cause_means_never_attempted_not_a_stale_one() -> None:
    """The cause must travel WITH the verdict, never be written unconditionally.

    A first draft set `tests_mutation_cause` at the top of the mutation block on every implement
    call, while `tests_mutation_caught` is written only when the check actually runs. On a
    multi-iteration run a later call then overwrote the cause and left it disagreeing with the
    verdict it explains — a record drifting from the thing it records, which is the defect this
    field exists to remove. Caught by inspection before the measurement sweep consumed it.

    An empty cause alongside a real verdict is the shape that must never occur.
    """
    _, legs = _legs(mutation=True, mutation_cause="measured")
    assert legs["mutation_raw"] is True and legs["mutation_cause"] == "measured"

    # Absent cause + absent verdict is the honest "never attempted" pair.
    _, none_legs = _legs(mutation=None, mutation_cause="")
    assert none_legs["mutation_raw"] is None and none_legs["mutation_cause"] == ""


def test_recorded_legs_are_exactly_LEG_NAMES() -> None:
    """The exported list and the evaluated one must be the same list (#121).

    `LEG_NAMES` is what the onboarding flow tells an operator can vouch for their repo. If a fifth
    route were added to the evaluation and not here (or the reverse), the product would describe a
    different mechanism than the one that judges the run — the drift this module exists to end.
    """
    _, legs = _legs()
    assert tuple(k for k in legs if k in set(LEG_NAMES)) == LEG_NAMES  # present, and in order
