"""Over-strictness / faithfulness detector (#57, ADR-0062).

Deterministic AST detection of authored acceptance-test assertions that pin incidental detail the
spec leaves open. One-sided: it must FLAG the instrumented traps (exact stdout whitespace, a
rendering-literal count, an exit-code pin, a private-name pin, an unsatisfiable contradiction) and
must NOT flag faithful assertions (a behavioural value equality, a spec-pinned literal, raises).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from mosaera_core.faithfulness import authored_suite_overstrict_findings


def _ws(tmp_path: Any) -> Any:
    return SimpleNamespace(root=tmp_path)


def _write(tmp_path: Any, name: str, body: str) -> str:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return name


def _kinds(findings: list[Any]) -> set[str]:
    return {f.kind for f in findings}


# --- FLAGGED: the confirmed over-strict traps ---------------------------------


def test_exact_stdout_line_equality_is_flagged(tmp_path: Any) -> None:
    # MCB-01: `assert lines[0] == "1 [ ] Buy milk"` pins whitespace the spec left open.
    rel = _write(
        tmp_path,
        "tests/test_cli.py",
        "def test_list(result):\n"
        '    lines = result.stdout.strip().split("\\n")\n'
        '    assert lines[0] == "1 [ ] Buy milk"\n',
    )
    findings = authored_suite_overstrict_findings(_ws(tmp_path), [rel], spec_text="list the tasks")
    assert "exact_output_equality" in _kinds(findings)
    assert findings[0].auto_loosenable is True


def test_rendering_count_literal_is_flagged(tmp_path: Any) -> None:
    # MCB-21: `assert stdout.count("#important") == 1` pins the `#` rendering.
    rel = _write(
        tmp_path,
        "tests/test_tag.py",
        'def test_no_dup(result):\n    assert result.stdout.count("#important") == 1\n',
    )
    findings = authored_suite_overstrict_findings(
        _ws(tmp_path), [rel], spec_text="tagging must not duplicate a tag"
    )
    assert "output_count_pin" in _kinds(findings)
    assert all(not f.auto_loosenable for f in findings if f.kind == "output_count_pin")


def test_exit_code_pin_against_nonzero_spec_is_flagged(tmp_path: Any) -> None:
    rel = _write(
        tmp_path,
        "tests/test_err.py",
        "def test_unknown(result):\n    assert result.returncode == 2\n",
    )
    findings = authored_suite_overstrict_findings(
        _ws(tmp_path), [rel], spec_text="an unknown command exits with a non-zero status"
    )
    assert "exit_code_pin" in _kinds(findings)
    assert findings[0].auto_loosenable is True


def test_contradiction_pair_is_flagged(tmp_path: Any) -> None:
    # MCB-14: pin the private name in source AND require it not be exported → unsatisfiable.
    rel = _write(
        tmp_path,
        "tests/test_refactor.py",
        "import inspect\n"
        "import pytest\n"
        "import accounts\n"
        "def test_extracted():\n"
        "    source = inspect.getsource(accounts.create_user)\n"
        '    assert "_validate_user" in source\n'
        "def test_not_exported():\n"
        "    with pytest.raises(AttributeError):\n"
        "        accounts._validate_user\n",
    )
    findings = authored_suite_overstrict_findings(
        _ws(tmp_path), [rel], spec_text="extract the validation into one helper"
    )
    assert "contradiction" in _kinds(findings)


def test_source_introspection_name_pin_is_flagged(tmp_path: Any) -> None:
    # MCB-05 (#60, ADR-0066): pinning a specific PRIVATE helper NAME in the module source for a
    # loosely-worded "decompose into helpers" requirement — a correct, differently-named refactor
    # fails it. Flagged as source_introspection (NOT a contradiction — no raises pairing here).
    rel = _write(
        tmp_path,
        "tests/test_refactor.py",
        "import inspect\n"
        "import checkout\n"
        "def test_decomposed():\n"
        "    src = inspect.getsource(checkout)\n"
        '    assert "_apply_discount" in src\n',
    )
    findings = authored_suite_overstrict_findings(
        _ws(tmp_path), [rel], spec_text="refactor into a short orchestrator delegating to helpers"
    )
    assert "source_introspection" in _kinds(findings)


def test_hasattr_private_name_pin_is_flagged(tmp_path: Any) -> None:
    # `assert hasattr(mod, "_helper")` pins a private symbol name the task didn't name.
    rel = _write(
        tmp_path,
        "tests/test_refactor.py",
        'import checkout\ndef test_helper():\n    assert hasattr(checkout, "_compute_tax")\n',
    )
    findings = authored_suite_overstrict_findings(
        _ws(tmp_path), [rel], spec_text="decompose into module-level helpers"
    )
    assert "source_introspection" in _kinds(findings)


# --- NOT FLAGGED: faithful assertions (false-positive guards) -----------------


def test_behavioural_value_equality_is_not_flagged(tmp_path: Any) -> None:
    # A domain value (not captured output) compared to a dict/str is behavioural — never flagged.
    rel = _write(
        tmp_path,
        "tests/test_acc.py",
        "def test_record():\n"
        '    assert create_user("alice", 30) == {"action": "create", "name": "alice", "age": 30}\n'
        "def test_name():\n"
        '    assert entry.text == "buy milk"\n',
    )
    assert authored_suite_overstrict_findings(_ws(tmp_path), [rel], spec_text="") == []


def test_spec_pinned_literal_is_not_flagged(tmp_path: Any) -> None:
    # When the spec QUOTES the exact line, pinning it is faithful, not over-strict.
    rel = _write(
        tmp_path,
        "tests/test_cli.py",
        'def test_list(result):\n    assert result.stdout.strip() == "1 [ ] Buy milk"\n',
    )
    spec = 'the list prints exactly "1 [ ] Buy milk" for a single undone task'
    assert authored_suite_overstrict_findings(_ws(tmp_path), [rel], spec_text=spec) == []


def test_spec_named_private_helper_is_not_flagged(tmp_path: Any) -> None:
    # When the SPEC names the exact helper, pinning it is faithful (#60, ADR-0066).
    rel = _write(
        tmp_path,
        "tests/test_refactor.py",
        "import inspect, checkout\n"
        "def test_named():\n"
        "    src = inspect.getsource(checkout)\n"
        '    assert "_apply_member_discount" in src\n'
        "def test_attr():\n"
        '    assert hasattr(checkout, "_apply_member_discount")\n',
    )
    spec = "extract a helper named _apply_member_discount"
    assert authored_suite_overstrict_findings(_ws(tmp_path), [rel], spec_text=spec) == []


def test_hasattr_public_name_is_not_flagged(tmp_path: Any) -> None:
    # Only PRIVATE (leading-underscore) names are implementation-shape pins; a public API name is
    # part of the contract — never flagged.
    rel = _write(
        tmp_path,
        "tests/test_api.py",
        'import checkout\ndef test_public():\n    assert hasattr(checkout, "checkout_total")\n',
    )
    assert authored_suite_overstrict_findings(_ws(tmp_path), [rel], spec_text="") == []


def test_nonzero_exit_check_is_not_flagged(tmp_path: Any) -> None:
    # `!= 0` already matches the spec's strictness — nothing to loosen.
    rel = _write(
        tmp_path,
        "tests/test_err.py",
        "def test_unknown(result):\n    assert result.returncode != 0\n",
    )
    assert (
        authored_suite_overstrict_findings(_ws(tmp_path), [rel], spec_text="exits non-zero") == []
    )


def test_exit_pin_without_nonzero_spec_is_not_flagged(tmp_path: Any) -> None:
    # If the spec pins the exact code, `== 2` is faithful.
    rel = _write(
        tmp_path,
        "tests/test_err.py",
        "def test_bad(result):\n    assert result.returncode == 2\n",
    )
    spec = "on a usage error the tool exits with code 2"
    assert authored_suite_overstrict_findings(_ws(tmp_path), [rel], spec_text=spec) == []


def test_empty_and_id_equality_is_not_flagged(tmp_path: Any) -> None:
    # `== ""` (print nothing) and `== "3"` (an id) are not rendered lines → not over-strict.
    rel = _write(
        tmp_path,
        "tests/test_cli.py",
        "def test_blank(result):\n"
        '    assert result.stdout.strip() == ""\n'
        "def test_id(result):\n"
        '    assert result.stdout.strip() == "3"\n',
    )
    assert authored_suite_overstrict_findings(_ws(tmp_path), [rel], spec_text="") == []


def test_skipped_test_is_ignored(tmp_path: Any) -> None:
    rel = _write(
        tmp_path,
        "tests/test_cli.py",
        "import pytest\n"
        "@pytest.mark.skip\n"
        "def test_list(result):\n"
        '    assert result.stdout.strip().split("\\n")[0] == "1 [ ] Buy milk"\n',
    )
    assert authored_suite_overstrict_findings(_ws(tmp_path), [rel], spec_text="") == []


def test_no_authored_tests_is_empty(tmp_path: Any) -> None:
    assert authored_suite_overstrict_findings(_ws(tmp_path), [], spec_text="anything") == []


# --- F37: the same verdicts through `unittest` assertions -----------------------------------
#
# The detector walked `ast.Assert` only, so `self.assertEqual(...)` / `self.assertIn(...)` were
# invisible. LedgerCLI's charter mandates `unittest`, which made the guard find NOTHING on every
# suite this product actually authors. Measured on the MCB corpus: all 42 bench test files are
# bare-`assert`, which is why the blindness survived its own justification measurements.
#
# Each test below is the `unittest` twin of a bare-`assert` case above and must reach the SAME
# verdict — that pairing is the point, not the individual assertions.


def test_unittest_exact_output_equality_is_flagged(tmp_path: Any) -> None:
    rel = _write(
        tmp_path,
        "tests/test_cli.py",
        "import unittest\n"
        "class TestList(unittest.TestCase):\n"
        "    def test_list(self):\n"
        '        lines = self.result.stdout.strip().split("\\n")\n'
        '        self.assertEqual(lines[0], "1 [ ] Buy milk")\n',
    )
    findings = authored_suite_overstrict_findings(_ws(tmp_path), [rel], spec_text="list the tasks")
    assert "exact_output_equality" in _kinds(findings)


def test_unittest_exit_code_pin_is_flagged(tmp_path: Any) -> None:
    rel = _write(
        tmp_path,
        "tests/test_err.py",
        "import unittest\n"
        "class TestErr(unittest.TestCase):\n"
        "    def test_unknown(self):\n"
        "        self.assertEqual(self.result.returncode, 2)\n",
    )
    findings = authored_suite_overstrict_findings(
        _ws(tmp_path), [rel], spec_text="an unknown command exits with a non-zero status"
    )
    assert "exit_code_pin" in _kinds(findings)


def test_unittest_rendering_count_pin_is_flagged(tmp_path: Any) -> None:
    rel = _write(
        tmp_path,
        "tests/test_tag.py",
        "import unittest\n"
        "class TestTag(unittest.TestCase):\n"
        "    def test_no_dup(self):\n"
        '        self.assertEqual(self.result.stdout.count("#important"), 1)\n',
    )
    findings = authored_suite_overstrict_findings(
        _ws(tmp_path), [rel], spec_text="tagging must not duplicate a tag"
    )
    assert "output_count_pin" in _kinds(findings)


def test_unittest_source_membership_name_pin_is_flagged(tmp_path: Any) -> None:
    # `self.assertIn("_x", src)` — the `in` form, normalised to a Compare so the present-set path
    # sees it exactly as it sees `assert "_x" in src`.
    rel = _write(
        tmp_path,
        "tests/test_refactor.py",
        "import inspect\n"
        "import unittest\n"
        "import checkout\n"
        "class TestRefactor(unittest.TestCase):\n"
        "    def test_decomposed(self):\n"
        "        src = inspect.getsource(checkout)\n"
        '        self.assertIn("_apply_discount", src)\n',
    )
    findings = authored_suite_overstrict_findings(
        _ws(tmp_path), [rel], spec_text="decompose checkout into helpers"
    )
    assert "source_introspection" in _kinds(findings)


def test_unittest_hasattr_private_name_pin_is_flagged(tmp_path: Any) -> None:
    # `assertTrue(expr)` normalises to the bare expression, so the hasattr check is reachable.
    rel = _write(
        tmp_path,
        "tests/test_shape.py",
        "import unittest\n"
        "import accounts\n"
        "class TestShape(unittest.TestCase):\n"
        "    def test_helper(self):\n"
        '        self.assertTrue(hasattr(accounts, "_validate_user"))\n',
    )
    findings = authored_suite_overstrict_findings(
        _ws(tmp_path), [rel], spec_text="extract the validation into one helper"
    )
    assert "source_introspection" in _kinds(findings)


def test_unittest_contradiction_pair_is_flagged(tmp_path: Any) -> None:
    # The absent half already worked (`"raises" in "self.assertRaises"`); the PRESENT half is what
    # needed unittest support, so the pair only closes once both are seen.
    rel = _write(
        tmp_path,
        "tests/test_refactor.py",
        "import inspect\n"
        "import unittest\n"
        "import accounts\n"
        "class TestRefactor(unittest.TestCase):\n"
        "    def test_extracted(self):\n"
        "        source = inspect.getsource(accounts.create_user)\n"
        '        self.assertIn("_validate_user", source)\n'
        "    def test_not_exported(self):\n"
        "        with self.assertRaises(AttributeError):\n"
        "            accounts._validate_user\n",
    )
    findings = authored_suite_overstrict_findings(
        _ws(tmp_path), [rel], spec_text="extract the validation into one helper"
    )
    assert "contradiction" in _kinds(findings)


def test_unittest_behavioural_value_equality_is_not_flagged(tmp_path: Any) -> None:
    # A domain value, not captured output — the one-sidedness must survive normalisation.
    rel = _write(
        tmp_path,
        "tests/test_domain.py",
        "import unittest\n"
        "class TestDomain(unittest.TestCase):\n"
        "    def test_text(self):\n"
        '        self.assertEqual(entry.text, "Buy milk today")\n',
    )
    assert authored_suite_overstrict_findings(_ws(tmp_path), [rel], spec_text="") == []


def test_unittest_spec_pinned_literal_is_not_flagged(tmp_path: Any) -> None:
    rel = _write(
        tmp_path,
        "tests/test_cli.py",
        "import unittest\n"
        "class TestCli(unittest.TestCase):\n"
        "    def test_list(self):\n"
        '        self.assertEqual(self.result.stdout.strip(), "1 [ ] Buy milk")\n',
    )
    findings = authored_suite_overstrict_findings(
        _ws(tmp_path), [rel], spec_text='print each task as "1 [ ] Buy milk"'
    )
    assert findings == []


def test_unittest_absence_assertions_are_not_flagged(tmp_path: Any) -> None:
    # assertFalse / assertNotIn are ABSENCE assertions — the mirror of the existing
    # `assert not hasattr(...)` skip. Flagging them would invert their meaning.
    rel = _write(
        tmp_path,
        "tests/test_absent.py",
        "import inspect\n"
        "import unittest\n"
        "import checkout\n"
        "class TestAbsent(unittest.TestCase):\n"
        "    def test_no_private(self):\n"
        "        src = inspect.getsource(checkout)\n"
        '        self.assertNotIn("_apply_discount", src)\n'
        '        self.assertFalse(hasattr(checkout, "_helper"))\n',
    )
    assert authored_suite_overstrict_findings(_ws(tmp_path), [rel], spec_text="") == []


def test_unittest_public_name_hasattr_is_not_flagged(tmp_path: Any) -> None:
    rel = _write(
        tmp_path,
        "tests/test_shape.py",
        "import unittest\n"
        "import accounts\n"
        "class TestShape(unittest.TestCase):\n"
        "    def test_public(self):\n"
        '        self.assertTrue(hasattr(accounts, "create_user"))\n',
    )
    assert authored_suite_overstrict_findings(_ws(tmp_path), [rel], spec_text="") == []


def test_unittest_skipped_test_is_ignored(tmp_path: Any) -> None:
    rel = _write(
        tmp_path,
        "tests/test_cli.py",
        "import unittest\n"
        "class TestCli(unittest.TestCase):\n"
        "    @unittest.skip('wip')\n"
        "    def test_list(self):\n"
        '        self.assertEqual(self.result.stdout.strip(), "1 [ ] Buy milk")\n',
    )
    assert authored_suite_overstrict_findings(_ws(tmp_path), [rel], spec_text="") == []


def test_unittest_snippet_reports_the_source_the_operator_wrote(tmp_path: Any) -> None:
    # The finding is normalised internally to a comparison, but the operator must be shown the line
    # that is actually in their file — never a synthesised `a == b` they cannot search for.
    rel = _write(
        tmp_path,
        "tests/test_cli.py",
        "import unittest\n"
        "class TestList(unittest.TestCase):\n"
        "    def test_list(self):\n"
        '        self.assertEqual(self.result.stdout, "1 [ ] Buy milk")\n',
    )
    findings = authored_suite_overstrict_findings(_ws(tmp_path), [rel], spec_text="list the tasks")
    assert findings, "expected the over-strict assertion to be flagged"
    assert "assertEqual" in findings[0].snippet
    assert findings[0].line == 4


# --- Class collection: `unittest` does not name its classes `Test*` -------------------------
#
# Found reviewing !337. `test_functions` collected a class only when its name STARTED with `Test`,
# but `unittest` discovery collects any `TestCase` subclass and never looks at the name. F37's fix
# therefore worked on LedgerCLI by luck (its Proctor happened to write `TestStorage`); a suite named
# `StorageTests` was invisible to BOTH detectors. Measured against a real 4540-line `unittest`
# corpus (`regex/tests/test_regex.py`, class `RegexTests`): `test_functions` returned 1 function for
# the whole file, so the "zero findings" that verified F37 had scanned nothing.

_OVERSTRICT_BODY = (
    "    def test_output(self):\n"
    '        self.assertEqual(self.result.stdout.strip(), "1 [ ] Buy milk")\n'
)


def _overstrict_class(name: str, base: str = "unittest.TestCase") -> str:
    return f"import unittest\nclass {name}({base}):\n{_OVERSTRICT_BODY}"


def test_unittest_class_is_collected_whatever_it_is_named(tmp_path: Any) -> None:
    # The name is not the signal — the TestCase base is. All four must be scanned identically.
    for name in ("TestProbe", "ProbeTests", "ProbeTestCase", "StorageSuite"):
        rel = _write(tmp_path, f"tests/test_{name.lower()}.py", _overstrict_class(name))
        findings = authored_suite_overstrict_findings(
            _ws(tmp_path), [rel], spec_text="list the tasks"
        )
        assert "exact_output_equality" in _kinds(findings), f"{name} was not scanned"


def test_bare_testcase_base_is_collected(tmp_path: Any) -> None:
    # `from unittest import TestCase` — the base is unqualified, and still a TestCase.
    rel = _write(tmp_path, "tests/test_bare.py", _overstrict_class("Suite", base="TestCase"))
    findings = authored_suite_overstrict_findings(_ws(tmp_path), [rel], spec_text="list the tasks")
    assert "exact_output_equality" in _kinds(findings)


def test_a_non_test_helper_class_is_not_collected(tmp_path: Any) -> None:
    # The regression canary: the ONLY non-`Test*` class in all 42 MCB bench files is
    # `_Page(HTMLParser)` in MCB-02 — a parsing helper. Widening must not swallow it, or the
    # corpus findings change and the detector starts reading non-test code.
    rel = _write(
        tmp_path,
        "tests/test_page.py",
        "from html.parser import HTMLParser\n"
        "class _Page(HTMLParser):\n"
        "    def test_output(self):\n"
        '        self.assertEqual(self.result.stdout.strip(), "1 [ ] Buy milk")\n',
    )
    assert authored_suite_overstrict_findings(_ws(tmp_path), [rel], spec_text="") == []


# --- Bar integrity: a test that can never pass, or can never fail (ADR-0085 amendment) --------
#
# Both from live evidence on 2026-08-19/20. `source_formatting_pin`: the Proctor authored
# `assert "action='store_true'" in cli_content`, and `hygiene`'s `ruff format` rewrote the quotes
# it pinned, so item 107 shipped a tree failing its own suite (ADR-0106). `vacuous_test`: the
# Proctor twice authored a test that computed a value and asserted nothing.


def test_source_spelling_pin_is_flagged(tmp_path: Any) -> None:
    """The live item-107 bar, verbatim. `ruff format` rewrites the quotes it pins."""
    rel = _write(
        tmp_path,
        "tests/test_version.py",
        "from pathlib import Path\n\n\n"
        "def test_version_flag_not_hardcoded_in_cli():\n"
        '    cli_content = Path("src/budget_tracker/cli.py").read_text()\n'
        "    assert \"action='store_true'\" in cli_content\n",
    )
    findings = authored_suite_overstrict_findings(_ws(tmp_path), [rel], "add a --version flag")
    assert "source_formatting_pin" in _kinds(findings)
    assert all(not f.auto_loosenable for f in findings if f.kind == "source_formatting_pin")


def test_source_spelling_pin_through_unittest(tmp_path: Any) -> None:
    """F37: same verdict through `assertIn`; the snippet shows the line the operator wrote."""
    rel = _write(
        tmp_path,
        "tests/test_version_ut.py",
        "import unittest\nfrom pathlib import Path\n\n\n"
        "class T(unittest.TestCase):\n"
        "    def test_flag(self):\n"
        '        content = Path("src/cli.py").read_text()\n'
        "        self.assertIn(\"action='store_true'\", content)\n",
    )
    findings = authored_suite_overstrict_findings(_ws(tmp_path), [rel], "add a --version flag")
    pins = [f for f in findings if f.kind == "source_formatting_pin"]
    assert len(pins) == 1
    assert "assertIn" in pins[0].snippet


def test_absence_assertion_on_source_is_not_flagged(tmp_path: Any) -> None:
    """`assertNotIn` is an ABSENCE assertion — flagging it would invert its meaning."""
    rel = _write(
        tmp_path,
        "tests/test_absent.py",
        "import unittest\nfrom pathlib import Path\n\n\n"
        "class T(unittest.TestCase):\n"
        "    def test_flag(self):\n"
        '        content = Path("src/cli.py").read_text()\n'
        "        self.assertNotIn(\"version='1.0.0'\", content)\n",
    )
    assert authored_suite_overstrict_findings(_ws(tmp_path), [rel], "add a --version flag") == []


def test_spec_quoted_source_literal_is_not_flagged(tmp_path: Any) -> None:
    """A literal the task PINNED is faithful — the escape hatch every kind carries."""
    rel = _write(
        tmp_path,
        "tests/test_spec.py",
        "from pathlib import Path\n\n\n"
        "def test_flag():\n"
        '    cli_content = Path("src/cli.py").read_text()\n'
        "    assert \"action='store_true'\" in cli_content\n",
    )
    spec = "the parser must call add_argument with action='store_true'"
    assert authored_suite_overstrict_findings(_ws(tmp_path), [rel], spec) == []


def test_written_file_contents_are_not_flagged(tmp_path: Any) -> None:
    """Asserting on a `.py` file the CODE UNDER TEST wrote is behaviour, not a spelling pin.

    The path is composed from a fixture, so the detector cannot tell it from the module under
    test — and stays silent. This is the one-sidedness, and it is what keeps the product's own
    `write_file` tests quiet.
    """
    rel = _write(
        tmp_path,
        "tests/test_written.py",
        "def test_generator_writes_a_module(tmp_path):\n"
        "    generate(tmp_path)\n"
        '    assert "return \'hello\'" in (tmp_path / "hello.py").read_text()\n',
    )
    assert authored_suite_overstrict_findings(_ws(tmp_path), [rel], "generate a module") == []


def test_structural_assertion_over_ast_is_not_flagged(tmp_path: Any) -> None:
    """The form the persona PRESCRIBES instead — `ast` over the source — must stay silent."""
    rel = _write(
        tmp_path,
        "tests/test_structure.py",
        "import ast\nfrom pathlib import Path\n\n\n"
        "def test_has_helpers():\n"
        '    tree = ast.parse(Path("src/cli.py").read_text())\n'
        "    assert sum(isinstance(n, ast.FunctionDef) for n in ast.walk(tree)) >= 3\n",
    )
    assert authored_suite_overstrict_findings(_ws(tmp_path), [rel], "split cli into helpers") == []


def test_vacuous_test_is_flagged(tmp_path: Any) -> None:
    """The live rewrite: builds a list, appends to it, asserts nothing."""
    rel = _write(
        tmp_path,
        "tests/test_vacuous.py",
        "from pathlib import Path\n\n\n"
        "def test_version_is_not_hardcoded():\n"
        '    cli_content = Path("src/cli.py").read_text()\n'
        "    lines = []\n"
        "    for line in cli_content.splitlines():\n"
        '        if "version" in line:\n'
        "            lines.append(line)\n",
    )
    findings = authored_suite_overstrict_findings(_ws(tmp_path), [rel], "add a --version flag")
    assert "vacuous_test" in _kinds(findings)
    assert all(not f.auto_loosenable for f in findings if f.kind == "vacuous_test")


def test_does_not_raise_idiom_is_not_flagged(tmp_path: Any) -> None:
    """A bare CALL statement is a real "does not raise" bar — weak, but it fails when code raises.

    3 of 3 findings on the product's own suites before this guard existed.
    """
    rel = _write(
        tmp_path,
        "tests/test_no_raise.py",
        "def test_persist_skips_when_no_memory(tmp_path):\n"
        "    ctx = make_ctx(memory=None, root=tmp_path)\n"
        "    persist_coverage_ledger(ctx, {})  # no store -> no-op, no raise\n",
    )
    assert authored_suite_overstrict_findings(_ws(tmp_path), [rel], "persist the ledger") == []


def test_absence_only_test_is_not_vacuous(tmp_path: Any) -> None:
    """`assertNotIn` carries no view, so vacuity must use the PERMISSIVE classifier, not views."""
    rel = _write(
        tmp_path,
        "tests/test_absence_only.py",
        "import unittest\n\n\n"
        "class T(unittest.TestCase):\n"
        "    def test_no_debug(self):\n"
        "        out = render()\n"
        '        self.assertNotIn("DEBUG", out)\n',
    )
    assert authored_suite_overstrict_findings(_ws(tmp_path), [rel], "render without debug") == []


def test_raises_block_is_not_vacuous(tmp_path: Any) -> None:
    """A `pytest.raises` context asserts — not an `assert*` name, so it needs its own guard."""
    rel = _write(
        tmp_path,
        "tests/test_raises.py",
        "import pytest\n\n\n"
        "def test_missing_key():\n"
        "    data = load()\n"
        "    with pytest.raises(KeyError):\n"
        '        data["nope"]\n',
    )
    assert authored_suite_overstrict_findings(_ws(tmp_path), [rel], "raise on a missing key") == []


def test_delegating_test_is_not_vacuous(tmp_path: Any) -> None:
    """A test that binds nothing and delegates to a helper is never flagged."""
    rel = _write(
        tmp_path,
        "tests/test_delegate.py",
        "def test_all_cases():\n    _check_every_case()\n",
    )
    assert authored_suite_overstrict_findings(_ws(tmp_path), [rel], "check the cases") == []


def test_skipped_vacuous_test_is_not_flagged(tmp_path: Any) -> None:
    """A skipped test never runs, so it is not a bar either way — the file's standing convention."""
    rel = _write(
        tmp_path,
        "tests/test_skipped.py",
        "import pytest\n\n\n"
        '@pytest.mark.skip(reason="not yet")\n'
        "def test_later():\n"
        "    value = compute()\n",
    )
    assert authored_suite_overstrict_findings(_ws(tmp_path), [rel], "compute it") == []


def test_new_kinds_are_appended_last(tmp_path: Any) -> None:
    """Ordering is a contract: the critic truncates to 12, so a NEW finding must never displace an
    established one, and the positional `findings[0]` assertions above must keep their meaning."""
    rel = _write(
        tmp_path,
        "tests/test_both.py",
        "from pathlib import Path\n\n\n"
        "def test_output():\n"
        "    result = run_cli()\n"
        '    assert result.stdout == "1 [ ] Buy milk\\n"\n\n\n'
        "def test_spelling():\n"
        '    cli_content = Path("src/cli.py").read_text()\n'
        "    assert \"action='store_true'\" in cli_content\n",
    )
    findings = authored_suite_overstrict_findings(_ws(tmp_path), [rel], "list the todos")
    assert findings[0].kind == "exact_output_equality"
    assert findings[-1].kind == "source_formatting_pin"
