"""The test-contract registry (ADR-0087 §1-§4): who owns a delivered test, and its history.

Project item runs share ONE long-lived clone, so a test delivered by item N is cut into item
N+1's `integrity_baseline` and is indistinguishable there from a human's test. `disposition.py`
calls every baselined path "a HUMAN/baselined test"; on a project's fourth item that statement is
simply false, and there is nowhere else in the engine to learn otherwise. This table is that
"otherwise".

**One append-only versioned table, not two.** Version 1 is a delivery; version N+1 is an
amendment; the version HISTORY is the amendment record ADR-0087 §4 asks for. A separate
amendments table would duplicate the key and let the two drift.

**The rule that carries the whole thing: never invent ownership.** A row exists only for a path a
run demonstrably authored or amended. A baselined path with no row means *we do not know who wrote
it* — which is the truth, and which the operator surface must say rather than attributing it to
whichever item happened to touch the file. False ownership is the one thing that would make the
amendment offer actively dangerous: it would tell a human "item #42 owns this bar" when nobody
does.

Separate module from ``models.py`` on the ``models_claims`` / ``models_map`` precedent (god-file
ratchet). Tables register on ``Base.metadata`` when ``store/_contracts.py`` imports them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mosaera_memory.models import Base, _utcnow

# How a version came to exist. `delivered` = a run authored this test and shipped it;
# `amended` = a later run changed it under an operator authorization (ADR-0087 §5).
# Deliberately NO "pre_existing" value: we do not write rows for paths we did not touch, so
# absence — not a label — is how "unknown provenance" is represented. A label would invite a
# future writer to stamp it on a guess.
CONTRACT_PROVENANCES = frozenset({"delivered", "amended"})
# Who authorized an amendment. `human` is the only value today (ADR-0087 §2's Proctor-owned
# amendment is DIRECTION, not built) — declared as a set so adding one is a deliberate act.
CONTRACT_AUTHORITIES = frozenset({"human"})


class TestContract(Base):
    """One version of one delivered test file's contract, within one project."""

    __tablename__ = "test_contracts"
    __table_args__ = (UniqueConstraint("project_id", "path", "version", name="uq_contract_ver"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(512), index=True)
    # 1 on first delivery; +1 per amendment. The sequence IS the history.
    version: Mapped[int] = mapped_column(Integer, default=1)
    provenance: Mapped[str] = mapped_column(String(32))  # one of CONTRACT_PROVENANCES
    # NULL means the owner is genuinely unknown — never a placeholder for "we didn't look".
    owner_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # SET NULL, not CASCADE: losing the run must not erase the fact that the contract exists.
    owner_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    # The integrity hash (testintegrity space) of the content at this version, so a later reader
    # can tell whether what is on disk IS this version or has drifted since.
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    # What this test binds — the item's acceptance text, as far as it is known. May be empty;
    # an empty criterion is honest, a guessed one is not.
    criterion: Mapped[str] = mapped_column(Text, default="")
    amended_from_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    authorized_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amend_reason: Mapped[str] = mapped_column(Text, default="")
    # Per-test-function assertion counts at this version (#66's `assertion_profile`). Makes a
    # weakening auditable ACROSS runs, which the per-run check cannot do.
    assertion_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
