"""Derived-clause ORM model: an operator decision recorded once (ADR-0082 tier 2).

A clause is the durable answer to a question the operator already settled — "a short orchestrator
means at most 5 statements" — so the next item inherits it instead of asking again. It CITES a
standing standard and applies it locally; it is an application, never a carve-out.

Three shape rules are enforced by the schema rather than by convention, because each of them is a
way the original defect could come back:

- **The value is a NUMBER, never prose.** ``value_kind`` + ``value_num``, with no free-text value
  column anywhere. The whole failure this exists for was a value ("a handful") that two competent
  readers derived differently; a clause whose value had to be re-read from text would reproduce it
  one layer up.
- **No ``scope`` column.** Scope is inherited from the cited standard (ADR-0082 §3) — it is not a
  field anyone chooses, so there is nothing here to choose it with. ``project_id`` is derived by
  the writer from the standard's own scope.
- **No ``expires_at``.** A clause is stale by construction when its parent moves, so validity is
  re-derived at read (``mosaera_core.clauses.load_clauses``) rather than diarised.

Append-only: ratifying a replacement SUPERSEDES the prior row rather than updating it, so the
history of a decision survives — an audit trail for free, and the reason there is no UPDATE path.

Split out of ``models.py`` (at the modularity ceiling) but part of the SAME declarative ``Base``,
registering when ``store/_clauses.py`` imports it — the ``models_charter`` precedent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from mosaera_memory.models import Base, _utcnow

# The value shapes a clause may carry (ADR-0082 §2). `advisory` states that the operator has
# deliberately declined to fix a number; `unbounded` removes a parent's optional bound. Both are
# decisions, and both are recorded rather than left implicit. Mirrors `VALUE_KINDS` in
# `mosaera_policies.standards` — the leaf cannot import policies (it is a leaf), so the store
# validates SHAPE only and the trust boundary lives in `mosaera_core.clauses`.
CLAUSE_VALUE_KINDS: frozenset[str] = frozenset({"advisory", "number", "unbounded"})


class StandardClause(Base):
    """One ratified clause. Live rows are those with ``superseded_at IS NULL``.

    ``because`` is prose and is NEVER parsed — it explains the decision to a human; the machine
    reads ``value_num`` only. ``provenance`` records where the decision came from (a gate run, a
    counsel role) so a clause is traceable to the moment it was made.
    """

    __tablename__ = "standard_clauses"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    # NULL for a repo-scoped clause (it applies everywhere). Derived from the cited standard's
    # scope by the writer — never accepted from a caller.
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    standard_id: Mapped[str] = mapped_column(String(120))  # the tier-1 parent this cites
    binds: Mapped[str] = mapped_column(String(120))  # a registered oracle parameter

    value_kind: Mapped[str] = mapped_column(String(16))  # one of CLAUSE_VALUE_KINDS
    value_num: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # An optional single comparison — all three columns or none of them.
    when_param: Mapped[str | None] = mapped_column(String(60), nullable=True)
    when_op: Mapped[str | None] = mapped_column(String(2), nullable=True)
    when_num: Mapped[int | None] = mapped_column(Integer, nullable=True)

    because: Mapped[str] = mapped_column(Text, default="")  # prose; never parsed
    author: Mapped[str] = mapped_column(String(120), default="")
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    ratified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
