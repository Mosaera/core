from mosaera_policies import GATED_ACTIONS, parse_decision, request_approval


def test_gated_actions_is_exactly_the_wired_set() -> None:
    # PINNED (ADR-0102): every member must have a live request_approval() caller.
    # push/open_pr sat here for months with none — an inert control. Growing this
    # set requires wiring the interrupt, not just naming the action.
    assert GATED_ACTIONS == frozenset({"write_file", "edit_file", "delete_file", "deliver"})


def test_ungated_action_passes_without_interrupt() -> None:
    decision = request_approval("read_file", "reading", {})
    assert decision.approved


def test_parse_approve_words() -> None:
    for raw in ("approve", "APPROVE", "yes", "y", " ok "):
        assert parse_decision(raw).approved


def test_parse_deny_with_feedback() -> None:
    decision = parse_decision("deny: use a smaller diff")
    assert not decision.approved
    assert decision.feedback == "use a smaller diff"


def test_parse_dict() -> None:
    assert parse_decision({"approve": True}).approved
    d = parse_decision({"approve": False, "feedback": "nope"})
    assert not d.approved
    assert d.feedback == "nope"


def test_ambiguous_is_denied() -> None:
    assert not parse_decision("sure why not").approved
    assert not parse_decision(None).approved
    assert not parse_decision(42).approved
