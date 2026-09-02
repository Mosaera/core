"""Unit tests for recon_all — the 8-dimension sweep with per-dimension failure isolation (#42)."""

from __future__ import annotations

from pathlib import Path

import pytest
from mosaera_core.recon import DIMENSION_NAMES, DimensionResult
from mosaera_core.recon import orchestrate as orch
from mosaera_core.recon.orchestrate import recon_all
from mosaera_core.tools.repo.workspace import Workspace


def _ws(tmp_path: Path, files: dict[str, str]) -> Workspace:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return Workspace(root=tmp_path, run_id="recon-test", branch="main")


def test_dimension_map_matches_the_canonical_names() -> None:
    # The orchestrator's fn map must cover exactly the eight canonical dimensions (and the store's
    # MAP_DIMENSIONS mirrors these — a drift would be rejected at upsert deny-by-default).
    assert set(orch._DIMENSIONS) == set(DIMENSION_NAMES)


def test_recon_all_produces_one_valid_result_per_dimension(tmp_path: Path) -> None:
    # A sweep returns exactly one valid tri-state result per dimension regardless of what the host
    # tools do (present → clean/finding, absent → unavailable) — eight results, never a crash.
    ws = _ws(tmp_path, {"README.md": "# hi\n", "pyproject.toml": "[project]\n"})
    results = recon_all(ws)  # no sandboxes → security/tests report unavailable honestly
    assert sorted(r.dimension for r in results) == sorted(DIMENSION_NAMES)
    assert all(isinstance(r, DimensionResult) for r in results)
    assert all(r.status in {"finding", "clean", "unavailable"} for r in results)


def test_one_raising_dimension_is_isolated_as_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A dimension that raises becomes unavailable (never a crash, never a false-clean, §5); the
    # other seven still land. Empty fingerprint ⇒ the store reads it stale and retries next sweep.
    def boom(_ws: Workspace, _ts: object, _ss: object) -> DimensionResult:
        raise RuntimeError("gitleaks blew up on a hostile repo")

    monkeypatch.setitem(orch._DIMENSIONS, "security", boom)
    results = {r.dimension: r for r in recon_all(_ws(tmp_path, {}))}
    assert len(results) == len(DIMENSION_NAMES)
    sec = results["security"]
    assert sec.status == "unavailable" and sec.fingerprint == ""
    assert sec.unavailable and "RuntimeError" in sec.unavailable[0]
    assert results["structure"].status in {"finding", "clean", "unavailable"}  # sibling unaffected
