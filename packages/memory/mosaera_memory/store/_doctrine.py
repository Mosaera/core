"""Doctrine (the trusted corpus the PM follows)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select

from mosaera_memory.models import DoctrineChunk
from mosaera_memory.store._base import StoreBase


class DoctrineMixin(StoreBase):
    # --- doctrine (the trusted corpus the PM follows) ---

    def add_doctrine_chunk(
        self,
        scope: str,
        content: str,
        *,
        project_id: str | None = None,
        source: str = "",
        kind: str = "reference",
        embedding: Sequence[float] | None = None,
    ) -> int:
        """Insert a doctrine chunk (global or per-project). Returns its id."""
        chunk = DoctrineChunk(
            scope=scope,
            project_id=project_id,
            source=source,
            kind=kind,
            content=content,
            embedding=list(embedding) if embedding is not None else None,
        )
        with self.session() as s, s.begin():
            s.add(chunk)
            s.flush()
            return int(chunk.id)

    def load_doctrine(
        self, scope: str, project_id: str | None = None, kind: str | None = None
    ) -> list[dict[str, Any]]:
        """Doctrine chunks for a scope (plain read, no vectors) — most recent first.
        Used to inject per-project reference material into planning."""
        stmt = select(DoctrineChunk).where(DoctrineChunk.scope == scope)
        if project_id is not None:
            stmt = stmt.where(DoctrineChunk.project_id == project_id)
        if kind is not None:
            stmt = stmt.where(DoctrineChunk.kind == kind)
        stmt = stmt.order_by(DoctrineChunk.id.desc())
        with self.session() as s:
            return [
                {"source": d.source, "kind": d.kind, "content": d.content}
                for d in s.execute(stmt).scalars().all()
            ]

    def similar_doctrine(
        self,
        embedding: Sequence[float],
        *,
        scope: str,
        project_id: str | None = None,
        k: int = 5,
    ) -> list[tuple[DoctrineChunk, float]]:
        """The ``k`` doctrine chunks closest to ``embedding`` by cosine distance, within
        ``scope`` (and ``project_id`` when given). The semantic-retrieval seam for a
        large corpus — defined now, wired in a later phase."""
        vec = list(embedding)
        distance = DoctrineChunk.embedding.cosine_distance(vec)
        stmt = select(DoctrineChunk, distance).where(
            DoctrineChunk.embedding.is_not(None), DoctrineChunk.scope == scope
        )
        if project_id is not None:
            stmt = stmt.where(DoctrineChunk.project_id == project_id)
        stmt = stmt.order_by(distance).limit(k)
        with self.session() as s:
            return [(d, float(dist)) for d, dist in s.execute(stmt).all()]
