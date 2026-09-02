"""PM chat sessions: per-project conversation threads (create/list/get/rename/archive).

A session scopes chat HISTORY only — project knowledge (brief/backlog/runs/context registry)
stays project-scoped and is shared across a project's sessions (issue #30, ADR-0048 — cited as
ADR-0045 until 2026-08-20; the firm layer is a different, unbuilt decision). The
message store (``_content``) writes turns into a session and reads them back per-session; this
mixin owns the session lifecycle and the default-session seam that keeps legacy/first chats
working when no session is named."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mosaera_memory.models import PmSession, ProjectMessage
from mosaera_memory.store._base import StoreBase, _iso


def new_session_id() -> str:
    return f"sess-{uuid.uuid4().hex[:12]}"


def resolve_or_create_default_session(s: Session, project_id: str) -> str:
    """The project's most-recent ACTIVE session id, creating an empty one if none exists.

    A module function (not a mixin method) so the message store can call it inside its own
    transaction without a cross-mixin dependency — both the write path and ``ensure_default_
    session`` share exactly one definition of "the current session"."""
    existing = s.scalars(
        select(PmSession)
        .where(PmSession.project_id == project_id, PmSession.archived_at.is_(None))
        .order_by(PmSession.updated_at.desc(), PmSession.id.desc())
        .limit(1)
    ).first()
    if existing is not None:
        return existing.id
    created = PmSession(id=new_session_id(), project_id=project_id)
    s.add(created)
    s.flush()
    return created.id


def _session_summary(obj: PmSession, message_count: int = 0) -> dict[str, Any]:
    return {
        "id": obj.id,
        "project_id": obj.project_id,
        "title": obj.title,
        "created_at": _iso(obj.created_at),
        "updated_at": _iso(obj.updated_at),
        "archived": obj.archived_at is not None,
        "archived_at": _iso(obj.archived_at) if obj.archived_at else None,
        "message_count": message_count,
    }


class SessionsMixin(StoreBase):
    def create_pm_session(self, project_id: str, title: str = "") -> str:
        """Mint a new (empty) session; returns its id. Title is optional — the first user
        turn auto-names an untitled session (see ``ContentMixin.add_message``)."""
        session_id = new_session_id()
        with self.session() as s, s.begin():
            s.add(PmSession(id=session_id, project_id=project_id, title=title[:256]))
        return session_id

    def get_pm_session(self, session_id: str) -> dict[str, Any] | None:
        with self.session() as s:
            obj = s.get(PmSession, session_id)
            if obj is None:
                return None
            count = (
                s.scalar(
                    select(func.count(ProjectMessage.id)).where(
                        ProjectMessage.session_id == session_id
                    )
                )
                or 0
            )
            return _session_summary(obj, count)

    def list_pm_sessions(
        self, project_id: str, include_archived: bool = False
    ) -> list[dict[str, Any]]:
        """A project's sessions, most-recently-active first. Active only by default —
        archived sessions are hidden from the switcher but never deleted."""
        stmt = select(PmSession).where(PmSession.project_id == project_id)
        if not include_archived:
            stmt = stmt.where(PmSession.archived_at.is_(None))
        stmt = stmt.order_by(PmSession.updated_at.desc(), PmSession.id.desc())
        with self.session() as s:
            sessions = list(s.scalars(stmt))
            counts: dict[str, int] = {}
            if sessions:
                count_stmt = (
                    select(ProjectMessage.session_id, func.count(ProjectMessage.id))
                    .where(ProjectMessage.session_id.in_([x.id for x in sessions]))
                    .group_by(ProjectMessage.session_id)
                )
                for sid, n in s.execute(count_stmt):
                    counts[sid] = n
            return [_session_summary(x, counts.get(x.id, 0)) for x in sessions]

    def ensure_default_pm_session(self, project_id: str) -> str:
        """The project's current session id, creating one if the project has none."""
        with self.session() as s, s.begin():
            return resolve_or_create_default_session(s, project_id)

    def rename_pm_session(self, session_id: str, title: str) -> None:
        with self.session() as s, s.begin():
            obj = s.get(PmSession, session_id)
            if obj is not None:
                obj.title = title[:256]
                obj.updated_at = datetime.now(UTC)

    def set_pm_session_archived(self, session_id: str, archived: bool) -> None:
        """Soft archive/unarchive — flips ``archived_at``; the transcript is untouched."""
        with self.session() as s, s.begin():
            obj = s.get(PmSession, session_id)
            if obj is not None:
                obj.archived_at = datetime.now(UTC) if archived else None
