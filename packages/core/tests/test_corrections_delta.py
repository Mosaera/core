"""The add-reducer guard: only the DELTA may be returned into RunState."""

from mosaera_core.agents_bridge import _tester_input, new_corrections


def test_delta_excludes_what_was_carried_in() -> None:
    carried = ["rule A"]
    result = {"corrections": ["rule A", "rule B"]}
    assert new_corrections(result, carried) == ["rule B"]


def test_delta_dedupes_within_one_invocation() -> None:
    # Two identical denials in one turn must not add the same standing rule twice.
    assert new_corrections({"corrections": ["rule B", "rule B"]}, []) == ["rule B"]


def test_delta_is_empty_when_nothing_new() -> None:
    assert new_corrections({"corrections": ["rule A"]}, ["rule A"]) == []
    assert new_corrections({}, ["rule A"]) == []
    assert new_corrections(None, []) == []


def test_tester_input_omits_the_key_when_there_is_nothing_to_carry() -> None:
    # A run with no corrections must send the payload it always sent.
    assert _tester_input("go", ()) == {"messages": [_tester_input("go", ())["messages"][0]]}
    assert "corrections" not in _tester_input("go", ())
    assert _tester_input("go", ["r"])["corrections"] == ["r"]
