"""Operator-facing progress for the validation phase.

Extracted from ``nodes_impl.py`` rather than added to it: that module sits at the god-file limit,
and this is display/telemetry with no routing or evidence logic — the same separation
``tools/repo/_activity.py`` makes for the coder tools.
"""

from __future__ import annotations

from mosaera_core.tools.repo._activity import emit_activity

# What each validation step is doing, in the operator's words rather than the runner's. An unknown
# step falls back to its own name — the plan vocabulary can grow (it already has), and a missing
# entry must degrade to something readable, never to silence.
_STEP_PLAIN = {
    "install": "installing dependencies",
    "pytest": "running the test suite",
    "custom": "running the test command",
    "py-compile": "checking the code compiles",
    "html-check": "checking the HTML",
    "config-check": "checking the config files",
}


def validation_progress(phase: str, name: str, detail: str) -> None:
    """Surface validation to the run's activity stream (F80, 2026-08-23).

    Validation is the ONE stretch of a run that makes no model calls, so the token counter is flat
    throughout and, until this existed, nothing at all was emitted between "the coder finished" and
    "the suite finished" — a healthy install+suite cycle read as a hung run for minutes (owner:
    *"I thought it was stalled"*). The actor copy for this phase was already written
    (``RUN_ACTORS.test``: *"is running validation"*); it had no event to fire on.
    """
    what = _STEP_PLAIN.get(name, name)
    if phase == "start":
        emit_activity("validation", f"{what} ({detail})" if detail else what)
    else:
        emit_activity("validation", what, result=detail)
