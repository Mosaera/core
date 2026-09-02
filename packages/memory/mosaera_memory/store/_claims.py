"""Claim-ledger store operations (ADR-0079 Wave 2).

Validation happens HERE, at the write boundary, BEFORE any session opens — so the validators
are testable fully offline (the ``_OFFLINE_URL`` pattern) and a bad row can never reach the
database half-written. Method names embed ``run_claims`` so they never collide across the
composed mixins.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from mosaera_memory.models_claims import (
    CLAIM_ORACLE_KINDS,
    CLAIM_PROVENANCES,
    CLAIM_VERDICTS,
    RunClaim,
)
from mosaera_memory.store._base import StoreBase, _iso


def _claim_summary(row: RunClaim) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "claim_id": row.claim_id,
        "item_id": row.item_id,
        "text": row.text,
        "provenance": row.provenance,
        "oracle_kind": row.oracle_kind,
        "predicate": row.predicate,
        "material": bool(row.material),
        "verdict": row.verdict,
        "oracle_ref": row.oracle_ref,
        "schema_version": row.schema_version,
        "created_at": _iso(row.created_at),
    }


class ClaimsMixin(StoreBase):
    def add_run_claims(self, run_id: str, rows: list[dict[str, Any]]) -> None:
        """Append the run's claim+disposition rows. Validates EVERY row before opening a
        session — one bad row rejects the whole batch (no half-written ledger)."""
        validated: list[RunClaim] = []
        for i, r in enumerate(rows):
            provenance = str(r.get("provenance") or "")
            kind = str(r.get("oracle_kind") or "")
            verdict = str(r.get("verdict") or "")
            if provenance not in CLAIM_PROVENANCES:
                raise ValueError(f"row {i}: unknown provenance {provenance!r}")
            if kind not in CLAIM_ORACLE_KINDS:
                raise ValueError(f"row {i}: unknown oracle_kind {kind!r}")
            if verdict not in CLAIM_VERDICTS:
                raise ValueError(f"row {i}: unknown verdict {verdict!r}")
            claim_id = str(r.get("claim_id") or "")
            if not claim_id:
                raise ValueError(f"row {i}: empty claim_id")
            validated.append(
                RunClaim(
                    run_id=run_id,
                    claim_id=claim_id,
                    item_id=r.get("item_id"),
                    text=str(r.get("text") or ""),
                    provenance=provenance,
                    oracle_kind=kind,
                    predicate=str(r.get("predicate") or ""),
                    material=bool(r.get("material", True)),
                    verdict=verdict,
                    oracle_ref=str(r.get("oracle_ref") or "")[:512],
                    schema_version=int(r.get("schema_version") or 1),
                )
            )
        if not validated:
            return
        with self.session() as s, s.begin():
            s.add_all(validated)

    def list_run_claims(self, run_id: str) -> list[dict[str, Any]]:
        stmt = select(RunClaim).where(RunClaim.run_id == run_id).order_by(RunClaim.id)
        with self.session() as s:
            return [_claim_summary(r) for r in s.scalars(stmt)]

    def list_item_claims(self, item_id: int) -> list[dict[str, Any]]:
        """The LATEST disposition of every claim ever evaluated for one item.

        `(item_id, claim_id)` is the cross-run key (`models_claims.py:47-50`), so a claim re-derived
        on each launch accumulates one row per run and only the newest is current. Ordering by `id`
        and keeping the last per `claim_id` gives that without a window function.

        This is the read the North Star's defining question needs — *"does every acceptance
        criterion now have evidence?"* (`north-star.md:157`) — and it did not exist: the ledger has
        always been queryable only by RUN, so the question could be answered about one execution and
        never about a piece of work.

        What it deliberately does NOT do is decide whether the item is covered. Claims are derived
        from the acceptance text at launch, so a criterion added since the last run has no row here
        at all, and its ABSENCE is the answer. Reconciling these rows against the item's current
        acceptance belongs to the caller, which is the only place both are known.
        """
        stmt = select(RunClaim).where(RunClaim.item_id == item_id).order_by(RunClaim.id)
        with self.session() as s:
            latest: dict[str, dict[str, Any]] = {}
            for row in s.scalars(stmt):
                latest[row.claim_id] = _claim_summary(row)
            return list(latest.values())
