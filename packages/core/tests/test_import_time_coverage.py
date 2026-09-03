"""Structurally-uncoverable lines must not read as untested (#128).

`dynamic_context = test_function` records a context only while a test runs, and `parse_contexts`
counts a line covered ONLY under a non-empty context. A module-scope statement runs at IMPORT time,
so it can never appear in `covered_lines` — no suite, however thorough, can cover it.

Measured before this: the gate CREDITED a comment change (not executable, so the check passed
trivially) and REFUSED a `__version__` bump the standing suite genuinely verified — reviewer
APPROVE, critic 3/3, grader 2/2, parked anyway.

The tests that matter most are the ones proving this did NOT become a widening.
"""

from __future__ import annotations

from mosaera_core.coveragemap import CoverageMap, change_is_covered, import_time_lines

_SRC = '''"""A module."""

import os

VERSION = "1.4.0"


def render(rows):
    total = 0
    for r in rows:
        total += r
    return total


class Report:
    LABEL = "report"

    def emit(self):
        return VERSION
'''


def _lineno(needle: str) -> int:
    return next(i for i, line in enumerate(_SRC.splitlines(), 1) if needle in line)


def test_module_scope_statements_are_import_time() -> None:
    got = import_time_lines(_SRC)
    assert got is not None
    for needle in ('VERSION = "1.4.0"', "import os", "def render", "class Report"):
        assert _lineno(needle) in got, f"{needle!r} runs at import and must be listed"


def test_a_class_BODY_is_import_time_too() -> None:
    """A class body executes when the module is imported, so it is as uncoverable as a module-level
    assignment. Missing this would leave every dataclass field default still broken."""
    got = import_time_lines(_SRC)
    assert got is not None
    assert _lineno('LABEL = "report"') in got


def test_a_function_BODY_is_NOT_import_time() -> None:
    """The load-bearing exclusion. Function bodies are exactly what a test context can cover, so
    they must stay judgeable — otherwise this fix would excuse everything."""
    got = import_time_lines(_SRC)
    assert got is not None
    for needle in ("total = 0", "for r in rows", "total += r", "return VERSION"):
        assert _lineno(needle) not in got, f"{needle!r} is a function body and must stay judged"


def test_unparseable_is_UNKNOWN_not_empty() -> None:
    """A syntax error must not read as 'no import-time lines' — that would silently re-enable the
    defect on exactly the files least able to defend themselves."""
    assert import_time_lines("def broken(:\n") is None


def test_a_version_bump_no_longer_reads_as_untested() -> None:
    """THE DEFECT. The changed line is executable and import-time, so no test can cover it. The
    verdict must be None ("coverage has no opinion"), which hands the decision to the caller's
    import heuristic — NOT True, which would credit it outright."""
    cov = CoverageMap()
    cov.executable_lines["ledger.py"] = {3, 6, 9}
    cov.import_time_lines["ledger.py"] = {3}
    cov.covered_lines["ledger.py"] = {6, 9}
    assert change_is_covered(cov, {"ledger.py": {3}}) is None


def test_an_uncovered_FUNCTION_line_still_denies() -> None:
    """Deny-by-default, intact. This is the case the coverage gate exists for and the fix must not
    touch it."""
    cov = CoverageMap()
    cov.executable_lines["ledger.py"] = {3, 6, 9}
    cov.import_time_lines["ledger.py"] = {3}
    cov.covered_lines["ledger.py"] = {6}
    assert change_is_covered(cov, {"ledger.py": {9}}) is False


def test_a_mixed_change_is_judged_on_its_COVERABLE_lines() -> None:
    """A change touching both a constant and a function body is still judged on the body. The
    exclusion narrows what is asked about; it never excuses the rest of the diff."""
    cov = CoverageMap()
    cov.executable_lines["ledger.py"] = {3, 6, 9}
    cov.import_time_lines["ledger.py"] = {3}
    cov.covered_lines["ledger.py"] = {6}
    assert change_is_covered(cov, {"ledger.py": {3, 6}}) is True
    assert change_is_covered(cov, {"ledger.py": {3, 9}}) is False


def test_an_UNMEASURED_file_still_denies() -> None:
    """A changed file no test imports has no executable_lines at all — the F1 case coverage exists
    to catch. Unchanged by this fix."""
    cov = CoverageMap()
    assert change_is_covered(cov, {"ledger.py": {3}}) is False


def test_absent_import_time_info_falls_back_to_judging_EVERY_line() -> None:
    """If the source could not be parsed, the map has no entry and the old, strict behaviour must
    apply — unknown must cost the change its credit, not grant it."""
    cov = CoverageMap()
    cov.executable_lines["ledger.py"] = {3}
    cov.covered_lines["ledger.py"] = set()
    assert change_is_covered(cov, {"ledger.py": {3}}) is False
