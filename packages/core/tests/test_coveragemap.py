"""Coverage primitive — pure parsing/mapping (oracle-make-real #29, P0).

The sandbox orchestration (`run_coverage`) needs `coverage` in the sandbox image (infra
prerequisite) so it's integration-tested later; these cover the deterministic host-side logic.
"""

from __future__ import annotations

from typing import Any

import mosaera_core.coveragemap as cm
from coverage import CoverageData


def test_changed_lines_parses_added_side() -> None:
    diff = (
        "diff --git a/pkg/mod.py b/pkg/mod.py\n"
        "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n"
        "@@ -1,3 +1,4 @@\n"
        " import os\n"  # context → line 1
        "-old = 1\n"  # removed → no new-side line
        "+new = 2\n"  # added → line 2
        "+extra = 3\n"  # added → line 3
        " done = 4\n"  # context → line 4
        "diff --git a/README.md b/README.md\n"
        "--- /dev/null\n+++ b/README.md\n"
        "@@ -0,0 +1 @@\n"
        "+hi\n"  # added → line 1
    )
    assert cm.changed_lines(diff) == {"pkg/mod.py": {2, 3}, "README.md": {1}}


def test_changed_lines_deletion_only_file_is_invisible() -> None:
    # A pure deletion emits `+++ /dev/null` (not `+++ b/…`), so no added-side lines — matches the
    # diff-parser's known limitation (deletions are handled elsewhere via the old-side scan).
    diff = "--- a/pkg/gone.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-a = 1\n-b = 2\n"
    assert cm.changed_lines(diff) == {}


def test_parse_contexts_counts_only_test_contexts(tmp_path: Any) -> None:
    data = CoverageData()
    data.set_context("tests/test_m.py::test_add")
    data.add_lines({"pkg/mod.py": [10, 11]})
    data.set_context("")  # import-time only — must NOT count as tested
    data.add_lines({"pkg/mod.py": [1]})

    m = cm.parse_contexts(data, tmp_path)
    assert m.covered_lines == {"pkg/mod.py": {10, 11}}  # line 1 (empty ctx only) excluded
    assert m.tests_by_line[("pkg/mod.py", 10)] == {"tests/test_m.py::test_add"}
    assert m.lines_by_test["tests/test_m.py::test_add"] == {
        ("pkg/mod.py", 10),
        ("pkg/mod.py", 11),
    }


def test_covered_uncovered_splits_changed_lines() -> None:
    m = cm.CoverageMap(covered_lines={"pkg/mod.py": {10, 11}})
    covered, uncovered = cm.covered_uncovered(m, {"pkg/mod.py": {10, 12}})
    assert covered == {"pkg/mod.py": {10}}
    assert uncovered == {"pkg/mod.py": {12}}


# --- change_is_covered — the gate verdict (#29 P1) ---


def test_change_is_covered_all_executable_lines_covered() -> None:
    m = cm.CoverageMap(covered_lines={"a.py": {10, 11}}, executable_lines={"a.py": {10, 11, 12}})
    assert cm.change_is_covered(m, {"a.py": {10, 11}}) is True


def test_change_is_covered_uncovered_executable_line_is_false() -> None:
    m = cm.CoverageMap(covered_lines={"a.py": {10}}, executable_lines={"a.py": {10, 12}})
    assert cm.change_is_covered(m, {"a.py": {10, 12}}) is False  # 12 executable, changed, uncovered


def test_change_is_covered_unmeasured_file_is_false() -> None:
    # THE F1 case: feature.py changed but no test runs it → coverage never measured it → uncovered
    m = cm.CoverageMap(covered_lines={"other.py": {1}}, executable_lines={"other.py": {1}})
    assert cm.change_is_covered(m, {"feature.py": {5}}) is False


def test_change_is_covered_non_executable_changed_line_ignored() -> None:
    # line 13 is a comment (not executable) → not held against coverage
    m = cm.CoverageMap(covered_lines={"a.py": {10}}, executable_lines={"a.py": {10}})
    assert cm.change_is_covered(m, {"a.py": {10, 13}}) is True


