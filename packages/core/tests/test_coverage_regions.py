"""The P1→P2 adapter (#29 P3): AST region extraction + dotted-label→nodeid normalization."""

from __future__ import annotations

from pathlib import Path

import mosaera_core.coverage_regions as cr
from mosaera_core.coveragemap import CoverageMap

_CALC = (
    "def add(a, b):\n"  # 1
    "    return a + b\n"  # 2
    "\n"  # 3
    "class Calc:\n"  # 4
    "    def mul(self, a, b):\n"  # 5
    "        return a * b\n"  # 6
)


def _is_test(f: str) -> bool:
    return f.startswith("tests/") or Path(f).name.startswith("test_")


def test_extract_regions_functions_methods_and_span() -> None:
    regs = {r.qualname: r for r in cr.extract_regions("pkg/calc.py", _CALC)}
    assert set(regs) == {"add", "Calc.mul"}  # module-level `class Calc:` body line is not a region
    assert (regs["add"].start, regs["add"].end) == (1, 2)
    assert (regs["Calc.mul"].start, regs["Calc.mul"].end) == (5, 6)
    assert regs["Calc.mul"].source == "    def mul(self, a, b):\n        return a * b"


def test_extract_regions_decorators_and_nesting() -> None:
    src = (
        "import functools\n"  # 1
        "\n"  # 2
        "@functools.cache\n"  # 3  decorator — part of the region span
        "def outer(x):\n"  # 4
        "    def inner(y):\n"  # 5
        "        return y\n"  # 6
        "    return inner\n"  # 7
    )
    regs = {r.qualname: r for r in cr.extract_regions("m.py", src)}
    assert set(regs) == {"outer", "outer.inner"}  # nested fn gets a dotted qualname
    assert regs["outer"].start == 3  # span starts at the decorator, not the `def`
    assert regs["outer"].end == 7


def test_extract_regions_syntax_error_is_empty() -> None:
    assert cr.extract_regions("bad.py", "def (:\n") == []


def _cmap() -> CoverageMap:
    # Mirrors a real `dynamic_context = test_function` run of _CALC's tests: dotted labels, and each
    # context also covers its own test file's lines (that's what disambiguates the nodeid).
    return CoverageMap(
        covered_lines={"pkg/calc.py": {2, 6}, "tests/test_calc.py": {5, 10}},
        tests_by_line={
            ("pkg/calc.py", 2): {"test_calc.test_add"},
            ("pkg/calc.py", 6): {"test_calc.TestCalc.test_mul"},
            ("tests/test_calc.py", 5): {"test_calc.test_add"},
            ("tests/test_calc.py", 10): {"test_calc.TestCalc.test_mul"},
        },
        lines_by_test={
            "test_calc.test_add": {("pkg/calc.py", 2), ("tests/test_calc.py", 5)},
            "test_calc.TestCalc.test_mul": {("pkg/calc.py", 6), ("tests/test_calc.py", 10)},
        },
    )


def test_context_nodeids_dotted_label_to_pytest_nodeid() -> None:
    got = cr._context_nodeids(_cmap(), _is_test)
    assert got == {
        "test_calc.test_add": "tests/test_calc.py::test_add",
        "test_calc.TestCalc.test_mul": "tests/test_calc.py::TestCalc::test_mul",
    }


def test_context_nodeids_ambiguous_testfile_is_skipped() -> None:
    # A label whose lines land in TWO test files can't be resolved from the label — skip it.
    m = CoverageMap(lines_by_test={"pkgx.test_f": {("tests/a_test.py", 1), ("tests/b_test.py", 1)}})
    assert cr._context_nodeids(m, _is_test) == {}


def test_regions_from_coverage_end_to_end() -> None:
    out = {
        r.region_key: r for r in cr.regions_from_coverage(_cmap(), {"pkg/calc.py": _CALC}, _is_test)
    }
    assert set(out) == {"pkg/calc.py::add", "pkg/calc.py::Calc.mul"}  # test file excluded
    assert out["pkg/calc.py::add"].covering_tests == ["tests/test_calc.py::test_add"]
    assert out["pkg/calc.py::Calc.mul"].covering_tests == ["tests/test_calc.py::TestCalc::test_mul"]
    # fingerprints reuse the memory contract (churn-stable normalized hash + raw rot hash)
    import mosaera_memory._fingerprint as fp

    add_src = "def add(a, b):\n    return a + b"
    assert out["pkg/calc.py::add"].source_hash == fp.source_hash(add_src)
    assert out["pkg/calc.py::add"].region_fingerprint == fp.region_fingerprint(add_src)


def test_regions_from_coverage_unreadable_source_skipped() -> None:
    # covered file with no source provided → skipped (not guessed), not an error
    assert cr.regions_from_coverage(_cmap(), {}, _is_test) == []


def test_regions_from_coverage_uncovered_region_omitted() -> None:
    # only `add` (line 2) is covered; Calc.mul is not → only add is emitted (deny-by-default)
    m = CoverageMap(
        covered_lines={"pkg/calc.py": {2}},
        tests_by_line={("pkg/calc.py", 2): {"test_calc.test_add"}},
        lines_by_test={"test_calc.test_add": {("pkg/calc.py", 2), ("tests/test_calc.py", 5)}},
    )
    out = cr.regions_from_coverage(m, {"pkg/calc.py": _CALC}, _is_test)
    assert [r.qualname for r in out] == ["add"]
