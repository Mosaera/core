"""The clarification channel has ONE consumer and THREE producers — they must agree.

`clarification.proposals` is consumed by `resolve_clarification`, which writes the accepted
proposal into `backlog_items.acceptance` verbatim. That contract is stated for intake: the PM
prompt says *"each proposal is the COMPLETE acceptance text the item would have if accepted"*, and
`intake_ask.divert_undecidable_to_asks` passes an `enhance` op's acceptance for exactly that reason.

The ESCALATE arm was added later and writes **instructions to a human** — *"Amend the acceptance
criteria so tests/x.py can pass as written."* — into the same field, which the card renders as
one-click buttons. One click therefore replaced an item's acceptance with a sentence about
amending it, and the next run minted ENTAILED claims from that sentence.

The same shape as #68: a later feature landing on a contract it had never been told about, with
every test green. These tests are the agreement.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from test_api import _client_with, _FakeProjectMemory

_ORIGINAL = "search prints every matching note in id order; exits 0 on no match"

_ARM_FINAL = {
    "coder_escalated": True,
    "escalate_reason": "the task conflicts with a test: it pins a date never supplied",
    "give_up_reason": "escalation unresolved: the task conflicts with a test",
    "integrity_baseline": {"tests/test_add.py": "h1"},
    "authored_tests": [],
    "test_output": "FAILED tests/test_add.py::test_row - AssertionError\n1 failed, 2 passed\n",
    # `test_node` ran and found no tamper. PRESENT, not merely falsy: red-team R1 showed the two
    # channels are written only by that node, so on a hand-raise (capture -> supervise) they are
    # ABSENT — and an absent key read as "clean" is what let a tampering producer reach the ask.
    # `ask_withheld_reason` now distinguishes the two, so a fixture that omits them is modelling
    # the hand-raise branch whether it means to or not.
    "tests_modified": False,
    "destroyed_paths": [],
    "gate_decision": {"reasons": ["validation_failed"]},
    # What `supervise_node` RECORDS when the arm concludes (#68 / ADR-0090 MR3). The ask reads this
    # rather than re-deriving `is_oracle_conflict_escalation` from a `gate_decision` that has moved
    # on since the stop — the two used to disagree, so a stop could fire and the ask still be
    # refused. A final state that reached the arm always carries it; this fixture must too.
    "ask_blocking_tests": ["tests/test_add.py"],
}


def _arm_ctx(memory: Any) -> Any:
    from mosaera_api.app_context._escalation import EscalationMixin

    ctx = EscalationMixin.__new__(EscalationMixin)
    ctx.history = memory  # type: ignore[attr-defined]
    return ctx


def _item_with_an_escalate_ask() -> tuple[Any, int]:
    """A real item carrying a REAL ask written by the REAL arm — not a hand-built fixture.

    Hand-building the clarification would test my idea of what the arm writes. The defect was
    precisely that the arm writes something else, so the arm has to be the one that writes it.
    """
    mem: Any = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    item_id = mem.add_backlog_item("p1", "search", "", _ORIGINAL, 0)
    ctx = _arm_ctx(mem)
    session = SimpleNamespace(final=dict(_ARM_FINAL))
    asked = ctx._try_escalate_arm(
        {"id": item_id}, "r1", session, SimpleNamespace(escalate_arm=True)
    )
    assert asked is True, "the arm did not fire — the fixture no longer reproduces the situation"
    return mem, item_id


def test_an_escalate_proposal_can_never_become_the_acceptance() -> None:
    """THE regression. This failed before the fix, with the acceptance replaced by an instruction.

    The arm's proposals are directions for a human ("amend the criteria so X can pass"). Accepting
    one by index used to write that sentence into `acceptance`, destroying the operator's bar and
    re-minting every ENTAILED claim from a sentence about amending criteria.
    """
    mem, item_id = _item_with_an_escalate_ask()
    client = _client_with(mem)

    response = client.post(
        f"/api/projects/p1/backlog/{item_id}/clarification/resolve",
        json={"accepted_proposal_index": 0},
    )

    assert response.status_code == 400, (
        "a DIRECTION proposal was accepted as acceptance text — the bar is now "
        f"{mem.get_backlog_item(item_id)['acceptance']!r}"
    )
    assert mem.get_backlog_item(item_id)["acceptance"] == _ORIGINAL
    still_open = mem.item_clarification(item_id)
    assert still_open is not None and still_open["status"] == "open", (
        "a REFUSED resolve closed the ask — the operator loses the question and the item "
        "silently proceeds with the bar nobody answered about"
    )


def test_the_arm_marks_its_proposals_as_directions() -> None:
    """The producer half: the arm declares what its strings are, so the consumer can refuse them."""
    mem, item_id = _item_with_an_escalate_ask()
    ask = mem.item_clarification(item_id)
    assert ask["proposal_kind"] == "direction"
    assert ask["axis"] == "reachability"  # ADR-0089's vocabulary, not a parallel enum
    assert ask["proposals"], "the prose must survive — it is the operator's context"


def test_an_intake_proposal_still_becomes_the_acceptance() -> None:
    """The other half: the honouring producers are untouched. A fix that broke intake would be
    a worse defect than the one it closes."""
    mem: Any = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    item_id = mem.add_backlog_item("p1", "wiring", "", "everything wired up nicely", 0)
    mem.set_item_clarification(
        item_id,
        claim_text="everything wired up nicely",
        why_unbindable="no observable behaviour",
        proposals=[_ORIGINAL],
        axis="checkability",
        proposal_kind="acceptance",
    )
    client = _client_with(mem)

    response = client.post(
        f"/api/projects/p1/backlog/{item_id}/clarification/resolve",
        json={"accepted_proposal_index": 0},
    )
    assert response.status_code == 200
    assert mem.get_backlog_item(item_id)["acceptance"] == _ORIGINAL


def test_a_legacy_row_is_refused_not_trusted() -> None:
    """Deny-by-default over rows already in the live database.

    Every clarification written before this change lacks `proposal_kind`. Defaulting those to
    "acceptance" would reproduce the exact defect for every existing row, which is the tempting
    and wrong migration. An unlabelled proposal is refused; the operator's own text still works.
    """
    mem: Any = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    item_id = mem.add_backlog_item("p1", "legacy", "", _ORIGINAL, 0)
    mem.set_item_clarification(
        item_id,
        claim_text="legacy ask",
        why_unbindable="written before the discriminator existed",
        proposals=["some older proposal text"],
        axis="checkability",
        proposal_kind="acceptance",
    )
    # Simulate the on-disk shape: strip the discriminator the way an old row lacks it.
    row = dict(mem.item_clarification(item_id))
    row.pop("proposal_kind", None)
    mem.items[item_id]["clarification"] = row

    client = _client_with(mem)
    refused = client.post(
        f"/api/projects/p1/backlog/{item_id}/clarification/resolve",
        json={"accepted_proposal_index": 0},
    )
    assert refused.status_code == 400
    assert mem.get_backlog_item(item_id)["acceptance"] == _ORIGINAL

    accepted = client.post(
        f"/api/projects/p1/backlog/{item_id}/clarification/resolve",
        json={"edited_text": "prints matches in id order; exits 2 when none match"},
    )
    assert accepted.status_code == 200, "operator-authored text must always be accepted"
    assert mem.get_backlog_item(item_id)["acceptance"].startswith("prints matches in id order")


def test_the_store_refuses_an_unlabelled_ask() -> None:
    """A fourth producer that forgets the discriminator fails loudly at the boundary.

    Required-with-no-default is the whole mechanism. A default would silently readmit the bug the
    moment someone adds a fifth ask, which is how this one arrived.
    """
    mem: Any = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    item_id = mem.add_backlog_item("p1", "x", "", _ORIGINAL, 0)
    with pytest.raises(TypeError):
        mem.set_item_clarification(item_id, claim_text="c", why_unbindable="w", proposals=["p"])


def test_bar_stands_retry_leaves_the_acceptance_alone() -> None:
    """The missing operator position: *the bar is right, the CODE is wrong, try again.*

    Before this, the card offered one-click bar-lowering, a text box, and "Dismiss" — so the only
    way to say the producer was wrong was the button labelled as giving up.
    """
    mem, item_id = _item_with_an_escalate_ask()
    client = _client_with(mem)

    response = client.post(
        f"/api/projects/p1/backlog/{item_id}/clarification/resolve",
        json={"disposition": "bar_stands_retry"},
    )
    assert response.status_code == 200
    assert mem.get_backlog_item(item_id)["acceptance"] == _ORIGINAL
    record = mem.get_backlog_item(item_id)["clarification_record"]
    assert record["status"] == "affirmed", (
        "affirming the bar must be RECORDED, or the next sweep asks the identical question and "
        "the operator is nagged into lowering it"
    )


# --- F49: the ESCALATE arm asks the operator instead of burying the item ----------------------
# Moved here from test_api.py when ADR-0091 landed: these test the same producer whose contract
# the tests above pin, and test_api.py is a grandfathered god-file the ratchet only lets shrink.


def test_the_escalate_arm_raises_an_ask_on_the_item() -> None:
    mem, item_id = _item_with_an_escalate_ask()
    ask = mem.item_clarification(item_id)
    # The operator must be able to act without going to find out which test blocked it.
    assert "tests/test_add.py" in ask["claim_text"]
    assert "pins a date never supplied" in ask["why_unbindable"]
    assert len(ask["proposals"]) >= 1


def test_the_arm_is_silent_when_the_knob_is_off() -> None:
    mem: Any = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    item_id = mem.add_backlog_item("p1", "search", "", _ORIGINAL, 0)
    ctx = _arm_ctx(mem)
    session = SimpleNamespace(final=dict(_ARM_FINAL))
    assert (
        ctx._try_escalate_arm({"id": item_id}, "r1", session, SimpleNamespace(escalate_arm=False))
        is False
    )
    assert mem.item_clarification(item_id) is None


def test_the_arm_keeps_out_of_a_genuine_code_defect() -> None:
    mem: Any = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    item_id = mem.add_backlog_item("p1", "search", "", _ORIGINAL, 0)
    ctx = _arm_ctx(mem)
    # A coder-OWNED failure means `supervise_node` recorded no conflict at all — that is what
    # "the arm keeps out" looks like now that its structural answer is recorded once, at the
    # moment it is made, rather than re-derived here from output that has moved on.
    final = {
        **_ARM_FINAL,
        "test_output": "FAILED tests/test_mine.py::test_x\n1 failed\n",
        "ask_blocking_tests": [],
    }
    session = SimpleNamespace(final=final)
    assert (
        ctx._try_escalate_arm({"id": item_id}, "r1", session, SimpleNamespace(escalate_arm=True))
        is False
    )
    assert mem.item_clarification(item_id) is None  # the park stands on its own terms


def test_an_affirmed_bar_is_not_asked_about_again() -> None:
    """Asking once is a question; asking every sweep is pressure.

    The arm re-fires on each sweep, and the caller skips defer specifically so the item stays
    visible. Without suppression an operator who answered "the bar stands" gets the identical
    question forever, and the only answer that makes it stop is the one that lowers the bar.
    """
    mem, item_id = _item_with_an_escalate_ask()
    client = _client_with(mem)
    client.post(
        f"/api/projects/p1/backlog/{item_id}/clarification/resolve",
        json={"disposition": "bar_stands_retry"},
    )
    assert mem.item_clarification(item_id) is None  # the ask is closed

    ctx = _arm_ctx(mem)
    session = SimpleNamespace(final=dict(_ARM_FINAL))
    again = ctx._try_escalate_arm(
        {"id": item_id}, "r2", session, SimpleNamespace(escalate_arm=True)
    )
    assert again is True, "the item must still skip the defer rung — it is retryable, not buried"
    assert mem.item_clarification(item_id) is None, "the same question was raised a second time"


def test_a_DIFFERENT_wall_still_raises_a_fresh_question() -> None:
    """Suppression is per-bar, not per-item — affirming one wall must not silence the next."""
    mem, item_id = _item_with_an_escalate_ask()
    client = _client_with(mem)
    client.post(
        f"/api/projects/p1/backlog/{item_id}/clarification/resolve",
        json={"disposition": "bar_stands_retry"},
    )
    ctx = _arm_ctx(mem)
    other = {
        **_ARM_FINAL,
        "integrity_baseline": {"tests/test_other.py": "h9"},
        "test_output": "FAILED tests/test_other.py::test_z - AssertionError\n1 failed\n",
        # A different wall ⇒ supervise recorded a different blocking test. Keeping this in step
        # with the output is the invariant supervise guarantees in production.
        "ask_blocking_tests": ["tests/test_other.py"],
    }
    ctx._try_escalate_arm(
        {"id": item_id}, "r3", SimpleNamespace(final=other), SimpleNamespace(escalate_arm=True)
    )
    fresh = mem.item_clarification(item_id)
    assert fresh is not None and "tests/test_other.py" in fresh["claim_text"]


def test_a_gate_objection_recorded_AFTER_supervise_still_silences_the_ask() -> None:
    """The exclusion that only the final state can answer (#68).

    Fixing the double evaluation must not quietly drop this. On the give-up path the gate runs
    AFTER `supervise_node`, so a security objection is invisible when the conflict is recorded —
    and ADR-0075 red-teamed twice that a real objection means the park stands on its own terms.
    Supervise's structural answer is trusted; this is a different question, asked where its inputs
    are final.
    """
    mem: Any = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    item_id = mem.add_backlog_item("p1", "search", "", _ORIGINAL, 0)
    ctx = _arm_ctx(mem)
    late = {**_ARM_FINAL, "gate_decision": {"reasons": ["validation_failed", "security_findings"]}}
    assert (
        ctx._try_escalate_arm(
            {"id": item_id}, "r1", SimpleNamespace(final=late), SimpleNamespace(escalate_arm=True)
        )
        is False
    )
    assert mem.item_clarification(item_id) is None


def test_a_critic_veto_recorded_after_supervise_also_silences_the_ask() -> None:
    mem: Any = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    item_id = mem.add_backlog_item("p1", "search", "", _ORIGINAL, 0)
    ctx = _arm_ctx(mem)
    vetoed = {**_ARM_FINAL, "outcome_verdict": {"vetoed": True, "reason": "missing requirement"}}
    assert (
        ctx._try_escalate_arm(
            {"id": item_id}, "r1", SimpleNamespace(final=vetoed), SimpleNamespace(escalate_arm=True)
        )
        is False
    )
    assert mem.item_clarification(item_id) is None


def test_the_ask_is_reachable_on_a_manually_launched_run() -> None:
    """The arm's CALL SITE, not its predicate — the half every other test here cannot see.

    Measured live 2026-08-21 (run `20260821-180202-7865c0`): item #113 was driven into a genuine
    oracle conflict, the run parked `incomplete` with an honest `termination_reason`, and the item
    carried NO clarification. Every unit test above was green throughout, because they all invoke
    `_try_escalate_arm` directly. `_after()` returned at `if not chain` first, and the "Run guided"
    button on a backlog card launches with `chain=False` (`routes/backlog.py`) — so on the path an
    operator actually uses, the arm was dead code.

    That is F62's shape a layer up: the stop worked, the ask never fired. Asserting the arm behaves
    correctly proves nothing if nothing calls it, so this asserts that something calls it.
    """
    import ast
    import inspect

    from mosaera_api.app_context import _launch

    tree = ast.parse(inspect.getsource(_launch))
    after = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_after")
    guard = next(
        n
        for n in ast.walk(after)
        if isinstance(n, ast.If)
        and isinstance(n.test, ast.UnaryOp)
        and isinstance(n.test.op, ast.Not)
        and isinstance(n.test.operand, ast.Name)
        and n.test.operand.id == "chain"
    )
    called = {
        n.func.attr
        for n in ast.walk(guard)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert "_try_escalate_arm" in called, (
        "the escalate arm is no longer reached on a non-chained run — a manually launched item "
        "that parks on an oracle conflict will leave the operator an honest stop and nothing to "
        "answer, which is F62 verbatim"
    )
    # The siblings stay chain-only ON PURPOSE: they take autonomy (launch another run, ship a
    # diff, move the item out of the picker). Only the arm is hoisted, because raising a question
    # takes none. If one of these appears here, the hoist went further than it was meant to.
    for autonomy in ("_try_model_escalation", "_try_close_named_gap", "_try_recurate_or_defer"):
        assert autonomy not in called, f"{autonomy} must not run on a human-driven single run"
