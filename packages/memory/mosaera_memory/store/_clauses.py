"""Clause store: ratified operator decisions — read + append (ADR-0082 tier 2).

Persistence ONLY for ``StandardClause``. Methods are ``clause_``-prefixed so they never collide
across the mixins composed into ``MemoryStore`` (the ``CharterMixin`` pattern).

**This layer is NOT the trust boundary, and that is structural, not an oversight.** Whether a
clause may exist at all — does it cite a real standard, does that standard leave this parameter
open, does the parameter touch a proof-bearing gate reason — is decided by
``mosaera_policies.standards.validate_clause``, which this package cannot import: ``memory`` is a
leaf by the layer rule, and inverting that to reach ``policies`` would be a worse trade than the
one made here. So:

- the WRITE-time policy check lives in ``mosaera_core.clauses.ratify_clause``, the single caller of
  ``clause_insert`` (pinned by an architecture test);
- the READ-time check re-runs over every row in ``mosaera_core.clauses.load_clauses``, and that is
  the real guarantee — it is what makes a clause minted before the deny-list grew fail to load,
  and what catches any row that reached this table by some other path (a restored backup, a manual
  INSERT, a future second writer).

What this layer *does* own is SHAPE: value kind, the all-or-none condition, and the append-only
supersession that keeps a decision's history.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from mosaera_memory.models_clauses import CLAUSE_VALUE_KINDS, StandardClause
from mosaera_memory.store._base import StoreBase, _iso


def _clause_summary(row: StandardClause) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "standard_id": row.standard_id,
        "binds": row.binds,
        "value_kind": row.value_kind,
        "value_num": row.value_num,
        "when_param": row.when_param,
        "when_op": row.when_op,
        "when_num": row.when_num,
        "because": row.because,
        "author": row.author,
        "provenance": row.provenance or {},
        "ratified_at": _iso(row.ratified_at),
        "superseded_at": _iso(row.superseded_at) if row.superseded_at else None,
    }


class ClausesMixin(StoreBase):
    def clause_insert(
        self,
        clause_id: str,
        *,
        project_id: str | None,
        standard_id: str,
        binds: str,
        value_kind: str,
        value_num: int | None = None,
        when_param: str | None = None,
        when_op: str | None = None,
        when_num: int | None = None,
        because: str = "",
        author: str = "",
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append a clause, superseding any live one on the same (scope, standard, parameter).

        THE single writer — see the module docstring. It validates shape only; it does not and
        cannot know the policy limits, so calling it directly bypasses them. Supersession and
        insert share one transaction, so the table never holds two live clauses for one parameter
        even under a concurrent ratify.
        """
        if value_kind not in CLAUSE_VALUE_KINDS:
            raise ValueError(
                f"unknown clause value kind {value_kind!r}; "
                f"expected one of {sorted(CLAUSE_VALUE_KINDS)}"
            )
        if (value_num is None) == (value_kind == "number"):
            raise ValueError("a 'number' clause carries an integer value; other kinds carry none")
        condition = (when_param, when_op, when_num)
        if any(c is not None for c in condition) and not all(c is not None for c in condition):
            raise ValueError("a clause condition needs all of parameter, operator and value")
        if not standard_id or not binds:
            raise ValueError("a clause must cite a standard and bind a parameter")

        now = datetime.now(UTC)
        with self.session() as s, s.begin():
            live = s.execute(
                select(StandardClause).where(
                    StandardClause.project_id.is_(project_id)
                    if project_id is None
                    else StandardClause.project_id == project_id,
                    StandardClause.standard_id == standard_id,
                    StandardClause.binds == binds,
                    StandardClause.superseded_at.is_(None),
                )
            ).scalars()
            for prior in live:
                prior.superseded_at = now
            row = StandardClause(
                id=clause_id,
                project_id=project_id,
                standard_id=standard_id,
                binds=binds,
                value_kind=value_kind,
                value_num=value_num,
                when_param=when_param,
                when_op=when_op,
                when_num=when_num,
                because=because,
                author=author,
                provenance=provenance or {},
                ratified_at=now,
            )
            s.add(row)
            s.flush()
            return _clause_summary(row)

    def clause_list(
        self, project_id: str | None = None, *, include_superseded: bool = False
    ) -> list[dict[str, Any]]:
        """Clauses that apply to ``project_id``: its own PLUS every repo-scoped one.

        Repo-scoped clauses are stored once and read everywhere rather than copied per project —
        a copy would drift, and a drifted copy of a standing decision is the defect returning.
        """
        with self.session() as s:
            stmt = select(StandardClause)
            if project_id is not None:
                stmt = stmt.where(
                    (StandardClause.project_id == project_id) | StandardClause.project_id.is_(None)
                )
            else:
                stmt = stmt.where(StandardClause.project_id.is_(None))
            if not include_superseded:
                stmt = stmt.where(StandardClause.superseded_at.is_(None))
            rows = s.execute(stmt.order_by(StandardClause.ratified_at)).scalars().all()
            return [_clause_summary(r) for r in rows]
