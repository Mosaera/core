"""Attachment ORM models: uploaded files, their processed derivatives, and message links.

Split out of ``models.py`` (which is at the modularity ceiling) but part of the SAME
declarative ``Base`` — ``models.py`` re-exports these at its bottom, so importers keep using
``from mosaera_memory.models import Attachment`` unchanged and ``Base.metadata`` stays complete.

Storage is separated from context injection throughout: the binary lives on disk (``storage_path``,
relative to the uploads root — never in Postgres), while whether and how it enters a PM prompt is
the prompt builder's call.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mosaera_memory.models import Base, _utcnow

if TYPE_CHECKING:  # a string annotation keeps this module free of a runtime import cycle
    from mosaera_memory.models import Project


class Attachment(Base):
    """A file uploaded to a project. Storage is separated from context injection:
    the binary lives on disk (storage_path, relative to the uploads root — never
    in Postgres); whether/how it enters a PM prompt is the prompt builder's call.

    TODO(scope): scope may move to usage-level records later — the same stored
    file may eventually be reused with different scopes per use."""

    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # att-<hex>
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(256))  # sanitized display name
    mime_type: Mapped[str] = mapped_column(String(128), default="text/plain")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(String(1024))  # relative to uploads root
    # stored | ready | failed  (4A processes small text synchronously → ready)
    status: Mapped[str] = mapped_column(String(16), default="stored")
    error_message: Mapped[str] = mapped_column(Text, default="")
    # chars//4 approximation; a real tokenizer can replace this later.
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
    # message_only | project_context ("eligible for project-context inclusion")
    scope: Mapped[str] = mapped_column(String(32), default="message_only")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship()


class AttachmentDerivative(Base):
    """Processed output derived from an attachment: extracted text, a short
    summary, ~1000-token chunks, or a thumbnail (stored on disk, path only).
    Derivatives are replaceable — reprocessing deletes the old set first, so
    there is never more than one active row per kind+index (guardrail 9)."""

    __tablename__ = "attachment_derivatives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attachment_id: Mapped[str] = mapped_column(
        ForeignKey("attachments.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(
        String(32)
    )  # text_extract | summary_short | chunk | thumbnail
    content: Mapped[str] = mapped_column(Text, default="")  # empty for thumbnail
    storage_path: Mapped[str] = mapped_column(String(1024), default="")  # thumbnail file
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str] = mapped_column(String(128), default="")  # summarizer model id
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class MessageAttachment(Base):
    """Which attachments rode on which chat message. Rows persist even if the
    attachment is later soft-deleted, so historical references never break."""

    __tablename__ = "message_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("project_messages.id", ondelete="CASCADE"), index=True
    )
    attachment_id: Mapped[str] = mapped_column(
        ForeignKey("attachments.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
