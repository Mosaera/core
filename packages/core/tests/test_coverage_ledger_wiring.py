"""test_node → durable ledger write-wiring (#29 P3): `persist_coverage_ledger`.

The full path (a real coverage run → a real Postgres ledger) is DB-gated integration; here we drive
the glue with a fake store + a real tmp workspace to prove region persistence + the deny-by-default
guards (no store / no project / unreadable source), without a database."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from mosaera_core.coveragemap import CoverageMap
from mosaera_core.graph._coverage_ledger import persist_coverage_ledger

_CALC = (
    "def add(a, b):\n"
    "    return a + b\n"
    "\n"
    "class Calc:\n"
    "    def mul(self, a, b):\n"
    "        return a * b\n"
)


def _cmap() -> CoverageMap:
    return CoverageMap(
        covered_lines={"pkg/calc.py": {2, 6}, "tests/test_calc.py": {5, 10}},
        tests_by_line={
            ("pkg/calc.py", 2): {"test_calc.test_add"},
            ("pkg/calc.py", 6): {"test_calc.TestCalc.test_mul"},
        },
        lines_by_test={
            "test_calc.test_add": {("pkg/calc.py", 2), ("tests/test_calc.py", 5)},
            "test_calc.TestCalc.test_mul": {("pkg/calc.py", 6), ("tests/test_calc.py", 10)},
        },
    )


class _FakeMemory:
    def __init__(self, project_id: str | None) -> None:
        self._pid = project_id
        self.upserts: list[tuple[str, str, tuple[str, ...]]] = []

    def get_run(self, run_id: str) -> Any:
        return SimpleNamespace(project_id=self._pid) if self._pid is not None else None

    def upsert_coverage_region(
        self,
        project_id: str,
        region_key: str,
        *,
        region_fingerprint: str,
        source_hash: str,
        covering_tests: Any,
    ) -> None:
        self.upserts.append((project_id, region_key, tuple(covering_tests)))


def _ctx(tmp_path: Any, memory: Any) -> Any:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "calc.py").write_text(_CALC, encoding="utf-8")
    return SimpleNamespace(memory=memory, run_id="r1", workspace=SimpleNamespace(root=tmp_path))


def test_persist_writes_regions_for_the_project(tmp_path: Any) -> None:
    mem = _FakeMemory("proj1")
    persist_coverage_ledger(_ctx(tmp_path, mem), _cmap())
    got = {rk: (pid, tests) for (pid, rk, tests) in mem.upserts}
    assert set(got) == {"pkg/calc.py::add", "pkg/calc.py::Calc.mul"}  # test file excluded
    assert got["pkg/calc.py::add"] == ("proj1", ("tests/test_calc.py::test_add",))
    assert got["pkg/calc.py::Calc.mul"] == ("proj1", ("tests/test_calc.py::TestCalc::test_mul",))


def test_persist_skips_when_no_project(tmp_path: Any) -> None:
    # get_run → None (a headless / no-project run): nothing to compound against → no writes.
    mem = _FakeMemory(None)
    persist_coverage_ledger(_ctx(tmp_path, mem), _cmap())
    assert mem.upserts == []


def test_persist_skips_when_no_memory(tmp_path: Any) -> None:
    ctx: Any = SimpleNamespace(memory=None, run_id="r1", workspace=SimpleNamespace(root=tmp_path))
    persist_coverage_ledger(ctx, _cmap())  # no store → no-op, no raise


def test_persist_skips_unreadable_source(tmp_path: Any) -> None:
    # pkg/calc.py never written → its source is unreadable → those regions are skipped, not guessed.
    mem = _FakeMemory("proj1")
    ctx: Any = SimpleNamespace(memory=mem, run_id="r1", workspace=SimpleNamespace(root=tmp_path))
    persist_coverage_ledger(ctx, _cmap())
    assert mem.upserts == []


def test_persist_swallows_get_run_db_fault(tmp_path: Any) -> None:
    # Holistic red-team B-1: a transient DB fault must NOT propagate — a ledger blip never crashes
    # a green run into status='error'. get_run raising → warn + skip, no exception out of the node.
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "calc.py").write_text(_CALC, encoding="utf-8")

    class _GetRunRaises:
        def get_run(self, run_id: str) -> Any:
            raise RuntimeError("db pool timeout")

        def upsert_coverage_region(self, *a: Any, **k: Any) -> None:
            raise AssertionError("unreachable — get_run failed first")

    ctx: Any = SimpleNamespace(
        memory=_GetRunRaises(), run_id="r1", workspace=SimpleNamespace(root=tmp_path)
    )
    persist_coverage_ledger(ctx, _cmap())  # must NOT raise


def test_persist_swallows_upsert_db_fault(tmp_path: Any) -> None:
    # Same, for a fault mid-write (integrity error / deadlock) after get_run succeeded.
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "calc.py").write_text(_CALC, encoding="utf-8")

    class _UpsertRaises:
        def get_run(self, run_id: str) -> Any:
            return SimpleNamespace(project_id="proj1")

        def upsert_coverage_region(self, *a: Any, **k: Any) -> None:
            raise RuntimeError("unique violation")

    ctx: Any = SimpleNamespace(
        memory=_UpsertRaises(), run_id="r1", workspace=SimpleNamespace(root=tmp_path)
    )
    persist_coverage_ledger(ctx, _cmap())  # must NOT raise
