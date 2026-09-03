"""Project-CHARTER ORM model: the TRUSTED, operator-authored project intent (issue #40, ADR-0047).

The *trusted* half of onboarding, and the deliberate opposite of the map (``models_map``). The
charter is what the OPERATOR says — goal, posture, constraints — captured through the interview, so
it is the one artifact that MAY carry imperatives (it is instruction, not data). Recon must never
write it: inferring the goal from the repo is the ADR-0047 §1 violation in its most attractive form
(it silently promotes untrusted repo content to operator intent). Hence "edited, never recomputed"
(§7) — expressed here structurally by the absence of any recompute-from-map path, and by keeping
this model in its OWN module so the charter and the untrusted map can never be confused.

``posture`` (ADR-0046) makes charter writes a GOVERNANCE surface, not a preference one: the calling
route (#42) must be admin-gated (ADR-0004), the write audited, and a project may only be *more*
restrictive than the firm default. This store layer persists the validated value; the lattice
enforcement (posture clamping the autonomy knobs at the gate) is later governance work, not #40.

Split out of ``models.py`` (at the modularity ceiling) but part of the SAME declarative ``Base``.
It registers on ``Base.metadata`` when the charter mixin (``store/_charter.py``) imports it — which
happens whenever ``MemoryStore`` loads — so it is not re-exported through ``models.py`` (keeping
that file under the god-file ceiling).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mosaera_memory.models import Base, _utcnow

# The posture tiers (ADR-0046), ordered least→most restrictive. Deny-by-default: the store rejects
# any value outside this set (the "no free-text for enumerable values" rule, ADR-0005, applied at
# the persistence boundary too — a typo can never become an invalid posture).
CHARTER_POSTURES: frozenset[str] = frozenset({"free", "business", "regulated"})
DEFAULT_POSTURE = "business"


class ProjectCharter(Base):
    """One project's operator-authored charter (one row per project — ``project_id`` is the PK).

    - ``goal`` — what the operator wants built (the one thing only the operator knows; recon may
      never infer it).
    - ``constraints`` — operator-stated bounds (stack choices, no-go areas, house rules).
    - ``posture`` — the autonomy tier (``CHARTER_POSTURES``); a governance value, admin-gated at
      the route (#42), persisted validated here.

    ``project_id`` is the primary key AND a CASCADE foreign key: deleting a project removes its
    charter, and the 1:1 shape is enforced by the schema (no surrogate id, no duplicates)."""

    __tablename__ = "project_charters"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    goal: Mapped[str] = mapped_column(Text, default="")
    constraints: Mapped[str] = mapped_column(Text, default="")
    posture: Mapped[str] = mapped_column(
        String(16), default=DEFAULT_POSTURE
    )  # one of CHARTER_POSTURES
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
