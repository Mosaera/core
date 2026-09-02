"""LangGraph orchestrator: PM(plan) -> Coder(implement) -> tests -> Reviewer ->
human approval gate -> deliver, or loop back to planning with feedback.

This package was split from the former single ``graph.py`` module (de-god-filing
Phase 4). This ``__init__`` is the FACADE: every symbol callers/tests previously
imported from ``mosaera_core.graph`` is re-exported here, so both
``from mosaera_core.graph import build_graph`` and ``import mosaera_core.graph as
graph_mod`` keep working unchanged. Core symbols that tests monkeypatch (``run_plan``,
``run_quality``, ``hygiene_targets``/``autofix``/``hygiene_findings``) are patched on the
submodule that binds them (``graph.nodes_impl`` / ``graph.nodes_review``), not here.
"""

from __future__ import annotations

from mosaera_core.graph.build import build_graph, reason_diagnose, recursion_limit_for
from mosaera_core.graph.context import ModelFactory, RunContext, TeamFactory
from mosaera_core.graph.grounding import (
    build_grounding,
    grounded_overview,
    plan_named_files,
    planning_overview,
)
from mosaera_core.graph.instructions import fix_instruction
from mosaera_core.graph.nodes_deliver import deliver_node
from mosaera_core.graph.nodes_impl import (
    fix_node,
    hygiene_fix_node,
    hygiene_node,
    route_after_hygiene,
    route_after_test,
    test_node,
)
from mosaera_core.graph.nodes_plan import (
    author_tests_node,
    capture_node,
    design_node,
    plan_node,
    route_after_capture,
    route_after_supervise,
    supervise_node,
)
from mosaera_core.graph.nodes_reason import reason_node
from mosaera_core.graph.nodes_review import (
    gate_node,
    quality_revise_node,
    review_fix_node,
    review_node,
    route_after_gate,
    route_after_review,
    scan_node,
)
from mosaera_core.graph.state import RunState

__all__ = [
    "ModelFactory",
    "RunContext",
    "RunState",
    "TeamFactory",
    "author_tests_node",
    "build_graph",
    "build_grounding",
    "capture_node",
    "deliver_node",
    "design_node",
    "fix_instruction",
    "fix_node",
    "gate_node",
    "grounded_overview",
    "hygiene_fix_node",
    "hygiene_node",
    "plan_named_files",
    "plan_node",
    "planning_overview",
    "quality_revise_node",
    "reason_diagnose",
    "reason_node",
    "recursion_limit_for",
    "review_fix_node",
    "review_node",
    "route_after_capture",
    "route_after_gate",
    "route_after_hygiene",
    "route_after_review",
    "route_after_supervise",
    "route_after_test",
    "scan_node",
    "supervise_node",
    "test_node",
]
