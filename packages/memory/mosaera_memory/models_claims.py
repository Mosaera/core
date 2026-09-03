"""The claim ledger (ADR-0079): per-run acceptance claims + their evaluated dispositions.

One row per claim per run — claims are re-derived from the item's operator-approved acceptance
at every launch, so the run-scoped row IS the ledger entry; cross-run claim identity is
`(item_id, claim_id)`. Rows are append-only per run and carry BOTH the claim (text, provenance,
oracle binding) and the verdict the run's oracles produced, which is exactly what an auditor
needs to reconstruct "what was promised, what proved it, what happened" (ADR-0063).

A separate module from ``models.py`` on the ``models_map.py`` precedent: it keeps the god-file
ratchet honest and lets ``scripts/check_layer_imports.py`` ban this module to ``policies``
later if ever needed (the gate never reads storage — ADR-0079 §4). Tables register on
``Base.metadata`` when ``store/_claims.py`` imports them.

Vocabulary note: memory is a strict leaf (it cannot import ``mosaera_core.claims``), so the
allowed sets are re-declared here; ``packages/memory/tests`` cross-checks them against core's
so the two can never drift silently.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mosaera_memory.models import Base, _utcnow

# Mirrors mosaera_core.claims.PROVENANCES / ORACLE_KINDS and claim_oracles.VERDICTS —
# cross-checked by test (memory cannot import core; drift fails the suite, not silently).
CLAIM_PROVENANCES = frozenset({"ENTAILED", "REPOSITORY_INVARIANT", "INFERRED"})
CLAIM_ORACLE_KINDS = frozenset(
    {
        "acceptance_test",
        "validation_exit",
        "tests_unmodified",
        "ast_transformation_contract",
        "wellformedness_parse",
        "non_use",
        "consumer_impact",
        "none",
    }
)
CLAIM_VERDICTS = frozenset({"satisfied", "failed", "unbound", "unevaluable"})


class RunClaim(Base):
    __tablename__ = "run_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    # The claim's id within its item (e.g. "7-c2"); (item_id, claim_id) is the cross-run key.
    claim_id: Mapped[str] = mapped_column(String(64))
    item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    # No bare claims (the ProjectMapObservation precedent): provenance is NOT NULL and
    # validated at the write boundary (store/_claims.py), one of CLAIM_PROVENANCES.
    provenance: Mapped[str] = mapped_column(String(32))
    oracle_kind: Mapped[str] = mapped_column(String(32))  # one of CLAIM_ORACLE_KINDS
    predicate: Mapped[str] = mapped_column(Text, default="")
    material: Mapped[bool] = mapped_column(Boolean, default=True)
    verdict: Mapped[str] = mapped_column(String(16))  # one of CLAIM_VERDICTS
    # The evidence POINTER (location/name, never a value — the provenance rule).
    oracle_ref: Mapped[str] = mapped_column(String(512), default="")
    schema_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
