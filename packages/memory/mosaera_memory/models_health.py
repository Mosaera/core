"""Is this project's test suite green — and for WHICH tree?

One row per project. The verdict is keyed by `tree_hash`, so it is a fact about a specific state of
the repository rather than a fact about a moment in time. That is what makes it both safe to reuse
(same tree ⇒ same answer, no re-run) and safe to invalidate (a delivery, an external merge, or
`check_base_drift`'s fast-forward changes the hash ⇒ the answer no longer applies).

The model is Bazel's: an action is indexed by a digest of its inputs and unchanged targets are never
re-run. Mosaera's own evidence cache already works this way (ADR-0003, `evidence_memo` keyed by
`tree_hash`); this is the same idea given a durable home so it survives the run that computed it.

**Written when the suite is MEASURED, not when a run ends.** `persist_run` is only reached from
`deliver_node`, so a resilient-sweep give-up, a cancelled run, a crash, or a park nobody answers
records nothing at all — and those are exactly the runs whose knowledge is most worth keeping.
Writing at the measurement point means the fact is already durable before the run's fate is decided.

`verdict` is the same honest tri-state used everywhere else in this codebase: an unreadable
validator is `unknown`, never `failed`. Recording "broken" on the strength of output nobody could
parse would make the control fire on its own blindness.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from mosaera_memory.models import Base, _utcnow

#: `pass` — every planned step succeeded. `failed` — a step failed. `unknown` — no honest answer
#: (no validation possible, or output that could not be parsed). Deny-by-default at the boundary:
#: the store rejects anything outside this set, so a typo can never become a verdict.
SUITE_VERDICTS: frozenset[str] = frozenset({"pass", "failed", "unknown"})


class ProjectSuiteHealth(Base):
    """The last measured suite verdict for a project, and the tree it was measured on."""

    __tablename__ = "project_suite_health"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    #: The workspace tree hash the verdict belongs to (`Workspace.tree_hash`). A verdict without
    #: its tree is the bug this table exists to fix: `tests_passed` was a point-in-time fact in a
    #: channel nothing invalidated, so a tree could be committed that no run had ever validated.
    tree_hash: Mapped[str] = mapped_column(String(64))
    verdict: Mapped[str] = mapped_column(String(16))
    #: Failing test ids at that measurement. Kept so the NEXT run can tell "already broken" from
    #: "you broke it" without re-deriving anything (`graph/_baseline.caused_regressions`).
    failing: Mapped[list | None] = mapped_column(JSON, nullable=True)
    #: Which run measured it — provenance, so a disputed verdict can be traced to its transcript.
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
