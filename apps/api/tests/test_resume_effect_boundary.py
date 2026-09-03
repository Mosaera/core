"""The operator's chosen option must SURVIVE the API→engine boundary (ADR-0082/0107).

Red-team R1, 2026-08-21, found independently by two agents: `_lifecycle.approve()` put `effect` on
the resume queue, and `_resolve_escalation` then *rebuilt* the resume as a fresh literal dict
carrying only `resolution`/`approve`/`feedback`/`authorize_tests`. `effect` was dropped one function
later, so `_supervise`'s `effect == "end_run"` clause could never fire and "Stop and record it
honestly" was inert in production.

Three tests were green over it. `test_option_effect_routing.py` hand-builds a resume and injects it
straight into the graph — BELOW the seam that drops the field. `test_api.py` asserts only that
`effect` reaches the queue — ABOVE it. Two correct halves with the defect between them: the
repo's own no-caller/green-by-vacancy class, and the fourth instance of it in this arc.

So this file tests the SEAM and nothing else: everything here goes through the real
`session.approve()` and the real `_resolve_escalation`. Adding a resume field without adding it to
that rebuilt dict must fail here.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from test_api import _session

_OUTCOMES = [
    {"id": "send_back", "label": "Send it back", "effect": "send_back"},
    {"id": "stop_honestly", "label": "Stop and record it honestly", "effect": "end_run"},
]


def _escalation_park(session: Any) -> Any:
    """The interrupt an escalation actually parks on, with its computed outcomes."""
    return SimpleNamespace(id="esc-1", value={"action": "escalation", "outcomes": _OUTCOMES})


def _resolve(session: Any, **body: Any) -> dict[str, Any]:
    """Drive one park→approve→resume cycle through the REAL guided-mode escalation path."""
    import threading

    intr = _escalation_park(session)
    out: dict[str, Any] = {}

    def worker() -> None:
        out.update(session._resolve_escalation(intr, intr.value))

    t = threading.Thread(target=worker)
    t.start()
    for _ in range(500):  # wait for the park to open the decision slot
        if session.status == "awaiting_approval" and session._awaiting_decision:
            break
        threading.Event().wait(0.01)
    session.approve(**body)
    t.join(timeout=10)
    return out


def test_the_chosen_effect_reaches_the_engine() -> None:
    """THE regression. Before the fix this returned a dict with no `effect` key at all."""
    s = _session("eff-1", auto=False)
    resume = _resolve(s, approved=False, feedback="the bar is wrong", option_id="stop_honestly")
    assert resume.get("effect") == "end_run", (
        "the gate computed `end_run` for the option the operator clicked and the engine never saw "
        "it — supervise then falls back to inferring intent from whether the notes box is empty, "
        "which is exactly the F61 defect this was meant to fix"
    )
    # ...and the fields that already worked must be untouched.
    assert resume["resolution"] == "human"
    assert resume["approve"] is False
    assert resume["feedback"] == "the bar is wrong"


def test_send_back_survives_too_and_is_distinguishable() -> None:
    """Both options post `approve=False` with the same notes. If these two ever agree, the engine
    is back to guessing and the two buttons have silently collapsed into one."""
    s = _session("eff-2", auto=False)
    resume = _resolve(s, approved=False, feedback="try the other approach", option_id="send_back")
    assert resume.get("effect") == "send_back"


def test_a_park_with_no_options_carries_no_effect() -> None:
    """Compatibility: a legacy client, or a park declaring no outcomes, keeps the old routing."""
    s = _session("eff-3", auto=False)
    intr = SimpleNamespace(id="esc-2", value={"action": "escalation"})
    import threading

    out: dict[str, Any] = {}
    t = threading.Thread(target=lambda: out.update(s._resolve_escalation(intr, intr.value)))
    t.start()
    for _ in range(500):
        if s.status == "awaiting_approval" and s._awaiting_decision:
            break
        threading.Event().wait(0.01)
    s.approve(approved=False, feedback="")
    t.join(timeout=10)
    assert out.get("effect") == ""


def test_an_unknown_verb_is_not_forwarded() -> None:
    """Deny-by-default on the seam. `_supervise` treats ANY truthy effect as a deliberate choice
    and skips its legacy inference, so an unrecognised verb would fail OPEN — continuing a run the
    operator asked to stop. A verb outside the routed set resolves to "" instead."""
    s = _session("eff-4", auto=False)
    intr = SimpleNamespace(
        id="esc-3",
        value={
            "action": "escalation",
            "outcomes": [{"id": "weird", "label": "?", "effect": "request_dependency"}],
        },
    )
    import threading

    out: dict[str, Any] = {}
    t = threading.Thread(target=lambda: out.update(s._resolve_escalation(intr, intr.value)))
    t.start()
    for _ in range(500):
        if s.status == "awaiting_approval" and s._awaiting_decision:
            break
        threading.Event().wait(0.01)
    s.approve(approved=False, feedback="notes", option_id="weird")
    t.join(timeout=10)
    assert out.get("effect") == "", "an unrouted verb must not suppress the legacy give-up clause"


def test_the_allowlist_covers_every_verb_the_gate_can_emit() -> None:
    """`_RESUME_EFFECTS` is hand-written; this ties it to reality (red team R2, DEFER promoted).

    A verb outside the set is resolved to "" at the seam. That is the right default for an UNKNOWN
    string, but it is the wrong outcome for a legitimate new one: `_supervise` treats any truthy
    effect as a deliberate choice and skips its legacy inference, so an ending verb silently reduced
    to "" would fall back to that inference and — with notes typed — RE-SCOPE a run the operator
    asked to end. F61's shape inside the guard written to prevent it.

    Derived, never a second hand-written list: this fails the day someone adds a `GateOutcome` verb
    without teaching the seam about it, which is exactly when it needs to fail.
    """
    from mosaera_api.runner._budget import _RESUME_EFFECTS
    from mosaera_core.graph._gate_outcomes import escalation_outcomes, gate_outcomes

    emitted: set[str] = set()
    for finalizes in ("", "the iteration cap is spent"):
        for amendable in (None, {"tests": ["tests/t.py::test_a"], "paths": ["tests/t.py"]}):
            for regressions in ([], ["tests/t.py::test_a"]):
                emitted |= {
                    o.effect
                    for o in escalation_outcomes(
                        finalizes=finalizes,
                        finalizes_if_amended="",
                        amendable=amendable,
                        regressions=regressions,
                    )
                }
    # The delivery gate, across the iteration positions that change which options exist.
    for iteration in (1, 5):
        emitted |= {
            o.effect
            for o in gate_outcomes(
                {"iteration": iteration, "gate_decision": {"reasons": ["validation_failed"]}},
                max_iter=5,
            )
        }

    assert emitted, "the generators produced nothing — this test would pass vacuously"
    assert emitted <= _RESUME_EFFECTS, (
        f"the gate can emit {sorted(emitted - _RESUME_EFFECTS)}, which the resume seam would drop "
        "to '' — teach `_RESUME_EFFECTS` about it, or supervise will silently re-scope on it"
    )
