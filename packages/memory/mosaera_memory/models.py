"""SQLAlchemy ORM models for durable run memory.

Scoped to what the PM -> Coder -> Reviewer loop produces today: runs and the
decisions, code changes, test results, and embeddable artifacts they generate.
The broader brief schema (projects/teams/agents/approvals/audit_events) is
deferred until the API slice needs it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# nomic-embed-text produces 768-dimensional embeddings.
EMBED_DIM = 768


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


# The per-run approval modes (ADR-0012; plain names amended by ADR-0101 to ask/accept/auto). Same
# deny-by-default treatment as ``CHARTER_POSTURES``: the store rejects anything outside this set, so
# a typo can never become a stored run mode. Kept in sync with the API's `RunItemBody.mode` Literal
# by `test_run_modes_in_sync` — memory is a leaf and cannot import apps/api, so the pairing is
# pinned by a test rather than by an import (the CHARTER_POSTURES precedent).
RUN_MODES: frozenset[str] = frozenset({"guided", "autonomous", "high_assurance"})
DEFAULT_RUN_MODE = "guided"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # proj-<slug>-<hex>
    name: Mapped[str] = mapped_column(String(256))
    source_repo: Mapped[str] = mapped_column(String(1024))
    goal: Mapped[str] = mapped_column(Text, default="")
    # Internal understanding of the project — synthesized from the Quincy intake
    # conversation at "Build the backlog" time (no longer a user-drafted document).
    brief: Mapped[str] = mapped_column(Text, default="")
    # Cached repository overview (file listing) so Quincy has codebase context during the
    # conversation and decomposition without re-walking on every turn.
    repo_overview: Mapped[str] = mapped_column(Text, default="")
    # The freshness key for `repo_overview` (0030): `<rules version>:<clone HEAD sha>`. Without
    # it the overview was written once at intake and never again, so a project whose repo was
    # empty at creation kept an empty view of itself forever while its clone advanced with every
    # delivery. The version prefix is the second half of that lesson — keyed on HEAD alone, a
    # change to WHAT the listing contains reached no existing project until its clone happened to
    # move. Empty, or any key shape we no longer recognise, means rebuild.
    repo_overview_key: Mapped[str] = mapped_column(String(64), default="")
    # draft | drafting | ready | active | in_review | merged
    # (ready = intake conversation open, awaiting "Build the backlog")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    branch: Mapped[str] = mapped_column(String(256), default="")
    mr_url: Mapped[str] = mapped_column(String(1024), default="")
    # The branch the project MR ACTUALLY sources from (0029) — recorded, never inferred from
    # `branch` (the intake clone branch) or from the clone's checkout. See the migration.
    mr_source: Mapped[str] = mapped_column(String(256), default="")
    # Auto-approve gates + auto-run the backlog to completion (set-and-forget).
    autonomous: Mapped[bool] = mapped_column(Boolean, default=False)
    # The onboarding decisions (#121, 0033). `default_run_mode` seeds the launch control (one of
    # RUN_MODES; still overridable per run) — NOT the charter's ADR-0046 posture, which is a
    # governance declaration and lives in `project_charters`. `test_cmd` is the operator's own
    # validation command: one of the four independence legs `evaluate_oracle` accepts, and the only
    # one that was unreachable from the product. `setup_completed_at` NULL = never answered.
    default_run_mode: Mapped[str] = mapped_column(String(16), default=DEFAULT_RUN_MODE)
    test_cmd: Mapped[str] = mapped_column(String(512), default="")
    setup_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Per-project MONTHLY spend ceilings (None = no cap). Enforced between items of an autonomous
    # sweep: cumulative recorded spend this calendar month vs the cap; ≥100% pauses chaining. usd
    # bites only on paid models; tokens bite on any provider.
    budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Write-only project tokens (zero-trust, encrypted, masked hint only): gitlab_token =
    # `write_repository` transport; gitlab_api_token = OPTIONAL `api`, operator REST (ADR-0103).
    gitlab_token: Mapped[str] = mapped_column(String(512), default="")
    gitlab_api_token: Mapped[str] = mapped_column(String(512), default="")
    # GitHub App installation that can reach this project's repo (ADR-0114). NOT a secret and
    # NOT encrypted, unlike both columns above: an installation id is an identifier, and the
    # actual credential is a 1-hour token minted per delivery and never stored. Treated as a
    # CACHE of a fact GitHub owns — re-resolved on failure, never trusted as proof of access.
    github_installation_id: Mapped[str] = mapped_column(String(32), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    runs: Mapped[list[Run]] = relationship(back_populates="project")
    backlog: Mapped[list[BacklogItem]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    messages: Mapped[list[ProjectMessage]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


# Chat-turn roles. `user` and `pm` are the two parties; `note` is neither — it is the engine
# saying a turn did not complete (see `ProjectMessage.role`). Kept here rather than inline so the
# distinction has one home: WHO_SPOKE roles go to the model, `note` never does.
SPEAKER_ROLES: frozenset[str] = frozenset({"user", "pm"})
NOTE_ROLE = "note"


def conversation_turns(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The turns somebody actually said — what may be replayed to a model.

    Every model-facing reader of ``list_messages`` goes through this. The operator-facing readers
    (the transcript endpoint) deliberately do NOT: a failed turn should stay visible in the thread
    long after it happened, and invisible to the model forever.

    Deny-by-default on the role: an unrecognised role is dropped rather than passed through, so a
    future row type is silent to the model until someone decides otherwise. The opposite default
    would replay it as a human turn, which is how a note about a failure becomes something the
    operator appears to have said.
    """
    return [m for m in messages if str(m.get("role", "")) in SPEAKER_ROLES]


