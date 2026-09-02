"""Agent personas as a data corpus (ADR-0013).

A persona is an agent's system prompt loaded from a ``<name>.md`` file rather than a
Python constant, so a new agent's voice lives as editable data — the pattern a future
UI "create an agent" flow builds on. Mirrors the doctrine loader
(``mosaera_core.doctrine``): code-first ``read_text`` + cache, no model call.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

_PERSONA_DIR = Path(__file__).parent


@cache
def load_persona(name: str) -> str:
    """The system prompt for agent ``name`` from ``personas/<name>.md``."""
    return (_PERSONA_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
