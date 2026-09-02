"""The authored-suite assertion digest (#129 slice 3 enabler).

Its whole purpose is to make the assertions the DETECTOR MISSED analysable later, so the tests that
matter most are the ones about not losing information: unparseable is not "nothing", helpers are not
tests, and the caps are honest about truncating.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from mosaera_core.assertion_digest import assertion_snippets, suite_assertion_digest

_SUITE = """
def helper():
    assert 1 == 1


def test_exact_output():
    assert render(rows) == "a,b\\nc,d\\n"


class TestGroup:
    def test_range(self):
        assert 0 < score(x) <= 100
"""


def test_it_records_what_is_asserted_not_how_much() -> None:
    """The reason this exists rather than reusing `assertion_profile`: over-strictness is about
    WHAT is asserted. An exact-output equality and a behavioural range check are both '1' to a
    counter, and they are the two cases the detector most needs to tell apart."""
    got = assertion_snippets(_SUITE)
    assert got is not None
    joined = "\n".join(got)
    assert "test_exact_output" in joined
    assert 'render(rows) == "a,b\\nc,d\\n"' in joined, "the exact-output pin must be recoverable"
    assert "TestGroup::test_range" in joined, "class-nested tests must keep their qualname"
    assert "0 < score(x) <= 100" in joined


def test_a_helper_is_not_a_test() -> None:
    """`authored_suite_asserts_behaviour` applies the same rule: an assert in an uncalled helper is
    not the suite asserting anything. The digest must not imply otherwise."""
    got = assertion_snippets(_SUITE)
    assert got is not None
    assert not any(s.startswith("helper") for s in got)


def test_unparseable_is_UNKNOWN_not_empty() -> None:
    """The contract `assertion_profile` holds, for the same reason: a caller that reads None as
    'asserts nothing' turns a syntax error into evidence."""
    assert assertion_snippets("def broken(:\n") is None


def test_the_suite_digest_marks_what_it_could_not_read(tmp_path: Path) -> None:
    """'We could not look' and 'there was nothing' are different facts, and collapsing them is the
    defect this repo keeps re-measuring. A file that cannot be read or parsed leaves a MARKER."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text(
        "def test_x():\n    assert f() == 1\n", encoding="utf-8"
    )
    (tmp_path / "tests" / "test_bad.py").write_text("def test_y(:\n", encoding="utf-8")
    ws: Any = SimpleNamespace(root=tmp_path)

    digest = suite_assertion_digest(ws, ["tests/test_ok.py", "tests/test_bad.py", "tests/gone.py"])
    joined = "\n".join(digest)
    assert "tests/test_ok.py::test_x :: assert f() == 1" in joined
    assert "tests/test_bad.py :: <unparseable>" in joined
    assert "tests/gone.py :: <unreadable>" in joined


def test_no_authored_files_yields_an_empty_digest(tmp_path: Path) -> None:
    ws: Any = SimpleNamespace(root=tmp_path)
    assert suite_assertion_digest(ws, []) == []