class ProjectMessage(Base):
    __tablename__ = "project_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # The chat session (thread) this turn belongs to (issue #30). Nullable only so the 0013
    # migration can backfill legacy rows into a default session per project; the store always
    # sets it going forward. CASCADE: deleting a session deletes its turns (the API only
    # ARCHIVES, so this bites just on project deletion, which already cascades).
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("pm_sessions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # user | pm | note. `note` is an ENGINE fact, not an utterance: it records that a turn did
    # not complete and why. It is shown to the operator and must never be replayed to the model —
    # neither party said it, and feeding it back would teach the conversation its own failures as
    # if they were speech. `conversation_turns()` is the one filter; see MESSAGE_ROLES below.
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    project: Mapped[Project] = relationship(back_populates="messages")


class ProjectContextItem(Base):
    """Long-lived PM context registry: what the PM sees every turn (summary-
    first). 4B sources only attachments; brief/manual notes may join later.
    Kept in sync with scope changes and deletes — stale context is the #1 risk
    (guardrail 8): disabled_at set ⇒ the prompt builder ignores it."""

    __tablename__ = "project_context_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(32), default="attachment")
    source_id: Mapped[str] = mapped_column(String(64))  # attachment id for 4B
    title: Mapped[str] = mapped_column(String(256))
    summary: Mapped[str] = mapped_column(Text, default="")
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MessageContextSource(Base):
    """What context a PM reply actually used (MR 4D) — one row per source per
    pm message, recorded from the prompt builder's inclusion metadata. Powers
    the "Used context" chips; honest by construction (never inferred later)."""

    __tablename__ = "message_context_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("project_messages.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(32))  # brief | backlog | runs | attachment
    source_id: Mapped[str] = mapped_column(String(64), default="")  # attachment id when relevant
    title: Mapped[str] = mapped_column(String(256), default="")  # display name (filename)
    # included_raw | truncated | chunks | summary | reference_only
    included_as: Mapped[str] = mapped_column(String(32), default="included_raw")
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# Backlog dependency edges: a self-referential many-to-many so an item can declare it
# depends on other items (both directions CASCADE so an item's deletion cleans its edges).
backlog_item_dependencies = Table(
    "backlog_item_dependencies",
    Base.metadata,
    Column("item_id", ForeignKey("backlog_items.id", ondelete="CASCADE"), primary_key=True),
    Column("depends_on_id", ForeignKey("backlog_items.id", ondelete="CASCADE"), primary_key=True),
)


