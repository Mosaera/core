"""Messages, attachments, derivatives, project-context items, and artifacts."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from mosaera_memory._titles import derive_session_title
from mosaera_memory.models import (
    Artifact,
    Attachment,
    AttachmentDerivative,
    MessageAttachment,
    MessageContextSource,
    PmSession,
    ProjectContextItem,
    ProjectMessage,
    _utcnow,
)
from mosaera_memory.models_proposals import (
    PROPOSAL_KINDS,
    PROPOSAL_STATUSES,
    MessageProposal,
)
from mosaera_memory.store._base import StoreBase, _attachment_summary, _iso
from mosaera_memory.store._sessions import resolve_or_create_default_session


class ContentMixin(StoreBase):
    def add_message(
        self, project_id: str, role: str, content: str, session_id: str | None = None
    ) -> int:
        """Persist a chat turn into a session; returns the message id (attachment links
        need it). ``session_id`` omitted → the project's current session (created if none),
        so callers that don't track sessions still work. Writing a turn bumps the session's
        recency and, on the first user turn, auto-names an untitled session."""
        with self.session() as s, s.begin():
            sid = session_id or resolve_or_create_default_session(s, project_id)
            msg = ProjectMessage(project_id=project_id, role=role, content=content, session_id=sid)
            s.add(msg)
            s.flush()
            sess = s.get(PmSession, sid)
            if sess is not None:
                sess.updated_at = _utcnow()
                if role == "user" and not sess.title and content.strip():
                    sess.title = derive_session_title(content)
            return msg.id

    # --- attachments ---

    def add_attachment(
        self,
        attachment_id: str,
        project_id: str,
        *,
        filename: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
        storage_path: str,
        status: str = "stored",
        error_message: str = "",
        token_estimate: int = 0,
        scope: str = "message_only",
    ) -> None:
        with self.session() as s, s.begin():
            s.add(
                Attachment(
                    id=attachment_id,
                    project_id=project_id,
                    filename=filename,
                    mime_type=mime_type,
                    size_bytes=size_bytes,
                    sha256=sha256,
                    storage_path=storage_path,
                    status=status,
                    error_message=error_message,
                    token_estimate=token_estimate,
                    scope=scope,
                )
            )

    def get_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        with self.session() as s:
            a = s.get(Attachment, attachment_id)
            return _attachment_summary(a) if a is not None else None

    def list_attachments(
        self, project_id: str, include_deleted: bool = False
    ) -> list[dict[str, Any]]:
        stmt = (
            select(Attachment)
            .where(Attachment.project_id == project_id)
            .order_by(Attachment.created_at, Attachment.id)
        )
        if not include_deleted:
            stmt = stmt.where(Attachment.deleted_at.is_(None))
        with self.session() as s:
            return [_attachment_summary(a) for a in s.scalars(stmt)]

    def find_attachment_by_hash(self, project_id: str, sha256: str) -> dict[str, Any] | None:
        """Dedup lookup: an existing non-deleted upload with the same content."""
        stmt = (
            select(Attachment)
            .where(
                Attachment.project_id == project_id,
                Attachment.sha256 == sha256,
                Attachment.deleted_at.is_(None),
            )
            .limit(1)
        )
        with self.session() as s:
            a = s.scalars(stmt).first()
            return _attachment_summary(a) if a is not None else None

    def soft_delete_attachment(self, attachment_id: str) -> None:
        """Hide from active lists and future prompts; message links stay intact."""
        with self.session() as s, s.begin():
            a = s.get(Attachment, attachment_id)
            if a is not None and a.deleted_at is None:
                a.deleted_at = datetime.now(UTC)

    def update_attachment(self, attachment_id: str, **fields: Any) -> None:
        """Patch mutable attachment fields (status/error_message/token_estimate/scope)."""
        allowed = {"status", "error_message", "token_estimate", "scope"}
        with self.session() as s, s.begin():
            a = s.get(Attachment, attachment_id)
            if a is None:
                return
            for key, value in fields.items():
                if key in allowed:
                    setattr(a, key, value)

    # --- attachment derivatives (guardrail 9: replace, never duplicate) ---

    def replace_derivatives(self, attachment_id: str, derivatives: list[dict[str, Any]]) -> None:
        """Atomically swap an attachment's derivative set (reprocessing-safe)."""
        with self.session() as s, s.begin():
            for old in s.scalars(
                select(AttachmentDerivative).where(
                    AttachmentDerivative.attachment_id == attachment_id
                )
            ):
                s.delete(old)
            for d in derivatives:
                s.add(
                    AttachmentDerivative(
                        attachment_id=attachment_id,
                        kind=d["kind"],
                        content=d.get("content", ""),
                        storage_path=d.get("storage_path", ""),
                        token_count=d.get("token_count", 0),
                        chunk_index=d.get("chunk_index", 0),
                        model=d.get("model", ""),
                    )
                )

    def list_derivatives(self, attachment_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        stmt = (
            select(AttachmentDerivative)
            .where(AttachmentDerivative.attachment_id == attachment_id)
            .order_by(AttachmentDerivative.kind, AttachmentDerivative.chunk_index)
        )
        if kind is not None:
            stmt = stmt.where(AttachmentDerivative.kind == kind)
        with self.session() as s:
            return [
                {
                    "id": d.id,
                    "attachment_id": d.attachment_id,
                    "kind": d.kind,
                    "content": d.content,
                    "storage_path": d.storage_path,
                    "token_count": d.token_count,
                    "chunk_index": d.chunk_index,
                    "model": d.model,
                }
                for d in s.scalars(stmt)
            ]

    # --- project context items (guardrail 8: kept in sync, never stale) ---

    def upsert_project_context_item(
        self,
        project_id: str,
        source_id: str,
        *,
        title: str,
        summary: str,
        token_count: int,
        source_type: str = "attachment",
    ) -> None:
        """Create or re-enable/update the registry entry for a source."""
        with self.session() as s, s.begin():
            existing = s.scalars(
                select(ProjectContextItem).where(
                    ProjectContextItem.project_id == project_id,
                    ProjectContextItem.source_type == source_type,
                    ProjectContextItem.source_id == source_id,
                )
            ).first()
            if existing is not None:
                existing.title = title
                existing.summary = summary
                existing.token_count = token_count
                existing.updated_at = datetime.now(UTC)
                existing.disabled_at = None
            else:
                s.add(
                    ProjectContextItem(
                        project_id=project_id,
                        source_type=source_type,
                        source_id=source_id,
                        title=title,
                        summary=summary,
                        token_count=token_count,
                    )
                )

    def disable_project_context_item(
        self, project_id: str, source_id: str, source_type: str = "attachment"
    ) -> None:
        with self.session() as s, s.begin():
            for item in s.scalars(
                select(ProjectContextItem).where(
                    ProjectContextItem.project_id == project_id,
                    ProjectContextItem.source_type == source_type,
                    ProjectContextItem.source_id == source_id,
                    ProjectContextItem.disabled_at.is_(None),
                )
            ):
                item.disabled_at = datetime.now(UTC)
                item.updated_at = datetime.now(UTC)

    def list_project_context_items(self, project_id: str) -> list[dict[str, Any]]:
        """Active items only — disabled context must never reach a prompt."""
        stmt = (
            select(ProjectContextItem)
            .where(
                ProjectContextItem.project_id == project_id,
                ProjectContextItem.disabled_at.is_(None),
            )
            .order_by(ProjectContextItem.priority.desc(), ProjectContextItem.id)
        )
        with self.session() as s:
            return [
                {
                    "id": i.id,
                    "project_id": i.project_id,
                    "source_type": i.source_type,
                    "source_id": i.source_id,
                    "title": i.title,
                    "summary": i.summary,
                    "token_count": i.token_count,
                    "priority": i.priority,
                }
                for i in s.scalars(stmt)
            ]

    # --- context traceability (MR 4D) ---

    def add_message_context_sources(self, message_id: int, sources: list[dict[str, Any]]) -> None:
        """Record what context a PM reply used (from builder metadata)."""
        with self.session() as s, s.begin():
            for src in sources:
                s.add(
                    MessageContextSource(
                        message_id=message_id,
                        source_type=src["source_type"],
                        source_id=src.get("source_id", ""),
                        title=src.get("title", ""),
                        included_as=src.get("included_as", "included_raw"),
                        token_count=src.get("token_count", 0),
                    )
                )

    # --- what Quincy PROPOSED on a turn (0031) ---

    def add_message_proposals(self, message_id: int, proposals: list[dict[str, Any]]) -> None:
        """Record the proposals a PM turn produced, so its card survives a reload.

        Unknown kinds are DROPPED rather than stored: the payload is model output, and a row the UI
        cannot draw is worse than no row — it would restore a blank card under a reply whose text
        was already stripped of the proposal.
        """
        with self.session() as s, s.begin():
            for p in proposals:
                kind = str(p.get("kind", ""))
                if kind not in PROPOSAL_KINDS or p.get("payload") in (None, [], {}):
                    continue
                s.add(MessageProposal(message_id=message_id, kind=kind, payload=p["payload"]))

    def set_proposal_status(self, proposal_id: int, status: str) -> bool:
        """Mark a proposal accepted/dismissed. False when the id or status is unknown.

        This records what the operator DID; it never applies anything. The apply path keeps its own
        validator and gates (ADR-0047 §1: propose is not write).
        """
        if status not in PROPOSAL_STATUSES:
            return False
        with self.session() as s, s.begin():
            row = s.get(MessageProposal, proposal_id)
            if row is None:
                return False
            row.status = status
            return True

    def link_message_attachments(self, message_id: int, attachment_ids: list[str]) -> None:
        with self.session() as s, s.begin():
            for att_id in attachment_ids:
                s.add(MessageAttachment(message_id=message_id, attachment_id=att_id))

    def attachments_for_message(self, message_id: int) -> list[dict[str, Any]]:
        stmt = (
            select(Attachment)
            .join(MessageAttachment, MessageAttachment.attachment_id == Attachment.id)
            .where(MessageAttachment.message_id == message_id)
            .order_by(MessageAttachment.id)
        )
        with self.session() as s:
            return [_attachment_summary(a) for a in s.scalars(stmt)]

    def list_messages(self, project_id: str, session_id: str | None = None) -> list[dict[str, Any]]:
        """A project's chat turns. ``session_id`` given → that session's history only (the
        interactive path); omitted → all of the project's turns across sessions (used by
        decomposition, which synthesizes the brief from everything the stakeholder said)."""
        stmt = select(ProjectMessage).where(ProjectMessage.project_id == project_id)
        if session_id is not None:
            stmt = stmt.where(ProjectMessage.session_id == session_id)
        stmt = stmt.order_by(ProjectMessage.id)
        with self.session() as s:
            messages = list(s.scalars(stmt))
            # Attachments that rode on each message (shown in the transcript).
            # Soft-deleted files still appear here — history never breaks.
            steps_by_message = self._steps_by_message(s, [m.id for m in messages])
            by_message: dict[int, list[dict[str, Any]]] = {}
            if messages:
                link_stmt = (
                    select(MessageAttachment.message_id, Attachment)
                    .join(Attachment, Attachment.id == MessageAttachment.attachment_id)
                    .where(MessageAttachment.message_id.in_([m.id for m in messages]))
                    .order_by(MessageAttachment.id)
                )
                for message_id, att in s.execute(link_stmt):
                    by_message.setdefault(message_id, []).append(
                        {
                            "id": att.id,
                            "filename": att.filename,
                            "scope": att.scope,
                            "size_bytes": att.size_bytes,
                            "mime_type": att.mime_type,
                        }
                    )
            # What each PM reply used (MR 4D "Used context" chips).
            sources_by_message: dict[int, list[dict[str, Any]]] = {}
            if messages:
                src_stmt = (
                    select(MessageContextSource)
                    .where(MessageContextSource.message_id.in_([m.id for m in messages]))
                    .order_by(MessageContextSource.id)
                )
                for src in s.scalars(src_stmt):
                    sources_by_message.setdefault(src.message_id, []).append(
                        {
                            "source_type": src.source_type,
                            "source_id": src.source_id,
                            "title": src.title,
                            "included_as": src.included_as,
                            "token_count": src.token_count,
                        }
                    )
            # The proposals each PM turn made. OPEN only: a card the operator already accepted or
            # dismissed must not come back on every reload — the `clarification` vs
            # `clarification_record` split, applied to the chat.
            proposals_by_message: dict[int, list[dict[str, Any]]] = {}
            if messages:
                prop_stmt = (
                    select(MessageProposal)
                    .where(
                        MessageProposal.message_id.in_([m.id for m in messages]),
                        MessageProposal.status == "open",
                    )
                    .order_by(MessageProposal.id)
                )
                for prop in s.scalars(prop_stmt):
                    proposals_by_message.setdefault(prop.message_id, []).append(
                        {"id": prop.id, "kind": prop.kind, "payload": prop.payload}
                    )
            return [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "created_at": _iso(m.created_at),
                    "attachments": by_message.get(m.id, []),
                    "context_sources": sources_by_message.get(m.id, []),
                    # What this turn looked up before it answered (slice 4). Same
                    # batched shape as the two above; absent on older rows.
                    "steps": steps_by_message.get(m.id, []),
                    "proposals": proposals_by_message.get(m.id, []),
                }
                for m in messages
            ]

    def add_artifact(
        self,
        run_id: str,
        kind: str,
        content: str,
        embedding: Sequence[float] | None = None,
    ) -> None:
        with self.session() as s, s.begin():
            s.add(
                Artifact(
                    run_id=run_id,
                    kind=kind,
                    content=content,
                    embedding=list(embedding) if embedding is not None else None,
                )
            )

    def similar_artifacts(
        self, embedding: Sequence[float], k: int = 5
    ) -> list[tuple[Artifact, float]]:
        """Return the ``k`` artifacts closest to ``embedding`` by cosine distance."""
        vec = list(embedding)
        distance = Artifact.embedding.cosine_distance(vec)
        stmt = (
            select(Artifact, distance)
            .where(Artifact.embedding.is_not(None))
            .order_by(distance)
            .limit(k)
        )
        with self.session() as s:
            return [(art, float(dist)) for art, dist in s.execute(stmt).all()]
