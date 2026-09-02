"""Red-phase oracle check (oracle-make-real Phase 1a)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import mosaera_core.mutation as mut
import mosaera_core.oraclecheck as oc
import mosaera_core.seedcheck as sc
import pytest
from mosaera_core.validation import ValidationOutcome

# Dummy collaborators — run_plan is monkeypatched in every test, so these are never used.
_SANDBOX: Any = object()


def _fake_workspace(tmp_path: Any) -> Any:
    return SimpleNamespace(root=tmp_path)


def test_no_authored_tests_is_unassessed(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    calls: list[int] = []

    def _fake_run(*_a: Any, **_k: Any) -> ValidationOutcome:
        calls.append(1)
        return ValidationOutcome(True, "")

    monkeypatch.setattr(sc, "run_plan", _fake_run)
    # No authored suite → None, and we never spin up a sandbox run.
    assert oc.authored_suite_is_red(_fake_workspace(tmp_path), _SANDBOX, []) is None
    assert calls == []


def test_green_pre_impl_is_tautological(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    # The authored suite PASSES with no implementation → it can't be the oracle.
    monkeypatch.setattr(sc, "run_plan", lambda *a, **k: ValidationOutcome(True, "all green"))
    got = oc.authored_suite_is_red(_fake_workspace(tmp_path), _SANDBOX, ["tests/test_acc.py"])
    assert got is False


def test_red_pre_impl_is_a_valid_oracle(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    # The authored suite FAILS with no implementation → a genuine test-first oracle.
    monkeypatch.setattr(sc, "run_plan", lambda *a, **k: ValidationOutcome(False, "1 failed"))
    got = oc.authored_suite_is_red(_fake_workspace(tmp_path), _SANDBOX, ["tests/test_acc.py"])
    assert got is True


def test_unassessable_is_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    # No runnable validation (outcome.passed is None) → cannot vouch either way.
    monkeypatch.setattr(sc, "run_plan", lambda *a, **k: ValidationOutcome(None, "no validation"))
    got = oc.authored_suite_is_red(_fake_workspace(tmp_path), _SANDBOX, ["tests/test_acc.py"])
    assert got is None


# --- assertion floor (Phase 1c) ---


def _write(tmp_path: Any, name: str, body: str) -> str:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return name


def test_real_assert_counts(tmp_path: Any) -> None:
    rel = _write(tmp_path, "tests/test_a.py", "def test_x():\n    assert add(2, 3) == 5\n")
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is True


def test_assert_true_only_is_trivial(tmp_path: Any) -> None:
    rel = _write(tmp_path, "tests/test_b.py", "def test_x():\n    assert True\n    assert 1\n")
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is False


def test_no_assertions_is_trivial(tmp_path: Any) -> None:
    rel = _write(tmp_path, "tests/test_c.py", "def test_x():\n    do_thing()\n")
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is False


def test_pytest_raises_counts(tmp_path: Any) -> None:
    body = "import pytest\n\ndef test_x():\n    with pytest.raises(ValueError):\n        boom()\n"
    rel = _write(tmp_path, "tests/test_d.py", body)
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is True


def test_unittest_assert_counts(tmp_path: Any) -> None:
    body = "class T:\n    def test_x(self):\n        self.assertEqual(f(), 1)\n"
    rel = _write(tmp_path, "tests/test_e.py", body)
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is True


def test_no_authored_asserts_is_none(tmp_path: Any) -> None:
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), []) is None


def test_unparseable_only_is_none(tmp_path: Any) -> None:
    rel = _write(tmp_path, "tests/test_bad.py", "def test_x(:\n    oops\n")  # syntax error
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is None


def test_compare_of_constants_is_trivial(tmp_path: Any) -> None:
    # `assert 1 == 1` is a tautology over literals — the exact evasion the review reproduced.
    rel = _write(tmp_path, "tests/test_c.py", "def test_x():\n    assert 1 == 1\n")
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is False


# --- F52: the SAME tautology in unittest's call syntax ---
#
# The floor rejected `assert True` but accepted `self.assertTrue(True)`: the call branch matched on
# the callee NAME and never examined the arguments. LedgerCLI's charter mandates unittest, so the
# floor was effectively absent on the product's own suites. Live run 20260806-191349-668b6a: the
# Proctor authored three bodies of `self.assertTrue(True)` and only a human reading the write-gate
# diff stopped it.


def test_unittest_assert_true_of_a_literal_is_trivial(tmp_path: Any) -> None:
    """The live regression, verbatim from run 20260806-191349-668b6a."""
    body = (
        "import unittest\n\n"
        "class TestStorage(unittest.TestCase):\n"
        "    def test_read_expenses_empty_file(self):\n"
        '        """Test that reading from an empty file returns an empty list"""\n'
        "        self.assertTrue(True)  # Placeholder - will be replaced by actual test\n"
    )
    rel = _write(tmp_path, "tests/test_storage.py", body)
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is False


def test_unittest_assert_equal_of_constants_is_trivial(tmp_path: Any) -> None:
    body = "class T:\n    def test_x(self):\n        self.assertEqual(1, 1)\n"
    rel = _write(tmp_path, "tests/test_f.py", body)
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is False


def test_unittest_assert_of_a_constant_expression_is_trivial(tmp_path: Any) -> None:
    """`assertTrue(1 == 1)` — the tautology nested one level inside the call."""
    body = "class T:\n    def test_x(self):\n        self.assertTrue(1 == 1)\n"
    rel = _write(tmp_path, "tests/test_g.py", body)
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is False


def test_unittest_assert_is_none_of_a_literal_is_trivial(tmp_path: Any) -> None:
    body = "class T:\n    def test_x(self):\n        self.assertIsNone(None)\n"
    rel = _write(tmp_path, "tests/test_h.py", body)
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is False


# --- F52 false-park guards: an honest suite must be UNAFFECTED ---


def test_unittest_assert_on_a_name_still_counts(tmp_path: Any) -> None:
    body = "class T:\n    def test_x(self):\n        self.assertTrue(result)\n"
    rel = _write(tmp_path, "tests/test_i.py", body)
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is True


def test_unittest_assert_on_a_call_still_counts(tmp_path: Any) -> None:
    body = "class T:\n    def test_x(self):\n        self.assertEqual(add(2, 3), 5)\n"
    rel = _write(tmp_path, "tests/test_j.py", body)
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is True


def test_a_literal_msg_kwarg_does_not_make_it_trivial(tmp_path: Any) -> None:
    """`msg=` carries no claim — only positional operands decide."""
    body = 'class T:\n    def test_x(self):\n        self.assertEqual(got, 5, msg="nope")\n'
    rel = _write(tmp_path, "tests/test_k.py", body)
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is True


def test_a_zero_arg_assert_call_counts(tmp_path: Any) -> None:
    """One-sided: a call with no positional args cannot be PROVEN trivial, so it is not rejected.
    The error to avoid here is a false park."""
    body = "class T:\n    def test_x(self):\n        with self.assertRaises():\n            f()\n"
    rel = _write(tmp_path, "tests/test_l.py", body)
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is True


def test_one_real_test_carries_a_suite_with_a_vacuous_one(tmp_path: Any) -> None:
    """The floor is per-SUITE and any-real: a vacuous test alongside a genuine one still clears."""
    body = (
        "class T:\n"
        "    def test_vacuous(self):\n"
        "        self.assertTrue(True)\n"
        "    def test_real(self):\n"
        "        self.assertEqual(total(), 7)\n"
    )
    rel = _write(tmp_path, "tests/test_m.py", body)
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is True


def test_assert_outside_a_test_function_does_not_count(tmp_path: Any) -> None:
    # A real assert only in a non-test helper (never a test function) doesn't count — the suite
    # asserts nothing AS A TEST. (Deny-by-default: safe direction.)
    rel = _write(tmp_path, "tests/test_h.py", "def _check():\n    assert real() == 5\n")
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is False


def test_skipped_test_does_not_count(tmp_path: Any) -> None:
    # #44 red-team (ADR-0052): a @pytest.mark.skip test COLLECTS but never RUNS → pytest exits 0
    # (reads green) while asserting nothing at runtime. It must not clear the assertion floor, or an
    # all-skipped suite would falsely look already-satisfied. Same for xfail and unittest.skip.
    skip = "import pytest\n\n@pytest.mark.skip(reason='todo')\ndef test_x():\n    assert f() == 1\n"
    assert (
        oc.authored_suite_asserts_behaviour(
            _fake_workspace(tmp_path), [_write(tmp_path, "tests/test_s.py", skip)]
        )
        is False
    )
    xfail = "import pytest\n\n@pytest.mark.xfail\ndef test_x():\n    assert f() == 1\n"
    assert (
        oc.authored_suite_asserts_behaviour(
            _fake_workspace(tmp_path), [_write(tmp_path, "tests/test_xf.py", xfail)]
        )
        is False
    )
    ut = (
        "import unittest\n\nclass T:\n    @unittest.skip('x')\n"
        "    def test_x(self):\n        assert f() == 1\n"
    )
    assert (
        oc.authored_suite_asserts_behaviour(
            _fake_workspace(tmp_path), [_write(tmp_path, "tests/test_ut.py", ut)]
        )
        is False
    )


def test_assert_in_an_uncalled_nested_function_does_not_count(tmp_path: Any) -> None:
    # Red-team #54 R2: a gut that hides the assert in a nested helper that never runs. The assert is
    # syntactically present (ast.walk would find it) but never executes → must NOT clear the floor.
    body = "def test_x():\n    def _inner():\n        assert real() == 5\n    return\n"
    rel = _write(tmp_path, "tests/test_n.py", body)
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is False


def test_assert_under_a_statically_false_branch_does_not_count(tmp_path: Any) -> None:
    # Red-team #54 R2: `if False:` — a dead branch whose assert never runs.
    body = "def test_x():\n    if False:\n        assert real() == 5\n"
    rel = _write(tmp_path, "tests/test_dead.py", body)
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is False


def test_assert_of_a_lambda_object_is_trivial(tmp_path: Any) -> None:
    # Red-team #54 R2: `assert (lambda: False)` — the lambda OBJECT is always truthy, so the assert
    # can never fail; it asserts nothing about behaviour.
    body = "def test_x():\n    assert (lambda: real() == 5)\n"
    rel = _write(tmp_path, "tests/test_lam.py", body)
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is False


def test_empty_parametrize_never_runs_so_does_not_count(tmp_path: Any) -> None:
    # Red-team #54 R2: an empty parametrize set generates ZERO cases → pytest reports skipped → the
    # assert never executes at runtime.
    body = (
        "import pytest\n\n@pytest.mark.parametrize('x', [])\n"
        "def test_x(x):\n    assert real(x) == 5\n"
    )
    rel = _write(tmp_path, "tests/test_ep.py", body)
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is False


def test_assert_in_a_CALLED_nested_helper_edge_errs_safe(tmp_path: Any) -> None:
    # A test whose ONLY assertion is in a nested helper it DOES call is rare; the reachability floor
    # conservatively excludes all nested-scope asserts, so this errs toward park (deny-by-default) —
    # documented safe direction, not a false-green. An assert in the test's own body still counts.
    called = "def test_x():\n    def _c():\n        assert real() == 5\n    _c()\n"
    rel = _write(tmp_path, "tests/test_c2.py", called)
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is False
    body = "def test_y():\n    for i in range(3):\n        assert real(i) == i\n"  # loop counts
    rel2 = _write(tmp_path, "tests/test_loop.py", body)
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel2]) is True


def test_a_running_test_beside_a_skipped_one_still_counts(tmp_path: Any) -> None:
    # A skipped test doesn't disqualify the suite — a sibling test that DOES run + assert real still
    # clears the floor.
    body = (
        "import pytest\n\n@pytest.mark.skip\ndef test_todo():\n    assert g() == 2\n\n"
        "def test_real():\n    assert f() == 1\n"
    )
    rel = _write(tmp_path, "tests/test_mix.py", body)
    assert oc.authored_suite_asserts_behaviour(_fake_workspace(tmp_path), [rel]) is True


# --- standing-suite independence (Phase 2, hardened) ---

# The change under test references `calc` (the credited path) unless a test says otherwise.
_CHANGED = ["calc.py"]


def test_standing_suite_pyproject_only_not_credited(tmp_path: Any) -> None:
    # THE reproduced HIGH defect: a repo carrying only a pyproject.toml (zero tests) must NOT count
    # as an independent oracle — plain bool(integrity_baseline) credited any pyproject-bearing repo.
    assert (
        oc.standing_suite_is_independent_oracle(
            _fake_workspace(tmp_path), {"pyproject.toml": "h"}, _CHANGED
        )
        is False
    )


def test_standing_suite_conftest_only_not_credited(tmp_path: Any) -> None:
    assert (
        oc.standing_suite_is_independent_oracle(
            _fake_workspace(tmp_path), {"conftest.py": "h"}, _CHANGED
        )
        is False
    )


def test_standing_suite_real_tests_credited(tmp_path: Any) -> None:
    # Asserts something real AND imports the changed module → a valid oracle for this change.
    _write(
        tmp_path,
        "tests/test_x.py",
        "from calc import compute\ndef test_x():\n    assert compute() == 7\n",
    )
    assert (
        oc.standing_suite_is_independent_oracle(
            _fake_workspace(tmp_path), {"tests/test_x.py": "h"}, _CHANGED
        )
        is True
    )


def test_standing_suite_tautological_tests_not_credited(tmp_path: Any) -> None:
    _write(
        tmp_path, "tests/test_x.py", "from calc import compute\ndef test_x():\n    assert True\n"
    )
    assert (
        oc.standing_suite_is_independent_oracle(
            _fake_workspace(tmp_path), {"tests/test_x.py": "h"}, _CHANGED
        )
        is False
    )


def test_standing_suite_empty_baseline_not_credited(tmp_path: Any) -> None:
    assert oc.standing_suite_is_independent_oracle(_fake_workspace(tmp_path), {}, _CHANGED) is False
    assert (
        oc.standing_suite_is_independent_oracle(_fake_workspace(tmp_path), None, _CHANGED) is False
    )


# --- module-reference heuristic (Phase 2b / F1) ---


def test_changed_module_paths() -> None:
    assert oc._changed_module_paths(["pkg/parser.py"]) == {"pkg/parser"}
    assert oc._changed_module_paths(["pkg/__init__.py"]) == {"pkg"}
    assert oc._changed_module_paths(["a.py", "b/c/d.py"]) == {"a", "b/c/d"}
    assert oc._changed_module_paths(["__init__.py"]) == set()  # top-level __init__: no package
    assert oc._changed_module_paths(["notes.md", "data.json"]) == set()


def test_standing_suite_not_credited_when_change_is_unreferenced(tmp_path: Any) -> None:
    # THE F1 exploit: a real, asserting standing suite about UNRELATED code (utils) must NOT credit
    # oracle_verified for a change to feature.py that no test touches → the run parks.
    _write(
        tmp_path,
        "tests/test_utils.py",
        "from utils import add\ndef test_add():\n    assert add(1, 2) == 3\n",
    )
    assert (
        oc.standing_suite_is_independent_oracle(
            _fake_workspace(tmp_path), {"tests/test_utils.py": "h"}, ["feature.py"]
        )
        is False
    )


def test_standing_suite_credited_via_dotted_import(tmp_path: Any) -> None:
    # A dotted import of the changed submodule references it (leaf `feature` = pkg/feature.py).
    _write(
        tmp_path,
        "tests/test_f.py",
        "import pkg.feature\ndef test_f():\n    assert pkg.feature.run() == 1\n",
    )
    assert (
        oc.standing_suite_is_independent_oracle(
            _fake_workspace(tmp_path), {"tests/test_f.py": "h"}, ["pkg/feature.py"]
        )
        is True
    )


def test_attribute_collision_does_not_credit(tmp_path: Any) -> None:
    # F-A: an ATTRIBUTE access whose name collides with a changed module leaf — `app.config[...]`
    # for a change to config.py — must NOT credit. The test never imports config.py.
    _write(
        tmp_path,
        "tests/test_health.py",
        "from myproject import app\ndef test_health():\n    assert app.config['ENV'] == 'test'\n",
    )
    assert (
        oc.standing_suite_is_independent_oracle(
            _fake_workspace(tmp_path), {"tests/test_health.py": "h"}, ["myproject/config.py"]
        )
        is False
    )


def test_from_import_name_collision_does_not_credit(tmp_path: Any) -> None:
    # Finding-1: `from django.conf import settings` imports a third-party SYMBOL named `settings`;
    # it must NOT credit a change to the repo's own `myapp/settings.py`. Path-based matching
    # (django/conf/settings ≠ myapp/settings) closes the imported-name namespace collision.
    _write(
        tmp_path,
        "tests/test_v.py",
        "from django.conf import settings\ndef test_v():\n    assert settings.DEBUG is False\n",
    )
    assert (
        oc.standing_suite_is_independent_oracle(
            _fake_workspace(tmp_path), {"tests/test_v.py": "h"}, ["myapp/settings.py"]
        )
        is False
    )


def test_cross_package_leaf_collision_does_not_credit(tmp_path: Any) -> None:
    # Finding-2: `import pkg_b.utils` must NOT credit a change to a DIFFERENT `pkg_a/utils.py` —
    # path matching (pkg_b/utils ≠ pkg_a/utils) rejects the shared leaf name.
    _write(
        tmp_path,
        "tests/test_u.py",
        "import pkg_b.utils\ndef test_u():\n    assert pkg_b.utils.f() == 1\n",
    )
    assert (
        oc.standing_suite_is_independent_oracle(
            _fake_workspace(tmp_path), {"tests/test_u.py": "h"}, ["pkg_a/utils.py"]
        )
        is False
    )


def test_stdlib_single_segment_import_does_not_credit(tmp_path: Any) -> None:
    # Finding (round 4): a test importing a STDLIB/third-party single-segment module must NOT credit
    # a repo file of the same leaf. `import logging` / `from types import X` are near-universal and
    # have nothing to do with the repo's own myapp/logging.py or pkg/types.py.
    _write(
        tmp_path,
        "tests/test_l.py",
        "import logging\nfrom types import SimpleNamespace\n\ndef test_l():\n    assert logging\n",
    )
    base = {"tests/test_l.py": "h"}
    assert (
        oc.standing_suite_is_independent_oracle(
            _fake_workspace(tmp_path), base, ["myapp/logging.py"]
        )
        is False
    )
    assert (
        oc.standing_suite_is_independent_oracle(_fake_workspace(tmp_path), base, ["pkg/types.py"])
        is False
    )


def test_single_segment_credits_top_level_and_src(tmp_path: Any) -> None:
    # The legit single-segment cases still credit: a top-level module, and a src/-rooted one.
    _write(tmp_path, "tests/test_c.py", "import calc\ndef test_c():\n    assert calc.f() == 1\n")
    base = {"tests/test_c.py": "h"}
    assert (
        oc.standing_suite_is_independent_oracle(_fake_workspace(tmp_path), base, ["calc.py"])
        is True
    )
    assert (
        oc.standing_suite_is_independent_oracle(_fake_workspace(tmp_path), base, ["src/calc.py"])
        is True
    )


def test_from_import_submodule_credits_under_src_layout(tmp_path: Any) -> None:
    # The legitimate case survives: `from myapp import settings` DOES credit a change to the real
    # `src/myapp/settings.py` (import path is a component-suffix of the src-prefixed repo path).
    _write(
        tmp_path,
        "tests/test_s.py",
        "from myapp import settings\ndef test_s():\n    assert settings.LIMIT == 5\n",
    )
    assert (
        oc.standing_suite_is_independent_oracle(
            _fake_workspace(tmp_path), {"tests/test_s.py": "h"}, ["src/myapp/settings.py"]
        )
        is True
    )


def test_behavioural_non_py_change_not_credited(tmp_path: Any) -> None:
    # F-B (adversarial finding): a change confined to a behavioural non-.py file (flags.json) yields
    # no module names, but it is NOT inert — an unrelated suite must not credit it. Deny → park.
    _write(
        tmp_path,
        "tests/test_x.py",
        "from calc import compute\ndef test_x():\n    assert compute() == 7\n",
    )
    assert (
        oc.standing_suite_is_independent_oracle(
            _fake_workspace(tmp_path), {"tests/test_x.py": "h"}, ["flags.json"]
        )
        is False
    )


def test_docs_only_change_still_credited(tmp_path: Any) -> None:
    # Provably-inert change (docs only, by EXTENSION) → F1 moot; the asserting suite counts.
    _write(tmp_path, "tests/test_x.py", "def test_x():\n    assert real() == 5\n")
    assert (
        oc.standing_suite_is_independent_oracle(
            _fake_workspace(tmp_path), {"tests/test_x.py": "h"}, ["README.md", "docs/guide.rst"]
        )
        is True
    )


def test_config_under_docs_dir_is_not_inert(tmp_path: Any) -> None:
    # Finding-3: a behavioural file living under a docs/ dir (`docs/runtime.yaml`,
    # `service/docs/flags.json`) must NOT read as inert — `_is_docs` classifies by EXTENSION, not
    # path, so these still DENY.
    _write(tmp_path, "tests/test_x.py", "def test_x():\n    assert real() == 5\n")
    assert (
        oc.standing_suite_is_independent_oracle(
            _fake_workspace(tmp_path),
            {"tests/test_x.py": "h"},
            ["docs/runtime.yaml", "service/docs/flags.json"],
        )
        is False
    )


def test_test_only_change_still_credited(tmp_path: Any) -> None:
    # Only test files changed → nothing behavioural to attribute → the asserting suite still counts.
    _write(tmp_path, "tests/test_x.py", "def test_x():\n    assert real() == 5\n")
    assert (
        oc.standing_suite_is_independent_oracle(
            _fake_workspace(tmp_path), {"tests/test_x.py": "h"}, ["tests/test_new.py"]
        )
        is True
    )


# --- mutation check (Phase 1b) ---

_MOD = "def f(a, b):\n    return a + b\n"


def test_mutate_return_to_none() -> None:
    out = oc._mutate_source(_MOD)
    assert out is not None and "return None" in out and "return a + b" not in out


def test_mutate_flips_comparison_when_no_return() -> None:
    out = oc._mutate_source("def f(a, b):\n    if a == b:\n        pass\n")
    assert out is not None and "!=" in out


def test_mutate_none_when_nothing_mutable() -> None:
    # F83 widened the operator set: a numeric literal IS now mutable (constant +1), so the old
    # fixture `x = 1` no longer qualifies as "nothing mutable" — which is the point of the change.
    # A genuinely non-mutable statement keeps the deny-by-default behaviour this pins.
    assert oc._mutate_source("import os\nCONFIG = os.environ\n") is None


def test_mutate_syntax_error_is_none() -> None:
    assert oc._mutate_source("def f(:\n") is None


def test_suite_catches_mutation(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    (tmp_path / "mod.py").write_text(_MOD, encoding="utf-8")
    monkeypatch.setattr(mut, "run_plan", lambda *a, **k: ValidationOutcome(False, "1 failed"))
    got = oc.suite_catches_a_mutation(
        _fake_workspace(tmp_path), _SANDBOX, ["mod.py"], ["tests/test_f.py"]
    )
    assert got is True
    assert (tmp_path / "mod.py").read_text() == _MOD  # ALWAYS reverted


def test_suite_survives_mutation_is_rubber_stamp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    (tmp_path / "mod.py").write_text(_MOD, encoding="utf-8")
    monkeypatch.setattr(mut, "run_plan", lambda *a, **k: ValidationOutcome(True, "all green"))
    got = oc.suite_catches_a_mutation(
        _fake_workspace(tmp_path), _SANDBOX, ["mod.py"], ["tests/test_f.py"]
    )
    assert got is False
    assert (tmp_path / "mod.py").read_text() == _MOD  # reverted even after a "green" run


def test_suite_catches_no_tests_is_none(tmp_path: Any) -> None:
    (tmp_path / "mod.py").write_text(_MOD, encoding="utf-8")
    assert oc.suite_catches_a_mutation(_fake_workspace(tmp_path), _SANDBOX, ["mod.py"], []) is None


def test_suite_catches_no_mutable_source_is_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # F83: `x = 1` gained a constant mutant, so the fixture moved to a genuinely non-mutable
    # statement. The property under test — no mutable construct => None, never a false verdict —
    # is unchanged and is exactly the `not_measured` case.
    (tmp_path / "mod.py").write_text("import os\nCONFIG = os.environ\n", encoding="utf-8")
    monkeypatch.setattr(mut, "run_plan", lambda *a, **k: ValidationOutcome(False, ""))
    got = oc.suite_catches_a_mutation(
        _fake_workspace(tmp_path), _SANDBOX, ["mod.py"], ["tests/t.py"]
    )
    assert got is None


# --- no-op statement-deletion operator: catches a purely non-mutable change (#39, ADR-0049) ---


def test_mutate_noop_deletes_bare_call() -> None:
    # A bare side-effecting call with no return/comparison is mutated to `pass`.
    out = oc._mutate_source("def f(x):\n    x.append(1)\n")
    assert out is not None and "pass" in out and "append" not in out


def test_mutate_noop_deletes_await_call() -> None:
    out = oc._mutate_source("async def f(s):\n    await s.delete(1)\n")
    assert out is not None and "pass" in out and "delete" not in out


def test_mutate_noop_excludes_bare_yield() -> None:
    # Deleting the sole yield would de-generator the fn → TypeError downstream (error-as-caught,
    # a false CREDIT), so a bare yield is NOT no-opable → None.
    assert oc._mutate_source("def g():\n    yield compute()\n") is None


def test_mutate_noop_excludes_bare_walrus() -> None:
    # A bare walrus binds a name; deleting it → NameError downstream (error-as-caught) → excluded.
    assert oc._mutate_source("def f():\n    (y := compute())\n") is None


def test_mutate_noop_skips_walrus_selects_later_call() -> None:
    # When a walrus (excluded) precedes a bare call (no-opable), the operator skips the walrus and
    # mutates the call — it never wrongly grabs the name-binding walrus.
    out = oc._mutate_source("def f():\n    (y := compute())\n    log(y)\n")
    assert out is not None and "(y := compute())" in out and "log(y)" not in out


def test_mutate_noop_excludes_walrus_in_call_args() -> None:
    # Red-team Finding 2: a walrus NESTED in call args is still a top-level Call, but deleting the
    # statement unbinds `y` (→ NameError downstream = error-as-caught). Must be excluded → None.
    assert oc._mutate_source("def h(x):\n    save(y := compute(x))\n") is None
    assert oc._mutate_source("def h(x):\n    a(b(y := x))\n") is None  # nested


def test_mutate_noop_keeps_legit_side_effect_calls() -> None:
    # The walrus guard must NOT over-exclude genuine side-effecting calls that bind no name —
    # next()/starred/method calls are legitimate no-op targets (their deletion is a real side-effect
    # removal, a downstream-dependency kill, not a name unbinding).
    assert "pass" in (oc._mutate_source("def h(g):\n    next(g)\n") or "")
    assert "pass" in (oc._mutate_source("def h(a):\n    log(*a)\n") or "")


def test_mutate_noop_excludes_docstring() -> None:
    # A docstring/bare literal is a true no-op — deleting it is never caught (false PARK) → None.
    assert oc._mutate_source("def f():\n    'just a docstring'\n") is None


def test_mutate_noop_excludes_assignment() -> None:
    # An assignment isn't an Expr statement at all; deleting a binding → NameError → excluded.
    assert oc._mutate_source("def f():\n    x = compute()\n") is None


def test_mutate_return_precedes_noop() -> None:
    # Operator order: a return is mutated before any bare call, even when the call comes first.
    out = oc._mutate_source("def f(a, b):\n    log(a)\n    return a + b\n")
    assert out is not None and "return None" in out and "log(a)" in out


def test_mutate_targets_changed_line() -> None:
    src = "def f():\n    first()\n    second()\n"
    assert oc._mutate_source(src, {2}) == "def f():\n    pass\n    second()"
    assert oc._mutate_source(src, {3}) == "def f():\n    first()\n    pass"


def test_mutate_changed_line_with_no_mutable_node_is_none() -> None:
    # A changed line holding no mutable construct yields None (declines rather than mutating
    # something irrelevant elsewhere) — the honest, deny-safe outcome.
    assert oc._mutate_source("def f():\n    first()\n    second()\n", {1}) is None


def test_suite_catches_noop_mutation(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    # End-to-end: a purely non-mutable change (a bare call) now RUNS the suite instead of the old
    # None-without-running — closing the #39 self-vouch gap.
    src = "def f(x):\n    x.append(1)\n"
    (tmp_path / "mod.py").write_text(src, encoding="utf-8")
    monkeypatch.setattr(mut, "run_plan", lambda *a, **k: ValidationOutcome(False, "1 failed"))
    got = oc.suite_catches_a_mutation(
        _fake_workspace(tmp_path), _SANDBOX, ["mod.py"], ["tests/t.py"], changed={"mod.py": {2}}
    )
    assert got is True
    assert (tmp_path / "mod.py").read_text() == src  # ALWAYS reverted


def test_suite_changed_confines_mutation(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    # `changed` pointing only at an unmutable line yields no mutation → None (rather than mutating
    # the first construct anywhere in the file, which could land on unchanged, well-tested code).
    src = "def f(x):\n    x.append(1)\n"
    (tmp_path / "mod.py").write_text(src, encoding="utf-8")
    monkeypatch.setattr(mut, "run_plan", lambda *a, **k: ValidationOutcome(True, "green"))
    got = oc.suite_catches_a_mutation(
        _fake_workspace(tmp_path), _SANDBOX, ["mod.py"], ["tests/t.py"], changed={"mod.py": {1}}
    )
    assert got is None


def test_suite_downgrades_when_a_later_file_survives(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # Red-team Finding 1: the loop must NOT early-return True on the first CAUGHT file and mask a
    # later SURVIVED mutation. a.py's no-op deletion is caught (red); b.py's return-mutation lives
    # (green) → the whole check must return False (a rubber stamp exists), never True.
    a_src, b_src = "def f(x):\n    x.append(1)\n", "def g(a, b):\n    return a + b\n"
    (tmp_path / "a.py").write_text(a_src, encoding="utf-8")
    (tmp_path / "b.py").write_text(b_src, encoding="utf-8")
    outcomes = iter([ValidationOutcome(False, "a caught"), ValidationOutcome(True, "b survived")])
    monkeypatch.setattr(mut, "run_plan", lambda *a, **k: next(outcomes))
    got = oc.suite_catches_a_mutation(
        _fake_workspace(tmp_path), _SANDBOX, ["a.py", "b.py"], ["tests/t.py"]
    )
    assert got is False
    assert (tmp_path / "a.py").read_text() == a_src  # both reverted
    assert (tmp_path / "b.py").read_text() == b_src


def test_suite_true_only_when_all_checked_and_none_survive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # The mirror: when every mutable file's mutation is caught, the check returns True (a genuine
    # oracle) — proving fail-closed doesn't over-downgrade.
    (tmp_path / "a.py").write_text("def f(x):\n    x.append(1)\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def g(a, b):\n    return a + b\n", encoding="utf-8")
    monkeypatch.setattr(mut, "run_plan", lambda *a, **k: ValidationOutcome(False, "caught"))
    got = oc.suite_catches_a_mutation(
        _fake_workspace(tmp_path), _SANDBOX, ["a.py", "b.py"], ["tests/t.py"]
    )
    assert got is True


def test_suite_reverts_bytes_exactly(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    # Red-team A1/A2: the revert must be BYTE-for-byte. A file with explicit LF endings (+ a
    # non-UTF-8 byte) must come back identical — text I/O would CRLF-translate on Windows and burn
    # the non-UTF-8 byte to U+FFFD, shipping a corrupted whole-file diff.
    raw = b"# caf\xe9 (latin-1)\ndef f(x):\n    x.append(1)\n    return 2\n"  # LF + a latin-1 byte
    p = tmp_path / "mod.py"
    p.write_bytes(raw)
    monkeypatch.setattr(mut, "run_plan", lambda *a, **k: ValidationOutcome(False, "caught"))
    oc.suite_catches_a_mutation(_fake_workspace(tmp_path), _SANDBOX, ["mod.py"], ["tests/t.py"])
    assert p.read_bytes() == raw  # byte-exact: endings + raw bytes preserved


# --- change-coverage gate: the `covered` param decides relevance precisely (#29 P1) ---


def _asserting_suite(tmp_path: Any) -> dict[str, str]:
    _write(tmp_path, "tests/test_x.py", "def test_x():\n    assert compute() == 7\n")
    return {"tests/test_x.py": "h"}


def test_coverage_true_credits_an_asserting_suite(tmp_path: Any) -> None:
    # Coverage shows a test executes the change + the suite asserts real → a genuine oracle.
    base = _asserting_suite(tmp_path)
    assert (
        oc.standing_suite_is_independent_oracle(
            _fake_workspace(tmp_path), base, ["feature.py"], covered=True
        )
        is True
    )


def test_coverage_false_denies_even_an_asserting_suite(tmp_path: Any) -> None:
    # Suite asserts real but coverage shows NO test runs the change → not an oracle for it → park.
    base = _asserting_suite(tmp_path)
    assert (
        oc.standing_suite_is_independent_oracle(
            _fake_workspace(tmp_path), base, ["feature.py"], covered=False
        )
        is False
    )


def test_coverage_does_not_override_the_assertion_floor(tmp_path: Any) -> None:
    # Even covered=True can't credit a tautological suite — the assertion floor still gates first.
    _write(tmp_path, "tests/test_x.py", "def test_x():\n    assert True\n")
    assert (
        oc.standing_suite_is_independent_oracle(
            _fake_workspace(tmp_path), {"tests/test_x.py": "h"}, ["feature.py"], covered=True
        )
        is False
    )


def test_coverage_none_falls_back_to_import_heuristic(tmp_path: Any) -> None:
    # covered=None (coverage off / unmeasurable) → the coarse import heuristic decides as before.
    _write(
        tmp_path, "tests/test_f.py", "from feature import f\ndef test_f():\n    assert f() == 1\n"
    )
    base = {"tests/test_f.py": "h"}
    assert (
        oc.standing_suite_is_independent_oracle(
            _fake_workspace(tmp_path), base, ["feature.py"], covered=None
        )
        is True
    )


# --- Comprehensive mutation (ADR-0071): mutate EVERY changed construct, require ALL caught ---

_TWO = "def f(x):\n    a = x == 1\n    return a\n"  # two mutable constructs: a compare + a return


def test_all_mutations_enumerates_every_construct() -> None:
    ms = mut._all_mutations(_TWO, None, cap=20)
    # F83 added arithmetic + constant operators, so the literal `1` in `x == 1` is a third site.
    # The property under test is construct-fair ENUMERATION (a single mutation would take only
    # one), not the exact count — but the count is pinned so a silent operator change is visible.
    assert len(ms) == 3
    assert any("return None" in m for m in ms)
    assert any("x != 1" in m for m in ms)
    assert any("x == 2" in m for m in ms)


def test_all_mutations_respects_the_cap() -> None:
    src = "def f():\n    return 1\n    return 2\n    return 3\n"  # three eligible returns
    assert len(mut._all_mutations(src, None, cap=2)) == 2  # capped (cost bound)


def test_comprehensive_catches_a_second_region_single_misses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # The suite asserts f's return value but never the comparison branch: the FIRST mutant (return)
    # is caught, the SECOND (== flip) survives — a rubber stamp a single mutation cannot see.
    (tmp_path / "mod.py").write_text(_TWO, encoding="utf-8")
    ws = _fake_workspace(tmp_path)

    # SINGLE: one mutant (the return), caught → True (the compare rubber stamp is never checked).
    monkeypatch.setattr(mut, "run_plan", lambda *a, **k: ValidationOutcome(False, "caught"))
    assert oc.suite_catches_a_mutation(ws, _SANDBOX, ["mod.py"], ["tests/t.py"]) is True

    # COMPREHENSIVE: return caught, then the compare mutant SURVIVES → False (rubber stamp found).
    outcomes = iter([ValidationOutcome(False, "caught"), ValidationOutcome(True, "survived")])
    monkeypatch.setattr(mut, "run_plan", lambda *a, **k: next(outcomes))
    got = oc.suite_catches_a_mutation(ws, _SANDBOX, ["mod.py"], ["tests/t.py"], comprehensive=True)
    assert got is False
    assert (tmp_path / "mod.py").read_text() == _TWO  # ALWAYS reverted, byte-for-byte


def test_comprehensive_true_when_every_mutant_is_caught(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    (tmp_path / "mod.py").write_text(_TWO, encoding="utf-8")
    monkeypatch.setattr(mut, "run_plan", lambda *a, **k: ValidationOutcome(False, "caught"))
    got = oc.suite_catches_a_mutation(
        _fake_workspace(tmp_path), _SANDBOX, ["mod.py"], ["tests/t.py"], comprehensive=True
    )
    assert got is True  # both mutants caught → the suite genuinely verifies every changed behaviour


def test_all_mutations_reaches_a_compare_nested_in_a_return() -> None:
    # Red-team #74 HIGH: a comparison inside a return value must be enumerated (visitors recurse).
    ms = mut._all_mutations("def f(n):\n    return {'big': n > 100}\n", None, cap=20)
    assert any("n <= 100" in m for m in ms)  # the compare flip is present, not swallowed


def test_all_mutations_reaches_a_compare_in_a_bare_call() -> None:
    ms = mut._all_mutations("def f(a, b):\n    record(a == b)\n", None, cap=20)
    assert any("a != b" in m for m in ms)


def test_all_mutations_cap_is_construct_fair_not_return_biased() -> None:
    # Red-team #74 Finding 2: a change with many returns must NOT starve the comparison out of the
    # cap — kinds are interleaved, so a small cap still includes the compare.
    src = "def f(n):\n    if n > 0:\n        return 1\n    return 2\n    return 3\n"
    ms = mut._all_mutations(src, None, cap=2)  # 3 returns + 1 compare, cap 2
    assert len(ms) == 2
    assert any("n <= 0" in m for m in ms)  # the compare is reached despite the returns


# --- the assertion profile: measuring a WEAKENING, not a change (#66, ADR-0087 §6) -------------


def test_the_literal_f59_case_is_detected() -> None:
    """The measured failure ADR-0087 opens with. Run `20260806-215759-0ba3b2` deleted
    `assert len(lines) == 2` from a delivered test and SHIPPED, because the tamper guard asks
    "was this touched?" and nothing asked "was the bar lowered?"."""
    before = oc.assertion_profile(
        "def test_totals():\n"
        "    lines = render(rows)\n"
        "    assert len(lines) == 2\n"
        "    assert lines[0].startswith('Total')\n"
    )
    after = oc.assertion_profile(
        "def test_totals():\n    lines = render(rows)\n    assert lines[0].startswith('Total')\n"
    )
    assert before == {"test_totals": 2}
    assert after == {"test_totals": 1}
    assert oc.profile_regression(before or {}, after or {}) == ["test_totals (2 -> 1 assertions)"]


def test_restoring_an_assertion_is_not_a_regression() -> None:
    """The other half of the same measurement. Run `...-3a6733` RESTORED that assertion under
    explicit operator authorization and was blocked — the guard caught the honest change and
    missed the dishonest one. One-sided means strengthening always passes."""
    weak = {"test_totals": 1}
    strong = {"test_totals": 2}
    assert oc.profile_regression(weak, strong) == []


def test_a_removed_test_function_is_a_regression() -> None:
    assert oc.profile_regression({"test_a": 1, "test_b": 3}, {"test_a": 1}) == ["test_b (removed)"]


def test_an_added_test_regresses_nothing() -> None:
    assert oc.profile_regression({"test_a": 1}, {"test_a": 1, "test_new": 5}) == []


def test_a_reformat_with_identical_assertions_is_clean() -> None:
    """The false-park direction, which is the expensive one: whitespace, comments and reordering
    must not read as a weakening."""
    a = oc.assertion_profile("def test_x():\n    assert f() == 1\n    assert g() == 2\n")
    b = oc.assertion_profile(
        "def test_x():\n    # explain the intent\n    assert  g() == 2\n\n    assert f() == 1\n"
    )
    assert a == b == {"test_x": 2}
    assert oc.profile_regression(a or {}, b or {}) == []


def test_adding_a_skip_decorator_reads_as_a_regression() -> None:
    """A skipped test collects green and asserts nothing at runtime — the ADR-0052 rubber stamp.
    Decorating a surviving test is a weakening with no visible edit to its body."""
    before = oc.assertion_profile("def test_x():\n    assert f() == 1\n")
    after = oc.assertion_profile(
        "import pytest\n\n@pytest.mark.skip\ndef test_x():\n    assert f() == 1\n"
    )
    assert after == {"test_x": 0}
    assert oc.profile_regression(before or {}, after or {}) == ["test_x (1 -> 0 assertions)"]


def test_class_methods_are_profiled_under_their_class() -> None:
    """Qualnames must be class-scoped or two `test_totals` in different classes collide, and a
    deletion in one would be masked by the other."""
    prof = oc.assertion_profile(
        "class TestA:\n"
        "    def test_totals(self):\n"
        "        assert f() == 1\n"
        "class TestB:\n"
        "    def test_totals(self):\n"
        "        assert g() == 2\n"
        "        assert h() == 3\n"
    )
    assert prof == {"TestA.test_totals": 1, "TestB.test_totals": 2}


def test_an_empty_parametrize_reads_as_zero() -> None:
    # Red-team #54 R2: zero generated cases ⇒ the body never runs.
    prof = oc.assertion_profile(
        "import pytest\n\n@pytest.mark.parametrize('n', [])\ndef test_x(n):\n    assert f(n) == 1\n"
    )
    assert prof == {"test_x": 0}


def test_trivial_assertions_do_not_inflate_the_count() -> None:
    """Count inflation is the obvious attack: pad a gutted test back to its old number. The count
    reuses the assertion-floor rule, so tautologies are worth zero on both sides of it."""
    prof = oc.assertion_profile(
        "def test_x():\n"
        "    assert True\n"
        "    assert 1 == 1\n"
        "    self.assertEqual(1, 1)\n"
        "    assert f() == 2\n"
    )
    assert prof == {"test_x": 1}


def test_an_unreachable_assertion_does_not_count() -> None:
    """Reachability is inherited from `_reachable`: an assert in a nested helper or a dead branch
    never runs, so it cannot be used to pad the profile back up."""
    prof = oc.assertion_profile(
        "def test_x():\n"
        "    def helper():\n"
        "        assert f() == 1\n"
        "    if False:\n"
        "        assert g() == 2\n"
        "    assert h() == 3\n"
    )
    assert prof == {"test_x": 1}


def test_a_non_test_helper_is_not_profiled() -> None:
    prof = oc.assertion_profile(
        "def check_it():\n    assert f() == 1\n\ndef test_x():\n    check_it()\n"
    )
    assert prof == {"test_x": 0}


def test_unparseable_source_is_unknown_not_empty() -> None:
    """The one that matters most. `None` must never be coerced to `{}` — an empty profile would
    make a syntax error read as "nothing was lost", i.e. a licence to gut the file."""
    assert oc.assertion_profile("def test_x(:\n") is None
    # And an empty AFTER against a real BEFORE is unambiguously a total loss.
    assert oc.profile_regression({"test_x": 2}, {}) == ["test_x (removed)"]


def test_the_floor_and_the_count_cannot_disagree() -> None:
    """`_asserts_something_real` is now defined as `_real_assertions > 0`. Pin that they stay one
    rule — a divergence would let a test clear the floor while profiling as zero (or vice versa)."""
    import ast

    for src, expected in [
        ("def test_x():\n    assert True\n", False),
        ("def test_x():\n    assert f() == 1\n", True),
        ("def test_x():\n    self.assertEqual(1, 1)\n", False),
        ("def test_x():\n    self.assertEqual(f(), 1)\n", True),
        ("def test_x():\n    pass\n", False),
    ]:
        fn = ast.parse(src).body[0]
        assert oc._asserts_something_real(fn) is expected
        assert (oc._real_assertions(fn) > 0) is expected


def test_parametrizing_a_test_is_not_a_regression() -> None:
    """Red-team round 2 FIX: replacing three inline asserts with a three-case parametrize is a
    strengthening any reviewer would ask for. Counting EXECUTIONS rather than statements makes the
    two forms agree — before this, the standard refactor read as 3 -> 1 and false-parked."""
    inline = oc.assertion_profile(
        "def test_a():\n    assert f(1) == 1\n    assert f(2) == 2\n    assert f(3) == 3\n"
    )
    parametrized = oc.assertion_profile(
        "import pytest\n\n"
        "@pytest.mark.parametrize('n', [1, 2, 3])\n"
        "def test_a(n):\n"
        "    assert f(n) == n\n"
    )
    assert inline == parametrized == {"test_a": 3}
    assert oc.profile_regression(inline or {}, parametrized or {}) == []


def test_shrinking_a_parametrize_set_is_a_regression() -> None:
    """The other direction must still bite: dropping cases drops coverage."""
    wide = oc.assertion_profile(
        "import pytest\n\n@pytest.mark.parametrize('n', [1, 2, 3])\n"
        "def test_a(n):\n    assert f(n) == n\n"
    )
    narrow = oc.assertion_profile(
        "import pytest\n\n@pytest.mark.parametrize('n', [1])\n"
        "def test_a(n):\n    assert f(n) == n\n"
    )
    assert oc.profile_regression(wide or {}, narrow or {}) == ["test_a (3 -> 1 assertions)"]


def test_an_uncountable_parametrize_set_cannot_inflate() -> None:
    """Deny-by-default on the unknown side: a non-literal argvalues counts as 1, never a guess.
    Otherwise `@parametrize('n', SOME_LIST)` would be an arbitrary inflation knob."""
    prof = oc.assertion_profile(
        "import pytest\n\n@pytest.mark.parametrize('n', CASES)\n"
        "def test_a(n):\n    assert f(n) == n\n"
    )
    assert prof == {"test_a": 1}


def test_stacked_parametrize_multiplies() -> None:
    prof = oc.assertion_profile(
        "import pytest\n\n"
        "@pytest.mark.parametrize('a', [1, 2])\n"
        "@pytest.mark.parametrize('b', [1, 2, 3])\n"
        "def test_a(a, b):\n    assert f(a, b)\n"
    )
    assert prof == {"test_a": 6}
