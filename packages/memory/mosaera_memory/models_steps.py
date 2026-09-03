"""What Quincy LOOKED UP on a chat turn, stored beside the turn that produced it.

Slice 3 let the PM query his own records mid-conversation; slice 4 shows that happening. Both
leave the same question afterwards: what did he actually check before he said that? Live, the
status line answers it. A reload used to lose the answer entirely, which made the whole thing feel
like decoration rather than evidence.

**A child table, not a JSON column on `project_messages`.** The `MessageProposal` precedent — same
parent, same CASCADE, same batched load inside `list_messages` — and `models.py` is at its own
god-file ceiling. A blob would also throw away per-step ordering and duration as queryable facts,
and "which lookups take longest" is a question worth being able to ask later.

**Tokens, not sentences.** `tool` and `arg` are the same identifiers the tool accepts, and the
operator's wording is rendered from the copy deck (`plain.ts`). This is the rule `_failed_turn`
states for the failure row: the record is exact, the sentence is a reading. Storing prose would
freeze today's phrasing into history and make a copy fix a data migration.

**Storing a step grants it nothing.** It is a record of a read that already happened, over data the
engine itself wrote. Nothing consults this table to decide anything.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from mosaera_memory.models import Base, _utcnow

#: What kind of step this was. Closed set, and deliberately narrow: only a LOOKUP is worth keeping.
#: A turn's thinking time is not "a thing he checked", and recording it would put "checked 1 thing"
#: under every reply — noise that teaches people to ignore the disclosure entirely.
STEP_KINDS = ("tool",)


class MessageStep(Base):
    """One lookup Quincy made while composing one PM turn."""

    __tablename__ = "message_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("project_messages.id", ondelete="CASCADE"), index=True
    )
    #: Order within the turn. Read back with an explicit `order_by`: "he checked what was blocked,
    #: then why it kept failing" is a different account from the reverse, and insertion order is
    #: not a promise the database makes.
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))  # tool
    tool: Mapped[str] = mapped_column(String(64))  # e.g. project_history
    arg: Mapped[str] = mapped_column(String(64), default="")  # e.g. failures
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
