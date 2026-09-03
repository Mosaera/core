"""The option the gate OFFERED must be the option the engine OBEYS (ADR-0082, F61).

`gate_outcomes`/`escalation_outcomes` compute each option's `effect` and show the operator a
consequence sentence derived from it. Until 2026-08-21 that verb was thrown away at the API
boundary: `runner/_lifecycle.approve` validated `option_id` against the offered set and then
recorded it as *"what the operator BELIEVED they chose"*, forwarding only `(approve, feedback)`.

`stop_honestly` and `send_back` are BOTH `approve=False` carrying whatever is in the notes box, so
they arrived byte-identical and `supervise_node` had to infer intent from `not feedback`. That
inference is wrong in exactly the case the option exists for: when `finalizes` is empty the run CAN
continue, so `stop_honestly` is the operator's only way to stop — and typing a note to explain why
made the run re-scope instead. F61's shape reproduced inside F61's own fix, one day old, found by
audit rather than by the live validation that ran right past it.

These tests pin the routing, not the label. Kept out of `test_graph_build.py`, which is over the
god-file ratchet and therefore shrink-only.
"""

from __future__ import annotations

from typing import Any

from test_graph_build import _run_supervise, _supervise_ctx, _supervise_state

# A CODER-OWNED failure: `tests/test_mine.py` is absent from `integrity_baseline`, so the producer
# may edit it, there is no oracle conflict, and `escalation_finalizes` returns "". This is the
# branch where the run can genuinely continue — the only branch on which the bug is reachable, and
# the one the 2026-08-21 live run happened not to exercise.
_CONTINUABLE = {"test_output": "FAILED tests/test_mine.py::test_x - AssertionError\n1 failed\n"}


def _answer(effect: str, **over: Any) -> dict[str, Any]:
    """What `_lifecycle.approve` now puts on the queue for a clicked option.

    `approve=False` and a non-empty `feedback` for both effects on purpose: that pair is precisely
    what the two options used to collapse into.
    """
    d: dict[str, Any] = {
        "resolution": "human",
        "approve": False,
        "feedback": "the bar is wrong and I want it on the record",
        "effect": effect,
    }
    d.update(over)
    return d


def test_stop_honestly_stops_even_when_the_run_could_continue() -> None:
    """THE regression. Before the fix this re-scoped, because notes were read as a vote."""
    final = _run_supervise(
        _supervise_ctx(True), _supervise_state(**_CONTINUABLE), _answer("end_run")
    )
    assert final.get("give_up_reason"), (
        "the operator chose an option whose stated consequence was 'ends the run' — writing notes "
        "alongside it must not turn it into a re-scope"
    )
    assert not final.get("feedback"), "a re-scope would send it back at the same wall"
    assert final.get("stalled") is False, "an accurate stop reads honest_park, never thrash"


def test_send_back_still_re_scopes_with_the_same_approve_and_feedback() -> None:
    """The other half: identical `(approve, feedback)`, opposite routing. If this and the test
    above ever agree, the effect stopped being read and the two options collapsed again."""
    final = _run_supervise(
        _supervise_ctx(True), _supervise_state(**_CONTINUABLE), _answer("send_back")
    )
    assert final.get("feedback"), "the operator asked for a revision — it must re-scope"
    assert not final.get("give_up_reason")


def test_an_ending_option_cannot_be_overridden_by_notes_on_a_forced_stop() -> None:
    """`finalizes` non-empty already ends the run; the effect must not weaken that. This is the
    path the live run DID take on 2026-08-21, which is why the defect survived validation."""
    final = _run_supervise(_supervise_ctx(True), _supervise_state(), _answer("end_run"))
    assert final.get("give_up_reason")
    assert "tests/test_add.py" in final["give_up_reason"], "the blocking test must still be named"


def test_a_client_that_sends_no_effect_keeps_the_legacy_behaviour() -> None:
    """Compatibility is the default (CLAUDE.md). A caller with no option — a scripted client, or a
    park that offers none — must route exactly as it did before `effect` existed: a human who
    declines WITHOUT a way forward stops, and one who supplies notes re-scopes."""
    declined = _run_supervise(
        _supervise_ctx(True),
        _supervise_state(**_CONTINUABLE),
        {"resolution": "human", "approve": False, "feedback": ""},
    )
    assert declined.get("give_up_reason"), "no effect, no notes, no approval — still a stop"

    with_notes = _run_supervise(
        _supervise_ctx(True),
        _supervise_state(**_CONTINUABLE),
        {"resolution": "human", "approve": False, "feedback": "try the other approach"},
    )
    assert with_notes.get("feedback"), "no effect + notes must still re-scope"
    assert not with_notes.get("give_up_reason")