class BacklogItem(Base):
    __tablename__ = "backlog_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str] = mapped_column(Text, default="")
    acceptance: Mapped[str] = mapped_column(Text, default="")
    # The item's architecture/design (approach, interfaces, files, risks) — produced by the PM
    # design stage and reused across runs of this item (#3) when `design_key` still matches.
    design: Mapped[str] = mapped_column(Text, default="")
    # Design cache key; NULL = stale (see migration 0023).
    design_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # todo | in_progress | in_review | done
    status: Mapped[str] = mapped_column(String(32), default="todo")
    position: Mapped[int] = mapped_column(Integer, default=0)
    iteration: Mapped[str | None] = mapped_column(String(64), nullable=True)  # future sprints
    # Soft-lock: the PM's advisory, user-overridable hold on running this item. Distinct from
    # the DERIVED blocked_by — a human can unlock to run early, and lock_reason carries the
    # caveat. Enforced at the launch gate + the autonomous picker.
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    lock_reason: Mapped[str] = mapped_column(Text, default="")
    # Per-item stacked MR (ADR-0021/0102): the item's branch, MR URL, and last-polled MR
    # state (""|opened|merged|closed) — kept OFF `status` (the sweep consumes that enum).
    branch: Mapped[str] = mapped_column(String(256), default="")
    mr_url: Mapped[str] = mapped_column(String(1024), default="")
    mr_state: Mapped[str] = mapped_column(String(16), default="")
    # The branch the MR ACTUALLY targets (0028) — recorded, never recomputed (see the migration).
    mr_target: Mapped[str] = mapped_column(String(256), default="")
    # Intake clarification (ADR-0080 §1): the OPEN request Quincy raised — {claim_text,
    # why_unbindable, proposals, status, asked_at}. One per item; validated at the store write
    # boundary. An OPEN material clarification makes the item not-runnable.
    clarification: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    project: Mapped[Project] = relationship(back_populates="backlog")
    # Items this one depends on — it can't start until each is delivered (in_review/done).
    # selectin so list/detail reads batch-load the edges instead of N+1 per item. Both
    # directions are declared explicitly (back_populates, not backref) so `dependents`
    # is a typed attribute — needed by the split/merge rewiring which reads it.
    depends_on: Mapped[list[BacklogItem]] = relationship(
        "BacklogItem",
        secondary=backlog_item_dependencies,
        primaryjoin=lambda: BacklogItem.id == backlog_item_dependencies.c.item_id,
        secondaryjoin=lambda: BacklogItem.id == backlog_item_dependencies.c.depends_on_id,
        back_populates="dependents",
        lazy="selectin",
    )
    # Items that depend on THIS one (the reverse edge) — rewired on split/merge/delete.
    dependents: Mapped[list[BacklogItem]] = relationship(
        "BacklogItem",
        secondary=backlog_item_dependencies,
        primaryjoin=lambda: BacklogItem.id == backlog_item_dependencies.c.depends_on_id,
        secondaryjoin=lambda: BacklogItem.id == backlog_item_dependencies.c.item_id,
        back_populates="depends_on",
        lazy="selectin",
    )


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # run_id
    source: Mapped[str] = mapped_column(String(1024))
    branch: Mapped[str] = mapped_column(String(256))
    task: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))  # APPROVED / NOT APPROVED
    tests_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    # Honest tri-state: pass | failed | unavailable; NULL = pre-planner row.
    # tests_passed stays for back-compat (unavailable coerces False there).
    validation_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Why a run ended without delivering (iteration cap / no progress / no capable
    # tool / reviewer unsatisfied). NULL for a clean delivery or a human decision.
    termination_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # How the run ended, STRUCTURED (#75, migration 0022): the same outcome bucket + park cause the
    # benchmark computes (`mosaera_core.run_diagnosis`), plus the gate reasons, vouch and stop
    # channels behind them. `termination_reason` above is the 80-char label; this is the evidence.
    # NULL = a pre-0022 row, a run still in flight, or one whose terminal path never reached it.
    diagnosis: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    iterations: Mapped[int] = mapped_column(Integer, default=0)
    commit_sha: Mapped[str] = mapped_column(String(64), default="")
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    item_id: Mapped[int | None] = mapped_column(
        ForeignKey("backlog_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # The run seal (#63, migration 0020). NULL is honest: pre-0020 row / never finalized /
    # no receipt. engine_version is stamped at finalize with the version that PRODUCED the
    # run — never back-filled from the live engine. receipt_id = deterministic sha256 over
    # (run_id, commit_sha, engine_version, receipt JSON), minted only with a receipt row.
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    engine_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    receipt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    project: Mapped[Project | None] = relationship(back_populates="runs")

    decisions: Mapped[list[Decision]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list[Artifact]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    repo_changes: Mapped[list[RepoChange]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    test_results: Mapped[list[TestResult]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    approvals: Mapped[list[Approval]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    audit_events: Mapped[list[AuditEvent]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    events: Mapped[list[RunEvent]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # plan / review / gate
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    run: Mapped[Run] = relationship(back_populates="decisions")


class RepoChange(Base):
    __tablename__ = "repo_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    diff: Mapped[str] = mapped_column(Text)
    commit_sha: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    run: Mapped[Run] = relationship(back_populates="repo_changes")


class TestResult(Base):
    __tablename__ = "test_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    output: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    run: Mapped[Run] = relationship(back_populates="test_results")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # report / plan / diff
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    run: Mapped[Run] = relationship(back_populates="artifacts")


class DoctrineChunk(Base):
    """A unit of planning doctrine the PM follows — GLOBAL (scope='global',
    project_id NULL) methodology/best-practice material, or PER-PROJECT
    (scope='project') reference docs (academic/research/house standards). The
    ``embedding`` column is the seam for later semantic retrieval
    (``similar_doctrine``); Phase 1 loads compactly by scope without it. No ANN index
    yet (consistent with ``artifacts``); add one when a large corpus lands.
    """

    __tablename__ = "doctrine_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(16))  # "global" | "project"
    # index=True matches the physical index migration 0008 already created for this column
    # (the ORM previously omitted it — a model↔migration drift this fixes).
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(256), default="")  # doc title / filename
    kind: Mapped[str] = mapped_column(String(32), default="reference")
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(32))  # write acts/deliver; "open_pr"=pre-0102
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    feedback: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    run: Mapped[Run] = relationship(back_populates="approvals")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    event: Mapped[str] = mapped_column(String(64))  # run.submitted / node / interrupt / ...
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    run: Mapped[Run] = relationship(back_populates="audit_events")


class RunEvent(Base):
    """Durable, append-only transcript of a run's fine-grained progress — the tool
    activities, agent reasoning, node completions and gate that otherwise live only
    in the in-memory SSE stream (lost on restart/eviction). Powers the transcript
    export/API for off-platform evaluation, debugging and the benchmark harness.

    ``seq`` is the run-local arrival order (mirrors the SSE seq); ``ts`` is the
    server epoch-ms stamp so replay keeps real times. ``data`` is the JSON event
    payload verbatim."""

    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(16))  # activity / thought / update / interrupt
    node: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ts: Mapped[int] = mapped_column(BigInteger)  # server epoch ms
    data: Mapped[str] = mapped_column(Text, default="")  # JSON payload
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    run: Mapped[Run] = relationship(back_populates="events")


# The attachment models, the auth-surface models (User, UserSession, SetupToken) and the PM chat
# session model live in sibling modules to keep this one under the modularity ceiling. Imported
# at the BOTTOM (after
# Base is defined) so the tables register on Base.metadata and importers keep using
# `from mosaera_memory.models import User` unchanged — Base is already defined above, and the
# ProjectMessage → pm_sessions FK resolves by table name at mapper-configure time (not import
# time), so there is no import cycle.
from mosaera_memory.models_attachments import (  # noqa: E402  (bottom re-export by design)
    Attachment as Attachment,
)
from mosaera_memory.models_attachments import (  # noqa: E402
    AttachmentDerivative as AttachmentDerivative,
)
from mosaera_memory.models_attachments import (  # noqa: E402
    MessageAttachment as MessageAttachment,
)
from mosaera_memory.models_auth import (  # noqa: E402
    SetupToken as SetupToken,
)
from mosaera_memory.models_auth import (  # noqa: E402
    User as User,
)
from mosaera_memory.models_auth import (  # noqa: E402
    UserSession as UserSession,
)
from mosaera_memory.models_chat import (  # noqa: E402
    PmSession as PmSession,
)
from mosaera_memory.models_coverage import (  # noqa: E402
    CoverageLedger as CoverageLedger,
)
from mosaera_memory.models_latency import (  # noqa: E402
    LatencySample as LatencySample,
)
from mosaera_memory.models_quota import (  # noqa: E402
    RunQuotaUsage as RunQuotaUsage,
)
