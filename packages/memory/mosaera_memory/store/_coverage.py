"""Coverage ledger: the durable code↔test map — upsert, impact-selection, rot detection (#32).

A DISTILLED, compounding form of ``mosaera_core.coveragemap.CoverageMap`` — one row per
``(project, region)``. This mixin owns persistence ONLY; region extraction + fingerprinting are
computed upstream (the graph ``test_node`` → ledger integration, out of scope for #32) via
``mosaera_memory._fingerprint`` and handed in, keeping ``memory`` a leaf. Modeled on
``SessionsMixin`` (#30); methods are ``coverage_``-prefixed so they never collide across the
mixins composed into ``MemoryStore``."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from mosaera_memory.models import CoverageLedger
from mosaera_memory.store._base import StoreBase, _iso


def _ledger_summary(row: CoverageLedger) -> dict[str, Any]:
    return {
        "project_id": row.project_id,
        "region_key": row.region_key,
        "region_fingerprint": row.region_fingerprint,
        "source_hash": row.source_hash,
        "covering_tests": list(row.covering_tests or []),
        "mutation_caught": row.mutation_caught,
        "last_verified_at": _iso(row.last_verified_at),
    }


class CoverageMixin(StoreBase):
    def upsert_coverage_region(
        self,
        project_id: str,
        region_key: str,
        *,
        region_fingerprint: str,
        source_hash: str,
        covering_tests: Iterable[str],
        mutation_caught: bool | None = None,
    ) -> None:
        """Record (or refresh) a region's coverage. Idempotent per ``(project, region_key)``: a
        re-verification overwrites the fingerprint / hash / tests / verdict and stamps
        ``last_verified_at`` now — so the map COMPOUNDS in place instead of duplicating rows.
        ``covering_tests`` is de-duplicated + sorted for a stable stored order."""
        tests = sorted(set(covering_tests))
        now = datetime.now(UTC)
        with self.session() as s, s.begin():
            row = s.scalars(
                select(CoverageLedger).where(
                    CoverageLedger.project_id == project_id,
                    CoverageLedger.region_key == region_key,
                )
            ).first()
            if row is None:
                s.add(
                    CoverageLedger(
                        project_id=project_id,
                        region_key=region_key,
                        region_fingerprint=region_fingerprint,
                        source_hash=source_hash,
                        covering_tests=tests,
                        mutation_caught=mutation_caught,
                        last_verified_at=now,
                    )
                )
            else:
                row.region_fingerprint = region_fingerprint
                row.source_hash = source_hash
                row.covering_tests = tests
                row.mutation_caught = mutation_caught
                row.last_verified_at = now
                row.updated_at = now

    def get_coverage_region(self, project_id: str, region_key: str) -> dict[str, Any] | None:
        with self.session() as s:
            row = s.scalars(
                select(CoverageLedger).where(
                    CoverageLedger.project_id == project_id,
                    CoverageLedger.region_key == region_key,
                )
            ).first()
            return _ledger_summary(row) if row is not None else None

    def list_coverage_regions(self, project_id: str) -> list[dict[str, Any]]:
        stmt = (
            select(CoverageLedger)
            .where(CoverageLedger.project_id == project_id)
            .order_by(CoverageLedger.region_key)
        )
        with self.session() as s:
            return [_ledger_summary(r) for r in s.scalars(stmt)]

    def select_covering_tests(self, project_id: str, region_keys: Iterable[str]) -> list[str]:
        """Impact-based test SELECTION: the union of covering tests over the given (changed)
        regions — the subset of the suite worth running for this change. Unknown regions
        contribute nothing (deny-by-default: the caller runs the full suite when the ledger has
        no coverage for a changed region)."""
        keys = list(dict.fromkeys(region_keys))
        if not keys:
            return []
        stmt = select(CoverageLedger.covering_tests).where(
            CoverageLedger.project_id == project_id,
            CoverageLedger.region_key.in_(keys),
        )
        out: set[str] = set()
        with self.session() as s:
            for (tests,) in s.execute(stmt):
                out.update(tests or [])
        return sorted(out)

    def stale_coverage_regions(
        self, project_id: str, current_region_fingerprints: Mapping[str, str]
    ) -> list[dict[str, Any]]:
        """ROT detection: stored regions whose CODE meaningfully changed since coverage was last
        verified — the churn-stable ``region_fingerprint`` differs from the stored one. Keyed on the
        FINGERPRINT (normalized source), not the raw ``source_hash``, so a purely cosmetic edit
        (reindent, blank/comment churn) keeping the fingerprint does NOT invalidate coverage — only
        a real code change flips it. Compared only for the region keys the caller provides (the
        regions it just re-fingerprinted); a matching fingerprint is fresh."""
        if not current_region_fingerprints:
            return []
        keys = list(current_region_fingerprints.keys())
        stmt = select(CoverageLedger).where(
            CoverageLedger.project_id == project_id,
            CoverageLedger.region_key.in_(keys),
        )
        with self.session() as s:
            return [
                _ledger_summary(r)
                for r in s.scalars(stmt)
                if current_region_fingerprints.get(r.region_key) != r.region_fingerprint
            ]
