"""The journal entry model."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Entry:
    """One journal entry: a stable id, its text, and any tags attached to it."""

    id: int
    text: str
    tags: list[str] = field(default_factory=list)
