"""Unit tests for the recon daemon's DimensionResult→map adapter + failure handling (#42).

Docker-free: ``recon_all``, the workspace open, and the sandbox factory are monkeypatched, so these
cover the mapping + the transient running/error overlay without a daemon.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from mosaera_api import recon as recon_mod
from mosaera_core.recon import DimensionResult, Observation


class _FakeMemory:
    """Records upsert_map_dimension calls (matches the store's signature)."""

    def __init__(self) -> None:
        self.upserts: list[dict[str, Any]] = []

    def upsert_map_dimension(
        self,
        project_id: str,
        dimension: str,
        *,
        status: str,
        fingerprint: str | None = None,
        observations: Any = (),
        unavailable_reason: str = "",
    ) -> None:
        self.upserts.append(
            {
                "project_id": project_id,
                "dimension": dimension,
                "status": status,
                "fingerprint": fingerprint,
                "observations": list(observations),
                "unavailable_reason": unavailable_reason,
            }
        )


def _results() -> list[DimensionResult]:
    return [
        DimensionResult.clean("deps", "fp-deps"),
        DimensionResult.finding(
            "security",
            "fp-sec",
            [Observation(text="AWS key pattern", provenance="prod.env:4", severity="critical")],
        ),
        DimensionResult.could_not_run("tests", "", ["no sandbox"]),
    ]


def test_run_recon_maps_each_dimension_to_the_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    mem = _FakeMemory()
    monkeypatch.setattr(
        recon_mod, "open_project_workspace", lambda *a, **k: SimpleNamespace(root=tmp_path)
    )
    monkeypatch.setattr(recon_mod, "_open_sandbox", lambda *a, **k: None)
    monkeypatch.setattr(recon_mod, "recon_all", lambda *a, **k: _results())

    recon_mod.run_recon(mem, "proj-1")  # type: ignore[arg-type]

    by_dim = {u["dimension"]: u for u in mem.upserts}
    assert set(by_dim) == {"deps", "security", "tests"}
    assert by_dim["deps"]["status"] == "clean" and by_dim["deps"]["fingerprint"] == "fp-deps"
    # Observation → {provenance, text, severity} adapter (severity plumbs through)
    assert by_dim["security"]["observations"] == [
        {"provenance": "prod.env:4", "text": "AWS key pattern", "severity": "critical"}
    ]
    # empty fingerprint → NULL ⇒ stale; unavailable tuple → reason string
    assert by_dim["tests"]["status"] == "unavailable" and by_dim["tests"]["fingerprint"] is None
    assert by_dim["tests"]["unavailable_reason"] == "no sandbox"
    # the transient overlay clears when the sweep finishes
    assert recon_mod.recon_state("proj-1") == {"running": False, "error": None}


def test_run_recon_records_total_failure_and_clears_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mem = _FakeMemory()

    def boom(*_a: Any, **_k: Any) -> Any:
        raise FileNotFoundError("clone missing — project never initialized")

    monkeypatch.setattr(recon_mod, "open_project_workspace", boom)
    recon_mod.run_recon(mem, "proj-x")  # type: ignore[arg-type]

    state = recon_mod.recon_state("proj-x")
    assert state["running"] is False
    assert isinstance(state["error"], str) and "clone missing" in state["error"]
    assert mem.upserts == []  # nothing persisted on a total failure
