"""Backlog provider seam.

The agent loop and API talk to a ``BacklogProvider`` rather than a specific
store, so the project backlog can be backed by our internal database today and by
an external system of record (GitLab Issues/Boards, then Jira/OpenProject) via a
connector later — without changing callers. Items are plain dicts (the shape
``MemoryStore`` already returns) so providers stay thin.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class DraftItem:
    """A backlog item the PM proposes when decomposing a brief."""

    title: str
    description: str = ""
    acceptance: str = ""


@runtime_checkable
class BacklogProvider(Protocol):
    def list_items(self, project_id: str) -> list[dict[str, Any]]: ...

    def add_item(
        self,
        project_id: str,
        title: str,
        description: str = "",
        acceptance: str = "",
        position: int = 0,
    ) -> int: ...

    def update_item(self, item_id: int, **fields: Any) -> None: ...
