"""The project-map injection into planning scoping — gating + degrade-to-cold-look (#42, §2/§6).

These cover ``_with_project_map`` (the seam ``planning_overview`` calls): the untrusted map is
appended for gap-analysis ONLY when the knob is on, a project is set, and a DB is present; a first
run with an empty map degrades to a cold-look note and says so. The map never reaches the gate —
that is enforced structurally by the layer guard (``policies`` cannot import ``mapview``/the map).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from mosaera_core.graph import grounding


def _ctx(scoping: bool, project_id: str | None, dims: list[dict[str, Any]] | None) -> Any:
    memory = SimpleNamespace(list_map_dimensions=lambda _pid: dims) if dims is not None else None
    return SimpleNamespace(
        settings=SimpleNamespace(onboarding_map_scoping=scoping),
        project_id=project_id,
        memory=memory,
    )


_DIMS = [{"dimension": "deps", "status": "clean", "observations": []}]


def test_map_appended_as_a_separate_block_when_enabled() -> None:
    out = grounding._with_project_map(_ctx(True, "p1", _DIMS), "BODY")
    assert out.startswith("BODY\n\n")  # appended after the body, its own block (not merged)
    assert "## Project map" in out and "- deps — clean" in out


def test_empty_map_degrades_to_cold_look_and_says_so() -> None:
    out = grounding._with_project_map(_ctx(True, "p1", []), "BODY")
    assert out.startswith("BODY") and "cold first look" in out


def test_no_injection_when_knob_off() -> None:
    assert grounding._with_project_map(_ctx(False, "p1", _DIMS), "BODY") == "BODY"


def test_no_injection_without_a_project() -> None:
    # A CLI/repo run has no project → no map, unchanged body (§6).
    assert grounding._with_project_map(_ctx(True, None, _DIMS), "BODY") == "BODY"


def test_no_injection_without_a_database() -> None:
    assert grounding._with_project_map(_ctx(True, "p1", None), "BODY") == "BODY"
