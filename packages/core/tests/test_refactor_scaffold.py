"""The deterministic refactor-oracle scaffold (ADR-0066 follow-up).

Generality is the point: the scaffold is exercised on a SYNTHETIC module (not an MCB case) — it
detects the target by import, extracts literal inputs from the existing test, mutates with generic
numeric boundaries + the signature's optional param, and the generated oracle REDS on the
un-refactored seed (structural) and GREENS on any correct decomposition (behaviour + structure).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from mosaera_core.refactor_scaffold import (
    _literal_calls,
    _mutations,
    _params,
    scaffold_if_refactor,
    scaffold_refactor_oracle,
)

_SEED = (
    "def total(nums, scale=1):\n"
    "    s = 0\n"
    "    for n in nums:\n"
    "        if n < 0:\n"
    "            raise ValueError('negative')\n"
    "        s += n * scale\n"
    "    return s\n"
)
_DECOMPOSED = (
    "def _scaled(n, scale):\n"
    "    if n < 0:\n"
    "        raise ValueError('negative')\n"
    "    return n * scale\n\n"
    "def _sum(nums, scale):\n"
    "    return sum(_scaled(n, scale) for n in nums)\n\n"
    "def total(nums, scale=1):\n"
    "    return _sum(nums, scale)\n"
)
_EXISTING_TEST = "from calc import total\n\ndef test_it():\n    assert total([1, 2, 3]) == 6\n"


def _bare(root: Path) -> Any:
    return SimpleNamespace(root=root)


def _ws(root: Path, module_src: str) -> Any:
    (root / "calc.py").write_text(module_src, encoding="utf-8")
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_calc.py").write_text(_EXISTING_TEST, encoding="utf-8")
    return SimpleNamespace(root=root)


def test_authors_frozen_copy_and_differential_test(tmp_path: Path) -> None:
    ws = _ws(tmp_path, _SEED)
    written = scaffold_refactor_oracle(ws, ["tests/test_calc.py"])
    assert written == ["tests/_frozen_calc.py", "tests/test_refactor_golden_calc.py"]
    # the frozen copy is a verbatim snapshot of the original
    assert (tmp_path / "tests" / "_frozen_calc.py").read_text() == _SEED
    gen = (tmp_path / "tests" / "test_refactor_golden_calc.py").read_text()
    assert "test_behaviour_is_preserved" in gen and "test_decomposition_happened" in gen
    assert "_frozen_calc.py" in gen  # loads the frozen copy by path


def test_scaffold_overwrites_a_preplanted_oracle(tmp_path: Path) -> None:
    # ADR-0068 red-team FN1 (HIGH): the oracle's paths are seed-PREDICTABLE and repo content is
    # UNTRUSTED, so the scaffold must NEVER adopt a pre-existing file at its target path — a
    # skip-if-exists let an attacker pre-plant a WEAK test that became the engine's oracle. `_write`
    # OVERWRITES: the strong differential always clobbers the plant.
    ws = _ws(tmp_path, _SEED)
    planted = tmp_path / "tests" / "test_refactor_golden_calc.py"  # the scaffold's predictable path
    planted.write_text(
        "def test_nothing():\n    assert True\n", encoding="utf-8"
    )  # neutered oracle
    written = scaffold_refactor_oracle(ws, ["tests/test_calc.py"])
    assert "tests/test_refactor_golden_calc.py" in written
    body = planted.read_text(encoding="utf-8")
    assert "test_nothing" not in body  # the plant was CLOBBERED
    assert "test_behaviour_is_preserved" in body  # the real strong oracle was written over it


def _run_generated(root: Path) -> tuple[int, str]:
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_refactor_golden_calc.py",
            "-p",
            "no:cacheprovider",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return r.returncode, r.stdout


def test_generated_oracle_reds_on_seed(tmp_path: Path) -> None:
    # The un-refactored seed has ONE module-level function → the decomposition check FAILS (red
    # phase), while the behaviour cases pass (the seed IS the frozen original). A valid test-first
    # oracle: it cannot be satisfied by doing nothing.
    ws = _ws(tmp_path, _SEED)
    scaffold_refactor_oracle(ws, ["tests/test_calc.py"])
    code, out = _run_generated(tmp_path)
    assert code != 0
    assert "test_decomposition_happened" in out  # that is the failing one
    assert "test_behaviour_is_preserved" not in out.split("FAILED")[-1] or "passed" in out


def test_generated_oracle_greens_on_a_correct_decomposition(tmp_path: Path) -> None:
    # Author from the seed, then swap in a CORRECT decomposition (different helper names) — the
    # oracle must go fully green: behaviour preserved across all generated inputs + decomposition
    # happened. Name-agnostic (helpers are `_scaled`/`_sum`, never pinned).
    ws = _ws(tmp_path, _SEED)
    scaffold_refactor_oracle(ws, ["tests/test_calc.py"])
    (tmp_path / "calc.py").write_text(_DECOMPOSED, encoding="utf-8")  # the coder's refactor
    code, out = _run_generated(tmp_path)
    assert code == 0, out
    assert "passed" in out


def test_generated_oracle_catches_a_behaviour_change(tmp_path: Path) -> None:
    # A refactor that CHANGES behaviour (scales wrong) must be caught by the differential across
    # generated inputs — this is what makes it a real oracle, not a tautology.
    ws = _ws(tmp_path, _SEED)
    scaffold_refactor_oracle(ws, ["tests/test_calc.py"])
    broken = (
        "def _scaled(n, scale):\n    return n * scale * 2\n\n"  # wrong: doubles
        "def _sum(nums, scale):\n    return sum(_scaled(n, scale) for n in nums)\n\n"
        "def total(nums, scale=1):\n    return _sum(nums, scale)\n"
    )
    (tmp_path / "calc.py").write_text(broken, encoding="utf-8")
    code, _ = _run_generated(tmp_path)
    assert code != 0  # the differential behaviour test fails on the wrong output


def test_deny_by_default(tmp_path: Path) -> None:
    # No existing test importing a local module → nothing to diff against → author nothing (falls
    # back to the Proctor). Never a broken/empty oracle.
    (tmp_path / "calc.py").write_text(_SEED, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    assert scaffold_refactor_oracle(_bare(tmp_path), []) == []
    # existing test but NON-literal inputs (a fixture) → cannot replay → no-op
    (tmp_path / "tests" / "test_x.py").write_text(
        "from calc import total\ndef test_it(sample):\n    assert total(sample) >= 0\n", "utf-8"
    )
    assert scaffold_refactor_oracle(_bare(tmp_path), ["tests/test_x.py"]) == []


def test_scaffold_if_refactor_gating(tmp_path: Path) -> None:
    ws = _ws(tmp_path, _SEED)
    tests = ["tests/test_calc.py"]
    refactor = "Refactor total without changing behaviour."
    # refactor task + enabled → authors
    assert scaffold_if_refactor(
        ws, enabled=True, task=refactor, plan="", design="", existing_tests=tests
    )
    # disabled → no-op
    assert (
        scaffold_if_refactor(
            ws, enabled=False, task=refactor, plan="", design="", existing_tests=tests
        )
        == []
    )
    # not a refactor task → no-op even when enabled
    assert (
        scaffold_if_refactor(
            ws, enabled=True, task="Add a --verbose flag.", plan="", design="", existing_tests=tests
        )
        == []
    )


def test_scaffold_never_arms_from_the_pm_paraphrase(tmp_path: Path) -> None:
    # The MCB-11 live misfire: a FEATURE task whose trusted brief does NOT match the preservation
    # patterns, while the PM's lossy plan/design paraphrase ("keep the existing behaviour
    # unchanged") DOES. Arming must read the trusted task ONLY — the paraphrase never arms the
    # scaffold (ADR-0066's trusted-spec contract; the ADR-0072 live-drive false-positive class).
    ws = _ws(tmp_path, _SEED)
    tests = ["tests/test_calc.py"]
    feature = (
        "Add `*` and `/` with correct precedence. Keep the existing `+`/`-` behaviour unchanged."
    )
    paraphrase = "keep the existing behaviour unchanged"
    assert (
        scaffold_if_refactor(
            ws, enabled=True, task=feature, plan=paraphrase, design="", existing_tests=tests
        )
        == []
    )
    assert (
        scaffold_if_refactor(
            ws, enabled=True, task=feature, plan="", design=paraphrase, existing_tests=tests
        )
        == []
    )
    # A REAL refactor task still arms on the task alone (plan/design not needed and not consulted).
    assert scaffold_if_refactor(
        ws,
        enabled=True,
        task="Refactor total without changing behaviour.",
        plan="",
        design="",
        existing_tests=tests,
    )


def test_mutations_cover_boundaries_and_optional_params() -> None:
    # example: total([1,2,3]) with an optional `scale` param (default 1).
    cases = _mutations([[1, 2, 3]], _params_of("def total(nums, scale=1): pass"))
    kwargs_seen = {tuple(sorted(k.items())) for _, k in cases}
    assert any("scale" in k for k in (dict(t) for t in kwargs_seen))  # optional param varied
    # numeric leaves swapped to boundaries (e.g. a 10 appears to cross a >=10 branch)
    flat = {n for args, _ in cases for lst in args if isinstance(lst, list) for n in lst}
    assert 10 in flat and 0 in flat


def test_literal_calls_only_extracts_literal_args() -> None:
    src = (
        "from calc import total\n"
        "def test_a():\n    assert total([1, 2]) == 3\n"
        "def test_b(x):\n    assert total(x) == 0\n"  # non-literal arg → skipped
    )
    calls = _literal_calls([src], {"total"})
    assert calls == {"total": [[[1, 2]]]}


import ast  # noqa: E402 - used only by the tiny helper below


def _params_of(fn_src: str) -> list[tuple[str, Any]]:
    return _params(ast.parse(fn_src).body[0].args)  # type: ignore[attr-defined]


# --- #62: source-mined boundaries + type confusions (the MCB-14 survivor's killers) ----------


def test_mined_boundaries_are_source_derived_triples() -> None:
    from mosaera_core.input_mining import mined_boundaries as _mined_boundaries

    # A module whose guard limits the generic set cannot reach (no negatives, nothing > 100).
    src = (
        "def f(age):\n    if age < 0 or age > 150:\n"
        "        raise ValueError('bad')\n    return age\n"
    )
    mined = _mined_boundaries(src)
    assert -1 in mined and 151 in mined and 149 in mined  # the off-by-one triples that reach it
    assert all(isinstance(v, int) for v in mined)
    assert _mined_boundaries("def broken(:") == ()  # unparseable → no claim


def test_type_confusions_cover_the_guard_families() -> None:
    from mosaera_core.refactor_scaffold import _type_confusions

    got = _type_confusions(["alice", 30])
    assert ["alice", True] in got  # bool-in-int, the classic isinstance guard
    assert ["", 30] in got  # empty string
    assert ["alice", "30"] in got  # stringified number
    assert ["alice", None] in got
    # one variant per arg per family — never a cross-product
    assert not any(v[0] != "alice" and v[1] != 30 for v in got)


_MISSING_SENTINEL = object()


def test_targeted_cases_survive_the_cap() -> None:
    # ADR-0081 liveness: the control must be able to FIRE — targeted cases are ordered before
    # the generic boundary flood, so the cap can never evict them (the file's own ordering rule).
    from mosaera_core.refactor_scaffold import _mutations

    variants = _mutations(
        ["alice", 30], [("name", _MISSING_SENTINEL), ("age", _MISSING_SENTINEL)], (-1, 151)
    )
    flat = [v[0] for v in variants]
    assert ["alice", -1] in flat and ["alice", 151] in flat
    assert ["alice", True] in flat


def test_golden_oracle_kills_the_deleted_validation_mutant(tmp_path: Path) -> None:
    """The measured MCB-14 survivor (#60 wall, leg 3): a mutant that DELETES the shared
    validation call from a caller. Every previously-generated input was valid, so nothing
    reached a raise and the mutant survived both the suite and the differential. With
    source-mined boundaries the golden oracle reaches the branch and kills it.

    Models the REAL sequence: scaffold authors on the un-refactored seed, the coder delivers
    the decomposition, then the mutant is applied to the delivered code.
    """
    seed = tmp_path / "acct.py"
    seed.write_text(  # pre-refactor: validation inline, duplicated
        "def create_user(name, age):\n"
        "    if not isinstance(name, str) or not name:\n"
        "        raise ValueError('name')\n"
        "    if age < 0 or age > 150:\n"
        "        raise ValueError('age')\n"
        "    return {'action': 'create', 'name': name, 'age': age}\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_acct.py").write_text(
        "from acct import create_user\n\n\n"
        "def test_ok():\n"
        "    assert create_user('alice', 30)['age'] == 30\n",
        encoding="utf-8",
    )
    written = scaffold_refactor_oracle(_bare(tmp_path), ["tests/test_acct.py"])
    assert written, "the scaffold must author for this shape"

    def run() -> int:
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "tests/", "-p", "no:cacheprovider"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        ).returncode

    refactored = (
        "def _validate(name, age):\n"
        "    if not isinstance(name, str) or not name:\n"
        "        raise ValueError('name')\n"
        "    if age < 0 or age > 150:\n"
        "        raise ValueError('age')\n\n\n"
        "def create_user(name, age):\n"
        "    _validate(name, age)\n"
        "    return {'action': 'create', 'name': name, 'age': age}\n"
    )
    seed.write_text(refactored, encoding="utf-8")
    assert run() == 0, "the correct refactor must stay green (no false park)"

    # The survivor: delete the validation call from the caller.
    seed.write_text(
        refactored.replace("    _validate(name, age)\n", "    pass\n"), encoding="utf-8"
    )
    assert run() != 0, "the deleted-validation mutant must now be KILLED"
