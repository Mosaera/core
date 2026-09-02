"""The exception-surface over-strictness checks (#129 slice 3).

Added from a LABELLED corpus rather than intuition: `overstrict_vs_ref` marks how much stricter the
authored suite is than the reference solution, and on 10 labelled positives the production detector
fired zero times. These two shapes recur across MCB-06/17/18.

The tests that matter most are the ones pinning what must NOT fire — a detector that flags faithful
assertions trades away the precision that makes the existing one trustworthy, and its findings feed
the Proctor's coder-blind repair turn.
"""

from __future__ import annotations

import ast

from mosaera_core.bar_integrity import check_exception_message_pin, check_type_name_string


def _assert_node(src: str) -> ast.Assert:
    node = ast.parse(src).body[0]
    assert isinstance(node, ast.Assert)
    return node


def _msg(src: str, spec: str = "") -> list:
    return check_exception_message_pin(_assert_node(src), "tests/t.py", spec)


def _type(src: str, spec: str = "") -> list:
    return check_type_name_string(_assert_node(src), "tests/t.py", spec)


def test_it_flags_a_pinned_error_message() -> None:
    """The most common over-strict shape in the labelled corpus. The spec says an error is RAISED;
    the test pins the wording, so rephrasing the message fails a correct implementation."""
    found = _msg('assert "not found" in str(exc_info.value)')
    assert len(found) == 1
    assert found[0].kind == "exception_message_pin"
    assert "pytest.raises" in found[0].suggestion


def test_it_flags_the_common_spellings() -> None:
    """MCB-06/17/18 between them use all of these. A check that only handles one is a check that
    fires on one case."""
    for src in (
        'assert "boom" in str(e)',
        'assert "boom" in str(exc)',
        'assert "boom" in str(err)',
        'assert "boom" in error_message',
        'assert "boom" in str(cm.exception)',
    ):
        assert _msg(src), f"missed: {src}"


def test_a_SPEC_QUOTED_message_is_faithful_and_never_flagged() -> None:
    """THE PRECISION GUARD, and the same one every check in this module inherits. If the task text
    pins the wording, the wording IS the contract — flagging it would push the Proctor to loosen a
    bar the spec set, which is the direction ADR-0062 was reverted for."""
    spec = 'the command must fail with "config not found" on a missing file'
    assert _msg('assert "config not found" in str(e)', spec) == []


def test_it_flags_a_type_name_smuggled_through_a_string() -> None:
    """`str(type(e))` survives no rename and is weaker than the isinstance it stands in for.
    100% precision on the labelled corpus — it fired on no negative."""
    found = _type('assert "OperationError" in str(type(e))')
    assert len(found) == 1
    assert found[0].kind == "type_name_string"
    assert "isinstance" in found[0].suggestion


def test_neither_check_claims_a_mechanical_rewrite_is_safe() -> None:
    """`auto_loosenable` is a hint to a JUDGMENT-based loosener, and ADR-0062's deterministic
    rewriter was reverted for reopening false-ship. Rewriting either of these needs information the
    assertion does not carry — what the message SHOULD say, or which type is meant."""
    assert _msg('assert "boom" in str(e)')[0].auto_loosenable is False
    assert _type('assert "X" in str(type(e))')[0].auto_loosenable is False


def test_ordinary_membership_is_not_an_exception_pin() -> None:
    """One-sided by construction. A substring check against ordinary data is a normal assertion and
    must not be dragged in — that is how a recall improvement quietly becomes a precision loss."""
    assert _msg('assert "alice" in names') == []
    assert _msg('assert "alice" in str(user)') == []
    assert _msg('assert "alice" in response.text') == []


def test_an_absence_assertion_is_not_flagged() -> None:
    """`not in` is not `ast.In`; the existing checks rely on the same distinction."""
    assert _msg('assert "boom" not in str(e)') == []
    assert _type('assert "X" not in str(type(e))') == []


def test_isinstance_is_the_thing_being_recommended_and_is_never_flagged() -> None:
    assert _type("assert isinstance(exc_info.value, ConfigError)") == []
    assert _msg("assert isinstance(exc_info.value, ConfigError)") == []
