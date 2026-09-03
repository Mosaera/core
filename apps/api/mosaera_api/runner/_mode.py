"""Run interaction modes (ADR-0101): ask / accept / auto, operator-switchable live.

The mode governs the WRITE gates only: `ask` parks every write for a human (legacy
guided); `accept`/`auto` auto-approve each write with a recorded approval row. The
DELIVERY gate keeps the run's launch semantics untouched — a guided-launched run always
parks its delivery for a human regardless of the live mode, and no mode ever skips the
deterministic gate. Escalation/stuck gates fire in every mode.

Kept out of ``_base.py`` deliberately (the 500-line ratchet); state lives on the session
as ``_interaction_mode`` via ``getattr`` so the session class itself is untouched.
"""

from __future__ import annotations

import json
from typing import Any

MODES = ("ask", "accept", "auto")

_LEGACY = {"guided": "ask", "autonomous": "auto", "high_assurance": "ask"}


def get_mode(session: Any) -> str:
    """The live interaction mode; defaults from the run's launch mode."""
    stored = getattr(session, "_interaction_mode", None)
    if stored in MODES:
        return str(stored)
    return _LEGACY.get(str(getattr(session, "mode", "guided")), "ask")


def writes_auto(session: Any) -> bool:
    """accept/auto: in-scope writes are auto-approved (and recorded), never parked."""
    return get_mode(session) in ("accept", "auto")


def set_mode(session: Any, new_mode: str) -> str:
    """Switch the live mode, recording the change as an operator decision + audit.

    Raises ``ValueError`` on an unknown mode. Returns the previous mode.
    """
    if new_mode not in MODES:
        raise ValueError(f"unknown interaction mode: {new_mode!r} (expected one of {MODES})")
    previous = get_mode(session)
    session._interaction_mode = new_mode
    if previous != new_mode:
        session._audit("mode-change", f"{previous} -> {new_mode} (operator)")
        memory = session._memory
        if memory is not None:
            session._safe(
                lambda: memory.add_decision(
                    session.run_id,
                    "mode_change",
                    json.dumps({"from": previous, "to": new_mode, "actor": "human"}),
                )
            )
    return previous
