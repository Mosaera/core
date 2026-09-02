"""Test-contract registry operations (ADR-0087 §1-§4).

Validation happens HERE, at the write boundary, before any session opens — the ``_claims``
precedent — so the validators are testable offline and a bad row can never land half-written.
Method names embed ``test_contract`` so they cannot collide across the composed mixins.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from mosaera_memory.models_contracts import (
    CONTRACT_AUTHORITIES,
    CONTRACT_PROVENANCES,
    TestContract,
)
from mosaera_memory.store._base import StoreBase, _iso


def _contract_summary(row: TestContract) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "path": row.path,
        "version": row.version,
        "provenance": row.provenance,
        "owner_item_id": row.owner_item_id,
        "owner_run_id": row.owner_run_id,
        "content_hash": row.content_hash,
        "criterion": row.criterion,
        "amended_from_version": row.amended_from_version,
        "authorized_by": row.authorized_by,
        "amend_reason": row.amend_reason,
        "assertion_profile": dict(row.assertion_profile or {}),
        "created_at": _iso(row.created_at),
    }


class ContractsMixin(StoreBase):
    def record_test_contract(
        self,
        project_id: str,
        path: str,
        *,
        provenance: str,
        owner_item_id: int | None = None,
        owner_run_id: str | None = None,
        content_hash: str = "",
        criterion: str = "",
        authorized_by: str | None = None,
        amend_reason: str = "",
        assertion_profile: dict[str, Any] | None = None,
    ) -> int | None:
        """Append the next version of ``path``'s contract. Returns its version, or None.

        Returns **None** when the content is unchanged from the latest version — re-delivering an
        identical file is not a new contract, and versioning it would turn the history into noise
        and make "how often is this bar amended?" unanswerable.

        The version is derived from what is already stored, never supplied by the caller: two
        concurrent writers must not be able to agree on a number.
        """
        if provenance not in CONTRACT_PROVENANCES:
            raise ValueError(f"unknown contract provenance: {provenance!r}")
        if authorized_by is not None and authorized_by not in CONTRACT_AUTHORITIES:
            raise ValueError(f"unknown contract authority: {authorized_by!r}")
        if not path.strip():
            raise ValueError("contract path is required")
        with self.session() as s, s.begin():
            rows = list(
                s.scalars(
                    select(TestContract)
                    .where(TestContract.project_id == project_id, TestContract.path == path)
                    .order_by(TestContract.version.desc())
                )
            )
            latest = rows[0] if rows else None
            if latest is not None and content_hash and latest.content_hash == content_hash:
                return None  # identical content — not a new version
            version = (latest.version + 1) if latest is not None else 1
            # An amendment changes a bar's CONTENT, not whose bar it is. Carry the origin forward
            # when the caller does not supply it, or the operator surface loses the one fact it
            # most needs ("this test was authored for item #42") the moment a bar is amended —
            # which is precisely when they are being asked to judge it. Supplying a value still
            # wins; this only fills a gap, and never invents one where none existed.
            s.add(
                TestContract(
                    project_id=project_id,
                    path=path,
                    version=version,
                    provenance=provenance,
                    owner_item_id=(
                        owner_item_id
                        if owner_item_id is not None or latest is None
                        else latest.owner_item_id
                    ),
                    owner_run_id=owner_run_id,
                    content_hash=content_hash,
                    criterion=criterion or (latest.criterion if latest is not None else ""),
                    # Only an amendment has something to amend FROM.
                    amended_from_version=latest.version if latest is not None else None,
                    authorized_by=authorized_by,
                    amend_reason=amend_reason,
                    assertion_profile=dict(assertion_profile or {}),
                )
            )
            return version

    def latest_test_contracts(self, project_id: str, paths: list[str]) -> dict[str, dict[str, Any]]:
        """The CURRENT contract for each of ``paths``, keyed by path. Missing paths are absent.

        Absent means the owner is unknown, and a caller must present it that way. This method
        deliberately returns nothing for an unregistered path rather than a stub row: a stub is
        how an invented owner gets into an operator's view.
        """
        if not paths:
            return {}
        with self.session() as s:
            rows = list(
                s.scalars(
                    select(TestContract)
                    .where(
                        TestContract.project_id == project_id, TestContract.path.in_(list(paths))
                    )
                    .order_by(TestContract.version.asc())
                )
            )
        # Ascending order means the last write per path wins — the highest version.
        return {row.path: _contract_summary(row) for row in rows}

    def test_contract_history(self, project_id: str, path: str) -> list[dict[str, Any]]:
        """Every version of one contract, oldest first — the amendment record (ADR-0087 §4)."""
        with self.session() as s:
            rows = list(
                s.scalars(
                    select(TestContract)
                    .where(TestContract.project_id == project_id, TestContract.path == path)
                    .order_by(TestContract.version.asc())
                )
            )
        return [_contract_summary(r) for r in rows]
