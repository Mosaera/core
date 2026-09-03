"""An assertion that no implementation can satisfy is not strict — it is impossible.

Measured on the 0.6.3 sweep (docs/engineering-history/over-park-anatomy-2026-08-30.md): the Proctor
lower-cased a page's source and searched it for a literal containing capitals, refusing a tree the
hidden grader passed 100%.

The property under test is a THEOREM, not a heuristic — `s.lower()` contains no uppercase character
— so the tests that matter most are the negatives: this may never fire on a satisfiable assertion.
"""

from __future__ import annotations

import ast

import pytest
from mosaera_core.bar_integrity import check_case_impossible


def _findings(src: str, spec: str = ""):
    node = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Assert))
    return check_case_impossible(node, "tests/test_x.py", spec)


# --- the real defect ------------------------------------------------------------------------


def test_the_MCB_02_assertion_that_refused_correct_work() -> None:
    """Verbatim from the sweep."""
    got = _findings('assert "<!DOCTYPE html>" in content.lower(), "HTML must have proper DOCTYPE"')
    assert len(got) == 1
    assert got[0].kind == "case_impossible"
    assert "never hold" in got[0].suggestion


@pytest.mark.parametrize(
    "src",
    [
        'assert "ERROR" in out.lower()',
        'assert out.lower() == "Hello"',
        'assert "abc" in out.upper()',
        'assert out.casefold() == "Mixed"',
        'assert "Test" in text.casefold()',
    ],
)
def test_impossible_comparisons_fire(src: str) -> None:
    assert _findings(src), f"{src} can never hold and must be flagged"


# --- the negatives, which are the ones that keep this honest ---------------------------------


@pytest.mark.parametrize(
    "src",
    [
        'assert "error" in out.lower()',  # all lowercase against .lower() — satisfiable
        'assert "ERROR" in out.upper()',  # all uppercase against .upper() — satisfiable
        'assert "404" in out.lower()',  # no cased characters at all
        'assert "!!" in out.upper()',  # punctuation only
        'assert "ERROR" in out',  # no fold applied
        'assert "ERROR" in out.strip()',  # a different method entirely
        'assert "ERROR" in out.lower(1)',  # not the no-arg fold
        "assert x.lower() == y.lower()",  # no literal
        'assert "A" < out.lower()',  # not an In/Eq comparison
        'assert "a" in out.lower() and "B" in out',  # BoolOp, not a bare Compare
    ],
)
def test_satisfiable_assertions_are_NEVER_flagged(src: str) -> None:
    """A false positive here would refuse correct tests — the exact harm being fixed, inverted."""
    assert _findings(src) == [], f"{src} is satisfiable and must not be flagged"


def test_a_quoted_spec_literal_does_not_excuse_impossibility() -> None:
    """The other checks stand down when the task quotes the literal, because a quoted literal IS
    the contract. That reasoning does not transfer: quoting cannot make a comparison satisfiable,
    and staying silent here would leave an unmeetable bar in place because the task named it."""
    got = _findings('assert "DOCTYPE" in html.lower()', spec="the page must contain DOCTYPE")
    assert got, "an impossible comparison stays impossible however the task words it"


def test_it_never_claims_the_finding_is_auto_fixable() -> None:
    """ADR-0062: knowing an assertion cannot hold does not reveal what it MEANT. Folding both sides
    and dropping the fold are different contracts, and choosing is the Proctor's judgement."""
    assert _findings('assert "ERROR" in out.lower()')[0].auto_loosenable is False


def test_the_check_is_actually_WIRED_into_the_pipeline(tmp_path) -> None:
    """The no-caller defence. A detector nothing calls is a detector that measures nothing, and
    this repo has shipped that shape before — so pin the real entry point, not just the function.
    """
    from types import SimpleNamespace

    from mosaera_core.faithfulness import authored_suite_overstrict_findings

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_page.py").write_text(
        "def test_doctype():\n"
        '    content = open("index.html").read()\n'
        '    assert "<!DOCTYPE html>" in content.lower()\n',
        encoding="utf-8",
    )
    got = authored_suite_overstrict_findings(
        SimpleNamespace(root=tmp_path),  # type: ignore[arg-type]
        ["tests/test_page.py"],
        "build a landing page",
    )
    assert "case_impossible" in {f.kind for f in got}
