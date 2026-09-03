"""An in-memory backlog store — just enough for the intake loop, and nothing more.

Not a promoted test fixture. `core` cannot import `apps/api/tests`, and more importantly the
deterministic arm genuinely needs no database: the loop under test is detection → routing →
resolution, none of which is about persistence. Paying for Postgres here would make the suite
expensive for no measurement.

It mirrors the CONTRACT of the real store where the loop depends on it — `set_item_clarification`
validates at the boundary and one open ask replaces another (ADR-0080's batching rule) — because a
fake that is more permissive than the real thing turns a suite into a source of false confidence.
"""

from __future__ import annotations

from typing import Any


class GovStore:
    """Backlog items + clarifications, with the real store's validation posture."""

    def __init__(self) -> None:
        self._items: dict[int, dict[str, Any]] = {}
        self._next_id = 1

    # --- backlog ---

    def add_item(self, title: str, acceptance: str, description: str = "") -> int:
        item_id = self._next_id
        self._next_id += 1
        self._items[item_id] = {
            "id": item_id,
            "title": title,
            "description": description,
            "acceptance": acceptance,
            "status": "todo",
            "clarification": None,
        }
        return item_id

    def list_backlog_items(self, project_id: str | None = None) -> list[dict[str, Any]]:
        return [dict(i) for i in self._items.values()]

    def get_backlog_item(self, item_id: int) -> dict[str, Any] | None:
        row = self._items.get(int(item_id))
        return dict(row) if row else None

    def update_backlog_item(self, item_id: int, **fields: Any) -> None:
        row = self._items[int(item_id)]
        for key, value in fields.items():
            if value is not None:
                row[key] = value

    # --- clarifications ---

    def set_item_clarification(
        self,
        item_id: int,
        *,
        claim_text: str,
        why_unbindable: str,
        proposals: list[str],
        axis: str,
        proposal_kind: str,
    ) -> None:
        """Store the open ask. Validates like the real store — empty claim text, zero proposals,
        or an unknown ``proposal_kind`` is a programming error, not a silently-stored bad question.

        The discriminator is mirrored deliberately (ADR-0091): a stub that accepts what the real
        store refuses stops being a mirror and starts being a place defects hide."""
        if not claim_text.strip():
            raise ValueError("claim_text is required")
        kept = [p.strip() for p in proposals if p and p.strip()]
        if not kept:
            raise ValueError("at least one proposal is required")
        if proposal_kind not in ("acceptance", "direction"):
            raise ValueError(f"unknown proposal_kind {proposal_kind!r}")
        # One open ask per item: a new request REPLACES an unresolved one (the batching rule).
        self._items[int(item_id)]["clarification"] = {
            "claim_text": claim_text[:2000],
            "why_unbindable": why_unbindable[:2000],
            "proposals": kept[:3],
            "axis": axis,
            "proposal_kind": proposal_kind,
            "status": "open",
        }

    def item_clarification(self, item_id: int) -> dict[str, Any] | None:
        row = self._items.get(int(item_id))
        ask = row.get("clarification") if row else None
        return dict(ask) if ask and ask.get("status") == "open" else None

    def resolve_item_clarification(self, item_id: int, *, status: str, resolution: str) -> None:
        ask = self._items[int(item_id)].get("clarification")
        if ask:
            ask["status"] = status
            ask["resolution"] = resolution

    # --- clauses (read side only; the arm ratifies through `mosaera_core.clauses`) ---

    def clause_insert(self, clause_id: str, **kw: Any) -> dict[str, Any]:
        row = {"id": clause_id, **kw}
        self._clauses = [
            c
            for c in getattr(self, "_clauses", [])
            if (c["project_id"], c["standard_id"], c["binds"])
            != (kw["project_id"], kw["standard_id"], kw["binds"])
        ]
        self._clauses.append(row)
        return row

    def clause_list(
        self, project_id: str | None = None, *, include_superseded: bool = False
    ) -> list[dict[str, Any]]:
        return list(getattr(self, "_clauses", []))