def test_change_is_covered_no_py_source_is_none() -> None:
    # docs/config-only change → coverage is moot → None (caller falls back to the heuristic)
    assert cm.change_is_covered(cm.CoverageMap(), {"README.md": {1}, "flags.json": {2}}) is None


# --- red-team round-1 regressions (ADR-0049) ---


def test_changed_lines_added_content_starting_with_plusplus() -> None:
    # Finding A3: an added CONTENT line whose text starts with `++` becomes diff line `+++…`. The
    # old header filter dropped it AND withheld its new-side number, mis-numbering the rest.
    diff = (
        "diff --git a/m.py b/m.py\n"
        "--- a/m.py\n+++ b/m.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+++premium = compute()\n"  # added content `++premium…` → line 1 (was dropped)
        "+danger = wipe_disk()\n"  # added → line 2 (was mis-numbered to 1)
    )
    assert cm.changed_lines(diff) == {"m.py": {1, 2}}


def test_changed_lines_added_content_starting_with_plusplus_space() -> None:
    # Finding A3 round 2: `++ danger()` is valid Python; its diff line is `+++ danger()` WITH a
    # space, so a "require a space" header filter STILL drops it. Only `+++ /dev/null` is a real
    # `+++ ` header that reaches the filter, so we match that exactly.
    diff = (
        "--- a/m.py\n+++ b/m.py\n"
        "@@ -1 +1,3 @@\n"
        " a = 0\n"  # context → line 1
        "+++ danger()\n"  # added content `++ danger()` → line 2 (was dropped)
        "+after = 1\n"  # added → line 3 (was mis-numbered to 2)
    )
    assert cm.changed_lines(diff) == {"m.py": {2, 3}}


def test_coveragerc_names_never_clobber_a_repo_config() -> None:
    # Finding B2: run_coverage uses UNIQUE names, never the repo's own `.coveragerc`/`.coverage`.
    assert cm._RCFILE not in (".coveragerc", "")
    assert cm._DATAFILE not in (".coverage", "")
    assert (
        f"data_file = {cm._DATAFILE}" in cm._COVERAGERC
    )  # data written to our file, not the repo's


def test_read_coverage_data_fills_executable_lines_from_any_cwd(tmp_path: Any) -> None:
    # Finding B1: analysis2 must resolve source against the WORKSPACE root, not the host process cwd
    # (which is never the run workspace in production). Build a REAL coverage data file by running a
    # suite under coverage in tmp_path, then read it while the host cwd is elsewhere (this test's
    # cwd = the repo, exactly the B1 condition) — executable_lines must still populate, not silently
    # empty (which would make change_is_covered park every tested change).
    import os
    import subprocess
    import sys

    root = tmp_path
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_calc.py").write_text(
        "from pkg.calc import add\n\n\ndef test_add() -> None:\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    (root / cm._RCFILE).write_text(cm._COVERAGERC, encoding="utf-8")
    proc = subprocess.run(  # noqa: S603 — trusted: this interpreter + fixed argv, no user input
        [sys.executable, "-m", "coverage", "run", f"--rcfile={cm._RCFILE}", "-m", "pytest", "-q"],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    datafile = root / cm._DATAFILE
    assert datafile.exists()

    cmap = cm.read_coverage_data(root, datafile)  # host cwd = repo, NOT root — the B1 condition
    assert cmap.executable_lines.get("pkg/calc.py"), "executable_lines empty → B1 regression"
    assert 2 in cmap.executable_lines["pkg/calc.py"]  # `return a + b` is executable
    assert cmap.covered_lines.get("pkg/calc.py") == {2}  # the return ran under test_add
    # end-to-end: the genuinely-tested changed line is credited, not parked
    assert cm.change_is_covered(cmap, {"pkg/calc.py": {2}}) is True
