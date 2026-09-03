"""Hidden acceptance suite for MCB-27 (remove the dead legacy exporter).

Ground truth — never shown to the agent, injected at grade time. A subtract case needs a grader
shaped differently from every other case in the corpus: the deliverable is an ABSENCE, so the suite
asserts on the source tree, not only on behaviour.

Both directions are graded, because both failures are real:
  * the dead thing must be GONE — from the module, the re-export, and any other reference;
  * the live thing must SURVIVE — `render_row` looks similar and the CLI depends on it, so a run
    that removes the wrong function must fail even though the package still imports.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_PKG = Path("reporting")


def _sources() -> list[Path]:
    return sorted(_PKG.rglob("*.py"))


def test_the_package_still_imports() -> None:
    import reporting  # noqa: F401


def test_the_live_function_survives_unchanged() -> None:
    from reporting.exporters import render_row

    assert render_row(["ab", "cdefghijklmnop"], width=4) == "ab   | cdef"


def test_the_live_caller_still_works() -> None:
    from reporting.cli import report

    assert report([["a"], ["b"]]).count("\n") == 1


def test_the_dead_function_is_gone_from_the_module() -> None:
    tree = ast.parse((_PKG / "exporters.py").read_text(encoding="utf-8"))
    defined = {
        n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    assert "legacy_export" not in defined, "the dead exporter is still defined"


def test_the_dead_re_export_is_gone() -> None:
    src = (_PKG / "__init__.py").read_text(encoding="utf-8")
    assert "legacy_export" not in src, "the dead re-export survived"


def test_it_is_no_longer_importable() -> None:
    with pytest.raises(ImportError):
        from reporting import legacy_export  # noqa: F401


def test_nothing_in_the_package_references_it() -> None:
    """The proof obligation the whole slice is about: no live reference anywhere."""
    offenders = []
    for path in _sources():
        if "legacy_export" in path.read_text(encoding="utf-8"):
            offenders.append(path.as_posix())
    assert not offenders, f"`legacy_export` is still referenced by: {offenders}"
