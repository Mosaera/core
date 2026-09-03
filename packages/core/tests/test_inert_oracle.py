"""Approach B — the ENGINE authors the oracle for a certified non-behavioural change (#118).

B shares A's classifier (`test_task_scale.py`) and differs in the treatment: no node is skipped, so
every control that reads `authored_tests` keeps working. What changes is WHO writes the acceptance
test — the engine, deterministically, instead of the Proctor spending a model call inventing one
for behaviour that by definition is not changing.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from mosaera_core.graph.nodes_plan import route_after_plan
from mosaera_core.inert_scaffold import scaffold_if_inert

_SRC = '''"""A module."""

import os

MAX = 10


def render(rows):
    return ",".join(rows)


def _helper():
    return 1


class Report:
    pass
'''


def _ws(tmp_path: Path) -> Any:
    # `src` is a real PACKAGE here (it carries __init__.py). Since red-team B-1 the scaffold
    # declines a path it cannot prove is importable, and a bare `src/` directory is a source-root
    # layout, not a package -- `test_a_src_layout_module_is_declined` covers that shape.
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "report.py").write_text(_SRC, encoding="utf-8")
    return SimpleNamespace(root=tmp_path)


def test_B_keeps_the_full_spine() -> None:
    """The load-bearing difference from A. B must NOT skip design/author_tests — the lane selects
    a deterministic oracle inside the node, it does not route around it."""
    ctx: Any = SimpleNamespace(settings=SimpleNamespace(reduced_lane=True))
    assert route_after_plan(ctx, {"lane": "reduced"}) == "design"  # type: ignore[arg-type]


def test_the_engine_authors_an_import_and_surface_oracle(tmp_path: Path) -> None:
    written = scaffold_if_inert(_ws(tmp_path), enabled=True, certified_paths=("src/report.py",))
    assert written == ["tests/test_inert_src_report.py"]
    body = (tmp_path / "tests" / "test_inert_src_report.py").read_text()
    assert "importlib.import_module('src.report')" in body.replace('"', "'")
    # Public surface only: `_helper` is private and must not be pinned, or every internal rename
    # would read as a behaviour change and the oracle would cry wolf.
    assert "'MAX'" in body.replace('"', "'")
    assert "'render'" in body.replace('"', "'")
    assert "'Report'" in body.replace('"', "'")
    assert "_helper" not in body


def test_it_declines_rather_than_guessing(tmp_path: Path) -> None:
    """Deny-by-default, the same contract `scaffold_if_refactor` holds: anything it cannot pin
    confidently returns [] and the Proctor authors as usual. A scaffold bug must never break a run.
    """
    ws = _ws(tmp_path)
    assert scaffold_if_inert(ws, enabled=False, certified_paths=("src/report.py",)) == []
    assert scaffold_if_inert(ws, enabled=True, certified_paths=()) == []
    assert scaffold_if_inert(ws, enabled=True, certified_paths=("README.md",)) == []
    assert scaffold_if_inert(ws, enabled=True, certified_paths=("a.py", "b.py")) == []


def test_an_already_broken_file_is_not_pinned(tmp_path: Path) -> None:
    """Snapshotting an unparseable module would freeze the breakage into the acceptance bar and
    fail every subsequent run for the wrong reason."""
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "report.py").write_text("def broken(:\n", encoding="utf-8")
    assert (
        scaffold_if_inert(
            SimpleNamespace(root=tmp_path), enabled=True, certified_paths=("src/report.py",)
        )
        == []
    )


def test_a_package_init_is_declined(tmp_path: Path) -> None:
    """`__init__.py` maps to the PACKAGE, not a module, so the snapshot would pin the wrong
    surface — and re-exports make that surface unstable for reasons unrelated to the change."""
    (tmp_path / "pkg").mkdir(parents=True)
    (tmp_path / "pkg" / "__init__.py").write_text("X = 1\n", encoding="utf-8")
    assert (
        scaffold_if_inert(
            SimpleNamespace(root=tmp_path), enabled=True, certified_paths=("pkg/__init__.py",)
        )
        == []
    )


def test_the_delivery_gate_is_not_taught_a_new_reason() -> None:
    """Same claim as A, and it must hold for B too: `packages/policies` byte-identical means the
    acceptance class provably did not widen. B additionally only ever ADDS an assertion, so it can
    refuse more and never less."""
    import inspect

    from mosaera_policies import gate

    src = inspect.getsource(gate)
    for token in ("lane", "inert_oracle", "scaffold_if_inert"):
        assert token not in src, f"{token!r} reached the delivery gate — the boundary moved"


# --- RED-TEAM B-1: the module path must be PROVABLY importable ---------------------------------


def test_a_src_layout_module_is_declined(tmp_path: Path) -> None:
    """THE B-1 TRIPWIRE. `src/` as a source ROOT (no __init__.py) means `src.report` does not
    import — the authored oracle would fail for a reason unrelated to the change and EVERY lane run
    would park. Declining costs one Proctor pass; guessing costs the whole run."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "report.py").write_text(_SRC, encoding="utf-8")
    assert (
        scaffold_if_inert(
            SimpleNamespace(root=tmp_path), enabled=True, certified_paths=("src/report.py",)
        )
        == []
    )


def test_a_real_package_is_accepted(tmp_path: Path) -> None:
    """The other provable shape: every parent carries __init__.py, so the dotted path IS the module
    path. Checked on disk, never assumed from the path string."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "report.py").write_text(_SRC, encoding="utf-8")
    written = scaffold_if_inert(
        SimpleNamespace(root=tmp_path), enabled=True, certified_paths=("pkg/report.py",)
    )
    assert written == ["tests/test_inert_pkg_report.py"]
    body = (tmp_path / "tests" / "test_inert_pkg_report.py").read_text().replace('"', "'")
    assert "import_module('pkg.report')" in body


def test_a_root_level_module_is_accepted(tmp_path: Path) -> None:
    """The shape every bench case happens to use — which is exactly why the A/B never exercised
    B-1, and why this file has to cover the other two rather than trusting the sweep."""
    (tmp_path / "ledger.py").write_text(_SRC, encoding="utf-8")
    written = scaffold_if_inert(
        SimpleNamespace(root=tmp_path), enabled=True, certified_paths=("ledger.py",)
    )
    assert written == ["tests/test_inert_ledger.py"]


def test_a_partially_packaged_path_is_declined(tmp_path: Path) -> None:
    """`a/b/mod.py` where `a` is a package but `b` is not: the dotted path is a fiction. Every
    parent must prove itself, not just the first."""
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "a" / "b" / "mod.py").write_text(_SRC, encoding="utf-8")
    assert (
        scaffold_if_inert(
            SimpleNamespace(root=tmp_path), enabled=True, certified_paths=("a/b/mod.py",)
        )
        == []
    )
