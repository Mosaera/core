"""A test that pins a value it never supplied (F36).

Reconstructed from run `20260806-074310-721ec9`, where the Proctor authored an assertion that could
never pass and it cost ~256k tokens and eleven gates to find out.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from mosaera_core.roundtrip import unsupplied_roundtrip_findings

# The real file, near enough verbatim: the CLI is invoked WITHOUT --date, so the row can never
# carry 2023-01-01. The header assertion beside it is legitimate and must NOT be flagged.
REAL = """
import subprocess, sys, tempfile, unittest

class TestCliAdd(unittest.TestCase):
    def test_cli_add_writes_row(self):
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as f:
            temp_file = f.name
        result = subprocess.run([
            sys.executable, '-m', 'budget_tracker.cli', 'add', '12.34', 'food',
            '--note=Lunch', '--file', temp_file
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        with open(temp_file, 'r') as f:
            content = f.read()
        self.assertIn('date,amount,category,note', content)
        self.assertIn('2023-01-01,12.34,food,"Lunch"', content)
"""


def _ws(tmp_path: Path, body: str, name: str = "tests/test_x.py") -> Any:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return SimpleNamespace(root=tmp_path)


def test_the_real_case_is_flagged_and_names_the_unsupplied_value(tmp_path: Path) -> None:
    findings = unsupplied_roundtrip_findings(_ws(tmp_path, REAL), ["tests/test_x.py"], "spec text")
    assert len(findings) == 1, [f.snippet for f in findings]
    f = findings[0]
    assert f.kind == "unsupplied_value"
    # Naming the value is the point — "this test is strict" would not tell the operator what to do.
    assert "'2023-01-01'" in f.suggestion
    assert f.auto_loosenable is False  # ADR-0062: never a mechanical rewrite


def test_the_header_assertion_in_the_same_file_stays_silent(tmp_path: Path) -> None:
    # `note` IS a substring of the supplied `--note=Lunch`, so a single-match rule would flag this
    # perfectly good assertion. One of four components is not round-trip evidence.
    findings = unsupplied_roundtrip_findings(_ws(tmp_path, REAL), ["tests/test_x.py"], "spec text")
    assert all("date,amount,category,note" not in f.snippet for f in findings)


def test_a_fully_supplied_round_trip_is_silent(tmp_path: Path) -> None:
    body = """
import subprocess, unittest

class TestX(unittest.TestCase):
    def test_ok(self):
        subprocess.run(['cli', 'add', '12.34', 'food', '--date=2023-01-01'])
        self.assertIn('2023-01-01,12.34,food', open('f').read())
"""
    assert unsupplied_roundtrip_findings(_ws(tmp_path, body), ["tests/test_x.py"], "") == []


def test_a_spec_pinned_value_is_faithful(tmp_path: Path) -> None:
    # The spec fixing the date makes it the contract, not an invention — same rule the sibling
    # module applies to a spec-quoted literal.
    spec = "the row must read 2023-01-01,12.34,food"
    assert unsupplied_roundtrip_findings(_ws(tmp_path, REAL), ["tests/test_x.py"], spec) == []


def test_a_single_component_is_not_a_round_trip(tmp_path: Path) -> None:
    body = """
import subprocess, unittest

class TestX(unittest.TestCase):
    def test_ok(self):
        subprocess.run(['cli', 'add', 'food'])
        self.assertIn('somethingelse', open('f').read())
"""
    assert unsupplied_roundtrip_findings(_ws(tmp_path, body), ["tests/test_x.py"], "") == []


def test_skipped_tests_and_unparseable_files_yield_nothing(tmp_path: Path) -> None:
    skipped = "import pytest, subprocess\n" + REAL.replace(
        "    def test_cli_add_writes_row(self):",
        "    @pytest.mark.skip\n    def test_cli_add_writes_row(self):",
    )
    assert unsupplied_roundtrip_findings(_ws(tmp_path, skipped), ["tests/test_x.py"], "") == []
    assert unsupplied_roundtrip_findings(_ws(tmp_path, "def ("), ["tests/test_x.py"], "") == []
    assert unsupplied_roundtrip_findings(_ws(tmp_path, REAL), ["tests/missing.py"], "") == []


# --- One-sidedness on real third-party `unittest` code ---------------------------------------
#
# These three narrowings came from the FIRST honest false-positive measurement this detector ever
# had: `regex/tests/test_regex.py` (4540 lines, 102 test functions). It had never been scanned —
# its class is `RegexTests`, and class collection required a `Test*` PREFIX — so the earlier
# "zero findings" verified nothing. Once collected it produced 19 findings, every one a false
# positive. 19 -> 6 -> 3 -> 1 across the three fixes below.


def test_a_literal_fed_to_a_nested_call_is_an_input_not_an_assertion(tmp_path: Path) -> None:
    # `self.assertEqual(regex.match(pat, 'c a ts').fuzzy_counts, (0, 2, 0))` — the asserted value is
    # the tuple; 'c a ts' is what the test FED the matcher. Walking into it read an input as an
    # unsupplied pin.
    body = """
import re, unittest

class MatcherTests(unittest.TestCase):
    def test_fuzzy(self):
        pattern = 'cats'
        self.assertEqual(re.match(pattern, 'c a ts').span(), (0, 2))
"""
    ws = _ws(tmp_path, body)
    assert unsupplied_roundtrip_findings(ws, ["tests/test_x.py"], "") == []


def test_an_input_inside_the_assertion_still_counts_as_supplied(tmp_path: Path) -> None:
    # `assertEqual(search(pat, 'A B CYZ').group(), 'A B CYZ')` — the test plainly supplied the
    # value; excluding the whole assertion from `supplied` hid that and read it as unsupplied.
    body = """
import re, unittest

class SearchTests(unittest.TestCase):
    def test_group(self):
        self.assertEqual(re.search('A.*B.*C', 'A B CYZ').group(), 'A B CYZ')
"""
    ws = _ws(tmp_path, body)
    assert unsupplied_roundtrip_findings(ws, ["tests/test_x.py"], "") == []


def test_a_single_character_component_is_not_roundtrip_evidence(tmp_path: Path) -> None:
    # `pattern.sub('#', 'a\\nb\\n') == 'a\\nb#\\n#'` asserts a TRANSFORMATION. One-character
    # components substring-match almost anything, manufacturing the majority and flagging the
    # transformed fragment as unsupplied.
    body = """
import re, unittest

class SubTests(unittest.TestCase):
    def test_dollar_matches_twice(self):
        pattern = re.compile('$', re.M)
        self.assertEqual(pattern.sub('#', 'a\\nb\\n'), 'a\\nb#\\n#')
"""
    ws = _ws(tmp_path, body)
    assert unsupplied_roundtrip_findings(ws, ["tests/test_x.py"], "") == []


def test_the_real_specimen_is_still_caught_after_all_three_narrowings(tmp_path: Path) -> None:
    # The whole point: one-sidedness must not cost the detection the module exists for.
    ws = _ws(tmp_path, REAL)
    findings = unsupplied_roundtrip_findings(ws, ["tests/test_x.py"], "")
    assert len(findings) == 1
    assert "2023-01-01" in findings[0].snippet


# --- F46: an assertion's MESSAGE is prose, not an asserted value. ---------------------------
#
# Found live on run 20260806-154604-229044 — a regression from the narrowing above. Moving
# `'pyproject.toml'` from ASSERTED to SUPPLIED (it sits behind a call) left the message as the only
# asserted literal, and it carried enough supplied components to clear the majority rule. Three
# false findings, all of this shape. The regex corpus could not have caught it: it barely uses the
# `assert cond, "message"` form.


def test_an_assert_message_and_a_docstring_are_prose_not_values(tmp_path: Path) -> None:
    """The exact file from run 20260806-154604-229044, which produced three false findings.

    Two prose sources conspired. The MESSAGE became the only asserted literal (the path sits behind
    `os.path.exists(...)`, so the narrowing above moved it to SUPPLIED), and the DOCSTRING was
    counted as a supplied input — 5 of the message's 6 components substring-match it ("exist" in
    "exists", "in", "repo", "root", "pyproject.toml"), clearing the majority rule and leaving
    'must' as the pinned-but-unsupplied component. Neither string is a value the test supplies or
    asserts; both are English.
    """
    body = '''
"""
Tests to verify project structure matches acceptance criteria.
"""
import os

def test_pyproject_toml_exists_and_has_no_runtime_deps():
    """Test that pyproject.toml exists in the repo root and declares zero runtime dependencies."""
    assert os.path.exists(\'pyproject.toml\'), "pyproject.toml must exist in repo root"
    with open(\'pyproject.toml\') as f:
        content = f.read()
    assert \'[project]\' in content
    assert \'dependencies = []\' in content

def test_src_budget_tracker_init_exists():
    """Test that src/budget_tracker/__init__.py is present."""
    p = \'src/budget_tracker/__init__.py\'
    assert os.path.exists(p), "src/budget_tracker/__init__.py must exist"
'''
    ws = _ws(tmp_path, body)
    assert unsupplied_roundtrip_findings(ws, ["tests/test_x.py"], "") == []


def test_an_assert_message_is_not_an_asserted_value(tmp_path: Path) -> None:
    body = """
import os, unittest

class StructureTests(unittest.TestCase):
    def test_layout(self):
        target = 'pyproject.toml'
        assert os.path.exists(target), "pyproject.toml must exist in repo root"
        other = 'src/budget_tracker/storage.py'
        assert os.path.exists(other), "src/budget_tracker/storage.py must exist"
"""
    ws = _ws(tmp_path, body)
    assert unsupplied_roundtrip_findings(ws, ["tests/test_x.py"], "") == []


def test_a_unittest_trailing_message_argument_is_not_an_asserted_value(tmp_path: Path) -> None:
    # `assertEqual(a, b, msg)` — unittest puts the message LAST, and it is prose.
    body = """
import unittest

class RowTests(unittest.TestCase):
    def test_row(self):
        row = build('12.34', 'food')
        self.assertEqual(row, '12.34,food', 'the row must contain amount and category')
"""
    ws = _ws(tmp_path, body)
    assert unsupplied_roundtrip_findings(ws, ["tests/test_x.py"], "") == []


def test_the_real_specimen_survives_the_message_exclusion(tmp_path: Path) -> None:
    ws = _ws(tmp_path, REAL)
    findings = unsupplied_roundtrip_findings(ws, ["tests/test_x.py"], "")
    assert len(findings) == 1
    assert "2023-01-01" in findings[0].snippet
