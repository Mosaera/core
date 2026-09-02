"""Project-MAP ORM models: the UNTRUSTED, recon-derived view of a project (issue #40, ADR-0047).

This is the *untrusted* half of onboarding. Recon reads READMEs, docstrings, comments, CI configs
and docs — repo content that ``AGENTS.md`` requires treating as **data, not instructions** — and
distills it into a DURABLE artifact that steers every future run. A poisoned map is therefore
*persistent* compromise (re-injected on every run, surviving restarts, looking like institutional
knowledge), so this schema is deliberately shaped by constraints, not convenience (ADR-0047 §1/§5):

- **Provenance is mandatory.** Every observation carries the source LOCATION it came from; there is
  no way to store a bare claim. "``README.md:12`` *claims* the suite is comprehensive" is a legal
  entry; "the suite is comprehensive" is not — the latter launders an untrusted claim into a firm
  belief and strips the provenance that lets anyone check it. Observations are *data*; core/agents
  quote + attribute + fence them at prompt-assembly time — this layer never emits imperatives.
- **A dimension that could not run says so.** ``status`` is a tri-state (``finding``/``clean``/
  ``unavailable``); ``unavailable`` is never collapsed into a passing score or a silent omission
  (ADR-0033's false-green fix / ADR-0035 loud-failure).
- **Freshness is per-dimension and deny-by-default.** Each dimension carries its own ``fingerprint``
  over just its inputs and when it was ``computed_at``; a NULL/mismatched fingerprint resolves to
  STALE, never fresh (see ``MapMixin.stale_map_dimensions``).

Split out of ``models.py`` (at the modularity ceiling) but part of the SAME declarative ``Base``.
These tables register on ``Base.metadata`` when the map mixin (``store/_map.py``) imports them —
which happens whenever ``MemoryStore`` loads — so they are NOT re-exported through ``models.py``
(keeping that file under the god-file ceiling). Kept in its OWN module (distinct from the trusted
``models_charter``) on purpose: it lets the layer guard forbid the map — and only the map — to
``packages/policies`` (ADR-0047 §2, ``scripts/check_layer_imports.py``). The map informs SCOPING;
it must never reach the GATE.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mosaera_memory.models import Base, _utcnow

# The recon dimensions (ADR-0047 §3, the north-star list). Deny-by-default: the store rejects any
# dimension outside this set, so a typo can't silently create an orphan dimension the UI never sees.
# These names + the observation ``text`` field match #41 recon's ``DIMENSION_NAMES`` /
# ``Observation.as_dict()`` wire format, so #42 wires ``DimensionResult.as_dict()`` straight in.
MAP_DIMENSIONS: frozenset[str] = frozenset(
    {"security", "tests", "structure", "quality", "cleanliness", "deps", "docs", "ci"}
)

# The honest tri-state (ADR-0047 §5). ``unavailable`` = "we did not / could not check" — NEVER
# rendered as ``clean``. Rejected at the store boundary if a caller passes anything else.
MAP_STATUSES: frozenset[str] = frozenset({"finding", "clean", "unavailable"})

# The advisory per-observation triage hint (ordering only, never a gate input). Deny-by-default:
# the store CLAMPS an unrecognized value to ``info`` (the neutral floor) rather than rejecting —
# severity is advisory, so a bad value degrades to neutral instead of failing the whole upsert.
MAP_SEVERITIES: frozenset[str] = frozenset({"info", "low", "medium", "high", "critical"})


class ProjectMapDimension(Base):
    """One recon dimension's distilled state for a project.

    - ``dimension`` — which of ``MAP_DIMENSIONS`` this row is (one row per project+dimension).
    - ``status`` — tri-state ``finding``/``clean``/``unavailable`` (never collapsed to ``clean``).
    - ``fingerprint`` — hash over just THIS dimension's inputs (lockfile hash for deps, CI-config
      hash for ci, …). NULL means "unknown" ⇒ the dimension is treated as STALE (§4). A
      lockfile edit must not invalidate the security scan, hence per-dimension keys.
    - ``unavailable_reason`` — why the dimension could not run (ADR-0035: loud, not silent).
    - ``computed_at`` — when this dimension was last reconned (the freshness stamp the UI shows).

    Unique per ``(project_id, dimension)`` so a re-recon UPSERTS in place — the map compounds
    instead of accumulating duplicate rows (mirrors ``CoverageLedger``)."""

    __tablename__ = "project_map_dimensions"
    __table_args__ = (UniqueConstraint("project_id", "dimension", name="uq_map_dimension"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    dimension: Mapped[str] = mapped_column(String(32))  # one of MAP_DIMENSIONS
    status: Mapped[str] = mapped_column(String(16))  # one of MAP_STATUSES (tri-state)
    # NULL fingerprint = unknown freshness ⇒ stale (deny-by-default, §4). Not the raw tree hash;
    # it is a hash over only this dimension's own inputs, computed upstream and handed in.
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unavailable_reason: Mapped[str] = mapped_column(Text, default="")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Re-recon replaces a dimension's observations wholesale, so they are owned children.
    observations: Mapped[list[ProjectMapObservation]] = relationship(
        back_populates="dimension", cascade="all, delete-orphan"
    )


class ProjectMapObservation(Base):
    """One provenanced FACT under a dimension — the anti-injection unit of the map.

    - ``provenance`` — the source LOCATION the fact came from (``README.md:12``, ``poetry.lock``,
      ``.gitlab-ci.yml:job``). REQUIRED (the store rejects an empty one): a map entry is only ever
      an observation *about a place in the repo*, never a free-floating belief.
    - ``text`` — the fact itself, as DATA. Core/agents quote + attribute it at prompt time; this
      layer stores it verbatim and never treats it as an instruction.
    - ``severity`` — an ordering hint (``info``/``low``/``medium``/``high``/``critical``); advisory.

    Security: a ``gitleaks`` finding IS a leaked-credential location. An observation records the
    finding LOCATION and TYPE — **never the secret value** (ADR-0047 security implications). The
    schema can't detect a pasted secret, so the recon dimension (#41) must honour this; the column
    docstring states the contract."""

    __tablename__ = "project_map_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dimension_id: Mapped[int] = mapped_column(
        ForeignKey("project_map_dimensions.id", ondelete="CASCADE"), index=True
    )
    # Source LOCATION only — never a secret value (gitleaks records where, not what).
    provenance: Mapped[str] = mapped_column(String(512))
    text: Mapped[str] = mapped_column(Text)  # the fact as data; attributed/fenced at prompt time
    severity: Mapped[str] = mapped_column(String(16), default="info")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    dimension: Mapped[ProjectMapDimension] = relationship(back_populates="observations")
