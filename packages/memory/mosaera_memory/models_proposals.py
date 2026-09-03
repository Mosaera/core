"""What Quincy PROPOSED on a chat turn, stored beside the turn that produced it.

A PM turn returns two things the operator can act on — a backlog `changeset` and a
`charter_proposal` — and until now neither was written anywhere. `pm_turn` handed them to the
client, which held them in React state, so a refresh destroyed them. Worse than losing a card: the
agent strips the proposal out of the reply text before it is stored and substitutes "Here's what
I'd suggest.", so a reloaded transcript kept a sentence that means nothing. `PmChangesetCard.tsx`
has carried a TODO asking for exactly this.

Two decisions worth stating, because both could reasonably have gone the other way:

**A child table, not a JSON column on `project_messages`.** `MessageContextSource` is the precedent
— same parent, same CASCADE, same batched load inside `list_messages` — and a proposal needs its own
`status`, which a blob on the message would make awkward to update without rewriting the turn.

**Storing a proposal grants it NOTHING.** This row is a record of what was said, never a source of
authority. Applying a changeset still goes through `apply_backlog_changeset` and its validator; a
charter still needs the operator's admin-gated PUT (ADR-0047 §1: propose ≠ write). Nothing reads
this table to decide anything — the UI reads it to re-render a card the human then acts on, which
is the same authority the card always had.

Split out of ``models.py`` (at the god-file ceiling) but part of the SAME declarative ``Base``,
registering when ``store/_content.py`` imports it — the ``models_charter`` precedent.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from mosaera_memory.models import Base, _utcnow

#: What kind of thing was proposed. Closed set: an unknown kind would render as an unknown card,
#: and a card the UI cannot draw is worse than no row at all.
PROPOSAL_KINDS = ("changeset", "charter")

#: `open` is the only actionable state; the other two are the ledger of what the operator did. The
#: split mirrors `clarification` vs `clarification_record` (`store/_base.py`), where the live read
#: returns a proposal only while it is unresolved — otherwise a card the human already dealt with
#: comes back on every reload, which teaches them to ignore cards.
PROPOSAL_STATUSES = ("open", "accepted", "dismissed")


class MessageProposal(Base):
    """One proposal Quincy made on one PM turn."""

    __tablename__ = "message_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("project_messages.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))  # changeset | charter
    #: The proposal itself, exactly as the client needs it to re-render the card. Model output, so
    #: it is UNTRUSTED data — it is stored redacted (`redact_secrets`) and rendered by the same
    #: components that already render it live.
    payload: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
