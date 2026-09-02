"""Map store: the UNTRUSTED, recon-derived map — upsert, read, per-dimension freshness (#40).

Persistence ONLY for ``ProjectMapDimension`` + ``ProjectMapObservation`` (recon itself is #41).
Modeled on ``CoverageMixin`` (#32); methods embed ``map`` so they never collide across the mixins
composed into ``MemoryStore``.

The security posture of ADR-0047 is enforced HERE, at the write boundary:

- **Provenance is mandatory (§1).** ``upsert_map_dimension`` rejects any observation without a
  non-empty ``provenance`` — you cannot store a bare claim, only an observation *about a location*.
- **Enumerable values are validated (§3/§5, ADR-0005).** ``dimension`` and ``status`` must be in
  ``MAP_DIMENSIONS`` / ``MAP_STATUSES`` (deny-by-default; a typo can't create a ghost dimension or
  an off-tri-state status).
- **Unknown freshness ⇒ stale (§4).** ``stale_map_dimensions`` treats a missing row, a NULL
  fingerprint, or a mismatched fingerprint as STALE. A stale map that presents itself as current is
  worse than no map, so freshness fails safe (mirrors ``CoverageMixin.stale_coverage_regions``).

This layer stores observations verbatim as DATA; quoting/attributing/fencing them into a prompt is
core/agents' job — memory never emits an imperative, and ``packages/policies`` may never import this
module (the layer guard makes "the map never reaches the gate" structural)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from mosaera_memory.models_map import (
    MAP_DIMENSIONS,
    MAP_SEVERITIES,
    MAP_STATUSES,
    ProjectMapDimension,
    ProjectMapObservation,
)
from mosaera_memory.store._base import StoreBase, _iso


def _observation_summary(row: ProjectMapObservation) -> dict[str, Any]:
    return {
        "provenance": row.provenance,
        "text": row.text,
        "severity": row.severity,
    }


def _dimension_summary(row: ProjectMapDimension) -> dict[str, Any]:
    return {
        "project_id": row.project_id,
        "dimension": row.dimension,
        "status": row.status,
        "fingerprint": row.fingerprint,
        "unavailable_reason": row.unavailable_reason,
        "computed_at": _iso(row.computed_at),
        "observations": [
            _observation_summary(o)
            for o in sorted(row.observations, key=lambda o: (o.severity, o.provenance))
        ],
    }


class MapMixin(StoreBase):
    def upsert_map_dimension(
        self,
        project_id: str,
        dimension: str,
        *,
        status: str,
        fingerprint: str | None = None,
        observations: Iterable[Mapping[str, str]] = (),
        unavailable_reason: str = "",
    ) -> None:
        """Record (or refresh) one recon dimension. Idempotent per ``(project, dimension)``: a
        re-recon overwrites status/fingerprint/reason, REPLACES the dimension's observations
        wholesale, and stamps ``computed_at`` now — so the map COMPOUNDS in place instead of
        duplicating rows.

        Validates deny-by-default, raising ``ValueError`` before any write: ``dimension`` in
        ``MAP_DIMENSIONS``, ``status`` in ``MAP_STATUSES``, every observation carries a non-empty
        ``provenance`` (a fact must say where it came from — §1), and the tri-state is CONSISTENT
        (§5) — ``clean`` carries no observations, ``finding`` carries at least one, ``unavailable``
        carries a reason. Each observation mapping is ``{"provenance", "text", "severity"?}``."""
        if dimension not in MAP_DIMENSIONS:
            raise ValueError(
                f"unknown dimension {dimension!r}; expected one of {sorted(MAP_DIMENSIONS)}"
            )
        if status not in MAP_STATUSES:
            raise ValueError(f"unknown status {status!r}; expected one of {sorted(MAP_STATUSES)}")
        obs = list(observations)
        for o in obs:
            if not (o.get("provenance") or "").strip():
                raise ValueError(
                    "every map observation needs a non-empty 'provenance' (the source location) — "
                    "the map records facts about the repo, never free-floating claims (ADR-0047 §1)"
                )
        # Tri-state HONESTY (ADR-0047 §5 / ADR-0033/0035), enforced HERE at the durable write
        # boundary — not delegated to an upstream dataclass a backfill or #42 could bypass with raw
        # kwargs. This is the same class of check the provenance/enum guards above already make: a
        # 'clean' that hides a finding is the false-green ADR-0033 exists to prevent; an
        # 'unavailable' with no reason is the silent no-op ADR-0035 bans.
        if status == "clean" and obs:
            raise ValueError(
                "status 'clean' cannot carry observations — a clean dimension has no findings; use "
                "'finding' (ADR-0047 §5)"
            )
        if status == "finding" and not obs:
            raise ValueError(
                "status 'finding' needs at least one provenanced observation (ADR-0047 §5)"
            )
        if status == "unavailable" and not unavailable_reason.strip():
            raise ValueError(
                "status 'unavailable' needs a non-empty unavailable_reason — say WHY it could not "
                "run, never a silent no-op (ADR-0035)"
            )
        now = datetime.now(UTC)
        with self.session() as s, s.begin():
            row = s.scalars(
                select(ProjectMapDimension).where(
                    ProjectMapDimension.project_id == project_id,
                    ProjectMapDimension.dimension == dimension,
                )
            ).first()
            if row is None:
                row = ProjectMapDimension(
                    project_id=project_id, dimension=dimension, created_at=now
                )
                s.add(row)
            row.status = status
            row.fingerprint = fingerprint
            row.unavailable_reason = unavailable_reason
            row.computed_at = now
            row.updated_at = now
            # Replace the observation set wholesale (delete-orphan handles the old rows).
            row.observations = [
                ProjectMapObservation(
                    provenance=o["provenance"].strip(),
                    text=o.get("text", ""),
                    # Clamp an unrecognized severity to the neutral floor (deny-by-default): it is
                    # advisory ordering, so a bad value degrades rather than failing the upsert.
                    severity=(
                        sev if (sev := o.get("severity", "info")) in MAP_SEVERITIES else "info"
                    ),
                    created_at=now,
                )
                for o in obs
            ]

    def get_map_dimension(self, project_id: str, dimension: str) -> dict[str, Any] | None:
        with self.session() as s:
            row = s.scalars(
                select(ProjectMapDimension).where(
                    ProjectMapDimension.project_id == project_id,
                    ProjectMapDimension.dimension == dimension,
                )
            ).first()
            return _dimension_summary(row) if row is not None else None

    def list_map_dimensions(self, project_id: str) -> list[dict[str, Any]]:
        stmt = (
            select(ProjectMapDimension)
            .where(ProjectMapDimension.project_id == project_id)
            .order_by(ProjectMapDimension.dimension)
        )
        with self.session() as s:
            return [_dimension_summary(r) for r in s.scalars(stmt)]

    def stale_map_dimensions(
        self, project_id: str, current_fingerprints: Mapping[str, str]
    ) -> list[str]:
        """FRESHNESS, deny-by-default (§4): given the caller's freshly-computed per-dimension
        fingerprints, return the dimensions that are STALE and must be re-reconned. A dimension is
        stale when it has no stored row, a FALSY stored fingerprint (NULL *or* empty ⇒ unknown ⇒
        stale), a falsy CURRENT fingerprint (the caller has no meaningful input hash), or a stored
        fingerprint that differs from the current one. Unknown freshness NEVER resolves to fresh —
        a stale map presenting itself as current is worse than no map, so an empty string must not
        read fresh against another empty string. Only the dimensions the caller names are
        considered (so a caller wanting a complete freshness check must pass every dimension)."""
        if not current_fingerprints:
            return []
        keys = list(current_fingerprints.keys())
        stmt = select(ProjectMapDimension).where(
            ProjectMapDimension.project_id == project_id,
            ProjectMapDimension.dimension.in_(keys),
        )
        with self.session() as s:
            stored = {r.dimension: r.fingerprint for r in s.scalars(stmt)}
        # Missing row, falsy (NULL/empty) stored OR current fingerprint, or a mismatch ⇒ stale.
        # A falsy fingerprint is "no meaningful input hash" = unknown, and unknown fails safe to
        # stale — closing the empty-string-reads-fresh hole the plain `is None` check left open.
        return sorted(
            dim
            for dim, current in current_fingerprints.items()
            if not stored.get(dim) or not current or stored.get(dim) != current
        )
