"""The #53 demo-repo materialize helper produces the right git repos (offline)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from git import Repo

_HELPER = Path(__file__).resolve().parents[3] / "demos" / "materialize.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("demos_materialize", _HELPER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tracked(dest: Path) -> set[str]:
    return set(Repo(dest).git.ls_files().split())


def test_greenfield_is_an_empty_repo(tmp_path: Path) -> None:
    # No commit → clone has no valid HEAD → the greenfield scaffold trigger.
    dest = _load().materialize("greenfield", tmp_path / "gf")
    assert not Repo(dest).head.is_valid()


def test_brownfield_carries_the_root_out_of_scope_test(tmp_path: Path) -> None:
    dest = _load().materialize("brownfield", tmp_path / "bf")
    tracked = _tracked(dest)
    assert "test_invariants.py" in tracked  # the ROOT out-of-scope test (the #45 point)
    assert "tests/test_inventory.py" in tracked  # the in-scope suite
    assert "BRIEF.md" not in tracked and "EXPECTED.md" not in tracked  # metadata excluded


def test_spaghetti_has_source_but_no_tests(tmp_path: Path) -> None:
    dest = _load().materialize("spaghetti", tmp_path / "sp")
    tracked = _tracked(dest)
    assert "report.py" in tracked
    assert not any("test" in t for t in tracked)  # no tests → shallow oracle path


def test_unknown_shape_is_rejected(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(SystemExit):
        _load().materialize("bogus", tmp_path / "x")
