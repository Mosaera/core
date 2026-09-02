"""LanguagePack registry + dispatcher.

``dispatch`` replaces the historical ``if/elif`` chain in ``detect_validation_plan``: it walks
the ordered ``REGISTRY``, collects each pack's confidence-scored plan, and the highest-confidence
match wins (ties broken by registry order). This makes precedence explicit — a strong signal
(pytest config, package.json) beats a weak one (a stray source file) regardless of position.
Adding a language = adding a pack here; nothing else in the engine changes (see ADR-0032).
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from mosaera_core.languages.base import DetectContext, LanguagePack
from mosaera_core.languages.config_data import ConfigDataPack
from mosaera_core.languages.node import NodePack
from mosaera_core.languages.python import PythonPack
from mosaera_core.languages.sql import SqlPack
from mosaera_core.languages.static_site import StaticSitePack
from mosaera_core.progress import generic_test_report
from mosaera_core.testreport import TestReport
from mosaera_core.validation import ValidationOutcome, ValidationPlan

if TYPE_CHECKING:
    from mosaera_core.tools.repo import Workspace

# Ordered registry. Order only breaks confidence ties; the score is what decides. PythonPack
# precedes SqlPack so a .py+.sql repo (both weak "sources" signals) resolves to Python (the app),
# with SQL as a component.
REGISTRY: tuple[LanguagePack, ...] = (
    PythonPack(),
    NodePack(),
    SqlPack(),
    StaticSitePack(),
    ConfigDataPack(),
)

_UNKNOWN = ValidationPlan(
    "unknown",
    [],
    "No recognized project type (no pytest configuration, Python sources, package.json, "
    "HTML pages, or config/data files) — validation unavailable.",
    strength="none",  # nothing executes
)


def dispatch(
    workspace: Workspace, *, install: bool = True, install_timeout: int | None = None
) -> ValidationPlan:
    """Detect the project's language and build its deterministic validation plan.

    Highest-confidence pack wins; ``unknown`` (empty steps → ``validation_unavailable``) when
    no pack recognises the workspace."""
    ctx = DetectContext(
        workspace=workspace,
        listing=workspace.file_listing(limit=300),
        install=install,
        install_timeout=install_timeout,
    )
    best: tuple[int, ValidationPlan, LanguagePack] | None = None
    for pack in REGISTRY:
        result = pack.detect(ctx)
        if result is not None and (best is None or result[0] > best[0]):
            best = (result[0], result[1], pack)
    if best is None:
        return _UNKNOWN
    # Stamp the winner onto the plan so its result can be handed back to the pack that built it
    # (#81). Packs return plans without a pack_name; the registry is the one place that knows
    # which pack won, so it is the one place that should record it.
    return dataclasses.replace(best[1], pack_name=best[2].name)


def interpret_outcome(plan: ValidationPlan, outcome: ValidationOutcome) -> TestReport | None:
    """Read ``outcome`` using the pack that BUILT ``plan`` (#81).

    Falls back to the pytest-shaped ``generic_test_report`` when the plan has no owning pack — the
    operator's ``--test-cmd`` plan, or a plan restored from an older checkpoint written before
    ``pack_name`` existed. That fallback is exactly the pre-#81 behaviour, so an unstamped plan
    degrades to what it did before rather than losing its signal.
    """
    for pack in REGISTRY:
        if pack.name == plan.pack_name:
            return pack.interpret(outcome)
    return generic_test_report(outcome.output)


__all__ = [
    "REGISTRY",
    "DetectContext",
    "LanguagePack",
    "dispatch",
    "interpret_outcome",
]
