"""The benchmark CLI builds with the autonomous oracle posture (#52, ADR-0057) — offline.

Stubs ``_bench`` (so no graph/model/sandbox runs) and captures the ``Settings`` the CLI hands it,
proving the scoreboard measures the real production autonomous oracle — and that the
``MOSAERA_AUTONOMOUS_VERIFIED=0`` opt-out reproduces the pre-#52 all-off deterministic baseline.
"""

from __future__ import annotations

from typing import Any

import pytest
from mosaera_core.bench import cli
from mosaera_core.bench.scorecard import Scorecard
from mosaera_core.config import Settings

_KNOBS = (
    "tester_enabled",
    "reason_on_stall_enabled",
    "oracle_coverage",
    "oracle_mutation_check",
    "tester_repairs_tests",  # #54
)


def _capture_settings(monkeypatch: pytest.MonkeyPatch) -> dict[str, Settings]:
    seen: dict[str, Settings] = {}

    def fake_bench(case: Any, settings: Settings, backend: str, repeat: int) -> Scorecard:
        seen["settings"] = settings
        return Scorecard(
            case_id=case.id, overall=0, dimensions=[], cost={}, meta={"outcome": "honest_park"}
        )

    monkeypatch.setattr(cli, "_bench", fake_bench)
    return seen


def test_bench_builds_with_the_full_oracle_posture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    seen = _capture_settings(monkeypatch)
    assert cli.main(["MCB-09"]) == 0
    settings = seen["settings"]
    assert all(getattr(settings, k) is True for k in _KNOBS)


def test_bench_opt_out_reproduces_the_deterministic_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_AUTONOMOUS_VERIFIED", "0")
    seen = _capture_settings(monkeypatch)
    assert cli.main(["MCB-09"]) == 0
    settings = seen["settings"]
    # The pre-#52 baseline: every oracle knob off (guarded by autonomous_verified=0).
    assert all(getattr(settings, k) is False for k in _KNOBS)
