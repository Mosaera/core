"""What a run STARTED with — its control set and its intent profiles.

Captured once at run start and never re-read. A knob flipped later must not retroactively
re-describe a finished run: that would be a new way for the dashboard to lie about history.

Extracted from ``_base.py`` (which sits against the 500-line ceiling) when the profile capture
was added. The seam is real rather than convenient — both functions answer one question, "what
was true when this run began?", and neither belongs to the runner's control flow.
"""

from __future__ import annotations

import os
from pathlib import Path

from mosaera_core.config import Settings, selected_profiles


def run_controls(settings: Settings) -> dict[str, bool]:
    """The optional agents/oracles this run executes with, including the ones that are OFF.

    The roster used to be inferred from observed events, so a disabled control was
    indistinguishable from one that simply had not run yet — which is how ``critic_enabled`` sat
    at its highest proven liveness rung and OFF, unremarked, on the live instance (2026-08-06).
    """
    return {
        "tester_enabled": settings.tester_enabled,
        "critic_enabled": settings.critic_enabled,
        "scan_enabled": settings.scan_enabled,
        "oracle_coverage": settings.oracle_coverage,
        "oracle_mutation_check": settings.oracle_mutation_check,
        "reason_on_stall_enabled": settings.reason_on_stall_enabled,
        "escalate_arm": settings.escalate_arm,
    }


def run_profiles(home: Path) -> dict[str, str]:
    """The intent profiles selected when this run began (ADR-0122), unset ones omitted.

    Recorded so a finished run can be read as an OBSERVATION rather than a promise: "effort was
    persistent, and it spent 3 of 12 iterations and $6.20" is a fact about this run, where "
    persistent tries harder" is a claim about runs in general that nothing has yet measured.

    Read from the layering helper rather than from ``Settings`` on purpose — the profile fields
    are inputs to that layering and are deliberately not carried on ``Settings``, because a field
    no engine code reads is how this repository has twice produced a decorative control.
    """
    from mosaera_core.settings_store import read_settings

    chosen = selected_profiles(os.environ, read_settings(home))
    return {k: v for k, v in chosen.items() if isinstance(v, str) and v}
