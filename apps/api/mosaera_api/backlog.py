"""Internal backlog provider — backs the ``BacklogProvider`` seam with MemoryStore.

The default (and only, for now) provider. A ``GitLabBacklog`` that syncs to
GitLab Issues/Boards is a follow-up behind the same interface.
"""

from __future__ import annotations

from typing import Any

from mosaera_memory import MemoryStore


class InternalBacklog:
    """A ``BacklogProvider`` backed by the durable-memory database."""

    def __init__(self, memory: MemoryStore):
        self._memory = memory

    def list_items(self, project_id: str) -> list[dict[str, Any]]:
        return self._memory.list_backlog_items(project_id)

    def add_item(
        self,
        project_id: str,
        title: str,
        description: str = "",
        acceptance: str = "",
        position: int = 0,
    ) -> int:
        return self._memory.add_backlog_item(project_id, title, description, acceptance, position)

    def update_item(self, item_id: int, **fields: Any) -> None:
        self._memory.update_backlog_item(item_id, **fields)
