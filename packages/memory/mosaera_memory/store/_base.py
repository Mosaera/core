"""Shared infrastructure + module-level helpers for the store package.

``StoreBase`` holds the engine/session plumbing and the Alembic-driven schema
lifecycle; the per-aggregate mixins inherit it. The module-level helpers
(summaries, JSON/ISO coercion, diff parsing) are pure and imported by whichever
mixin needs them.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from mosaera_memory.models import (
    EMBED_DIM,
    Attachment,
    BacklogItem,
    Base,
    Project,
    Run,
    User,
)
from mosaera_memory.secrets import try_decrypt

__all__ = ["EMBED_DIM", "StoreBase"]


def _to_sqlalchemy_url(url: str) -> str:
    """Normalize a psycopg URL to the SQLAlchemy psycopg3 driver form."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _alembic_config(url: str) -> Any:
    """Build an Alembic Config for our migrations, with the URL injected at
    runtime (we drive Alembic programmatically — no static alembic.ini)."""
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", _to_sqlalchemy_url(url))
    return cfg


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _json_or_none(raw: str) -> dict[str, Any] | None:
    """Parse a JSON object stored in a decision row; None on any garbage."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _run_summary(run: Run) -> dict[str, Any]:
    return {
        "id": run.id,
        "task": run.task,
        "status": run.status,
        "tests_passed": run.tests_passed,
        "iterations": run.iterations,
        "commit_sha": run.commit_sha,
        "source": run.source,
        "branch": run.branch,
        "project_id": run.project_id,
        "item_id": run.item_id,
        "validation_status": run.validation_status,
        "termination_reason": run.termination_reason,
        "created_at": _iso(run.created_at),
        # The seal (#63, migration 0020). Null = pre-0020 row / never finalized / no
        # receipt — the UI must render null honestly, never proxy the live engine version.
        "finished_at": _iso(run.finished_at) if run.finished_at else None,
        "engine_version": run.engine_version,
        "receipt_id": run.receipt_id,
        # How the run ended, structured (#75, migration 0022). Null = pre-0022 row / still in
        # flight / a terminal path that never reached it — rendered honestly, never inferred.
        "diagnosis": run.diagnosis,
    }


def _api_key_summary(k: Any) -> dict[str, Any]:
    """Safe projection of an API key -- NEVER includes `token_hash`, and there is no path back to
    the plaintext from anything stored. `revoked` is derived rather than exposing the timestamp
    alone, so a caller cannot mistake a non-null field for a live key."""
    return {
        "id": k.id,
        "name": k.name,
        "created_at": _iso(k.created_at),
        "last_used_at": _iso(k.last_used_at) if k.last_used_at else None,
        "revoked": k.revoked_at is not None,
    }


def _user_summary(u: User) -> dict[str, Any]:
    # Safe projection — NEVER includes password_hash.
    return {
        "id": u.id,
        "username": u.username,
        "is_admin": u.is_admin,
        "created_at": _iso(u.created_at),
    }


def _attachment_summary(a: Attachment) -> dict[str, Any]:
    return {
        "id": a.id,
        "project_id": a.project_id,
        "filename": a.filename,
        "mime_type": a.mime_type,
        "size_bytes": a.size_bytes,
        "sha256": a.sha256,
        "storage_path": a.storage_path,
        "status": a.status,
        "error_message": a.error_message,
        "token_estimate": a.token_estimate,
        "scope": a.scope,
        "created_at": _iso(a.created_at),
        "deleted_at": _iso(a.deleted_at) if a.deleted_at else None,
    }


# An item's dependency is satisfied once its work is DELIVERED. The runner only ever
# sets in_review on a clean delivery (never done — that's a human-set status), so
# requiring done would deadlock the autonomous sweep. done is included for human-marked
# items.
_DELIVERED = frozenset({"in_review", "done"})


def _backlog_summary(item: BacklogItem) -> dict[str, Any]:
    deps = list(item.depends_on)
    return {
        "id": item.id,
        "project_id": item.project_id,
        "title": item.title,
        "description": item.description,
        "acceptance": item.acceptance,
        "design": item.design,
        "design_key": item.design_key,
        "status": item.status,
        "position": item.position,
        "iteration": item.iteration,
        # Soft-lock: the PM's advisory, user-overridable hold + its caveat (distinct from
        # the derived blocked_by below).
        "locked": bool(item.locked),
        "lock_reason": item.lock_reason,
        # Per-item stacked-MR delivery (ADR-0021): the item's own branch + opened MR URL
        # + the MR's last-polled state (ADR-0102: "" | opened | merged | closed).
        "branch": item.branch,
        "mr_url": item.mr_url,
        "mr_state": item.mr_state,
        "mr_target": item.mr_target,
        # Intake clarification (ADR-0080): the OPEN request only (resolved ones read as None).
        "clarification": (
            dict(item.clarification)
            if isinstance(item.clarification, dict) and item.clarification.get("status") == "open"
            else None
        ),
        # The full exchange regardless of status (#63 ledger): the ask + the operator's
        # recorded resolution. None only when nothing was ever asked.
        "clarification_record": (
            dict(item.clarification) if isinstance(item.clarification, dict) else None
        ),
        "created_at": _iso(item.created_at),
        # Dependency graph: what this item depends on, and which of those aren't yet
        # delivered (derived — the item is runnable iff blocked_by is empty).
        "depends_on": sorted(d.id for d in deps),
        "blocked_by": sorted(d.id for d in deps if d.status not in _DELIVERED),
    }


def _changed_paths(diff: str, limit: int = 20) -> list[str]:
    """File paths touched by a unified diff (from its ``+++ b/<path>`` headers).
    Best-effort and bounded — feeds the compact 'what this item changed' digest."""
    paths: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            if path and path != "/dev/null" and path not in paths:
                paths.append(path)
                if len(paths) >= limit:
                    break
    return paths


def _mask(secret: str | None) -> str:
    """A safe hint for a secret — never the value itself."""
    if not secret:
        return ""
    return f"…{secret[-4:]}" if len(secret) > 4 else "…"


def _project_summary(project: Project) -> dict[str, Any]:
    # NOTE: the raw gitlab_token is write-only and MUST NOT appear here — clients
    # only ever see whether one is set and a masked hint.
    _token_ok, _token_plain = try_decrypt(project.gitlab_token)
    return {
        "id": project.id,
        "name": project.name,
        "source_repo": project.source_repo,
        "goal": project.goal,
        "brief": project.brief,
        "status": project.status,
        "branch": project.branch,
        "mr_url": project.mr_url,
        # The project MR's RECORDED source branch (0029) — branch protection reads this; it is
        # NOT `branch`, which is the intake clone branch written once at creation.
        "mr_source": project.mr_source,
        "autonomous": project.autonomous,
        "has_gitlab_token": bool(project.gitlab_token),
        # Mask the DECRYPTED plaintext (ADR-0039) — the raw column is ciphertext, whose tail is a
        # meaningless hint. But NEVER 500 a project list because one token can't be decrypted: if
        # MOSAERA_SECRET_KEY is missing/wrong the value is "locked", degraded per-project (M-2).
        "gitlab_token_masked": _mask(_token_plain) if _token_ok else "locked",
        "gitlab_token_status": (
            "absent" if not project.gitlab_token else ("present" if _token_ok else "locked")
        ),
        # The OPTIONAL api-scoped token (ADR-0103) — presence only, never the value/hint.
        "has_gitlab_api_token": bool(project.gitlab_api_token),
        # Whether a GitHub App installation has been resolved for this project (ADR-0114).
        # Presence only, like the two above — though this one is not a secret at all, the
        # credential being minted per delivery rather than stored.
        "has_github_connection": bool(project.github_installation_id),
        "error": project.error,
        "budget_usd": project.budget_usd,
        "budget_tokens": project.budget_tokens,
        # The onboarding decisions (#121). `test_cmd` is operator-authored and not a secret — it
        # is shown back so the setup card can render what is actually in force rather than a
        # blank field the operator has to re-type to see.
        "default_run_mode": project.default_run_mode,
        "test_cmd": project.test_cmd,
        "setup_completed_at": _iso(project.setup_completed_at),
        "created_at": _iso(project.created_at),
    }


class StoreBase:
    if TYPE_CHECKING:
        # Cross-mixin contracts. `MemoryStore` composes these mixins, so one may legitimately call
        # a method another defines — but nothing declared that, and mypy was right to say the
        # attribute is unproven. Declaring it here is the same shape `app_context/_base.py` uses
        # for the same reason: the composition is real, so write it down rather than silence it.
        #
        # `_steps_by_message` lives on `StepsMixin` and is called by `ContentMixin.list_messages`
        # to attach each turn's steps in one query.
        def _steps_by_message(
            self, session: Any, message_ids: list[int]
        ) -> dict[int, list[Any]]: ...

    def __init__(self, engine: Engine):
        self._engine = engine
        self._session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    @classmethod
    def from_url(cls, url: str) -> Self:
        return cls(create_engine(_to_sqlalchemy_url(url), pool_pre_ping=True))

    @classmethod
    def open_or_reason(cls, url: str) -> tuple[Self | None, str]:
        """Open + initialize a store, or return ``(None, why)``.

        The failure surface here is wide — connection refused, bad credentials, no
        privilege to ``CREATE EXTENSION vector``, a failed Alembic migration — and callers
        need to TELL the operator which. ``try_open`` used to swallow the exception whole,
        so the API degraded to amnesia with no log line and no way to explain itself
        (ADR-0035). This package has no logger by design; the caller reports.
        """
        try:
            store = cls.from_url(url)
            store.init()
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"
        return store, ""

    @classmethod
    def try_open(cls, url: str) -> Self | None:
        """Open + initialize a store, or None if it is unreachable/misconfigured.

        Prefer ``open_or_reason`` — it tells you WHY. This remains for callers that
        genuinely only need the optional store.
        """
        store, _ = cls.open_or_reason(url)
        return store

    def init(self) -> None:
        """Bring the schema to head via Alembic (idempotent).

        - fresh DB → ``alembic upgrade head`` builds everything;
        - a pre-Alembic DB (from the old create_all path) → bring it fully to the
          baseline, then ``stamp head`` so migrations don't re-create existing
          objects;
        - an already-versioned DB → ``upgrade head`` applies any new migrations.
        """
        from alembic import command
        from sqlalchemy import inspect

        with self._engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        url = self._engine.url.render_as_string(hide_password=False)
        cfg = _alembic_config(url)
        tables = set(inspect(self._engine).get_table_names())
        if "alembic_version" in tables:
            command.upgrade(cfg, "head")
        elif tables & {"runs", "projects"}:
            self._bring_pre_alembic_db_to_baseline()
            command.stamp(cfg, "head")
        else:
            command.upgrade(cfg, "head")

    def _bring_pre_alembic_db_to_baseline(self) -> None:
        """One-time transition: a DB created by the old ``create_all`` path must be
        at the full baseline schema before we stamp it as Alembic-managed. These
        idempotent statements are the old init()'s adds — harmless if already
        present, essential if the DB predates a column."""
        Base.metadata.create_all(self._engine)
        with self._engine.begin() as conn:
            conn.execute(text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS project_id VARCHAR(64)"))
            conn.execute(text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS item_id INTEGER"))
            conn.execute(
                text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS validation_status VARCHAR(16)")
            )
            conn.execute(
                text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS termination_reason VARCHAR(80)")
            )
            for col, ddl in (
                ("mr_url", "VARCHAR(1024) DEFAULT ''"),
                ("gitlab_token", "VARCHAR(512) DEFAULT ''"),
                ("autonomous", "BOOLEAN DEFAULT FALSE"),
                ("repo_overview", "TEXT DEFAULT ''"),
                ("error", "TEXT DEFAULT ''"),
                # Migration 0002 columns — MUST be here too: this path stamps the
                # DB at `head`, so it has to reach head. Omitting these left an
                # upgraded DB missing budget_* while Alembic reported head, and
                # every projects query (which selects budget_usd) then crashed.
                ("budget_usd", "DOUBLE PRECISION"),
                ("budget_tokens", "BIGINT"),
            ):
                conn.execute(text(f"ALTER TABLE projects ADD COLUMN IF NOT EXISTS {col} {ddl}"))
            # backlog_items post-0001 columns — same reasoning as projects above: a pre-Alembic
            # DB already HAS the backlog_items table (0001 baseline), so create_all never adds
            # these later columns, yet this path stamps `head`. Omitting them left an upgraded DB
            # missing design/locked/branch while Alembic reported head, and every backlog read
            # (which selects them) then crashed with UndefinedColumn.
            for col, ddl in (
                ("design", "TEXT DEFAULT ''"),  # 0004
                ("locked", "BOOLEAN DEFAULT FALSE"),  # 0009
                ("lock_reason", "TEXT DEFAULT ''"),  # 0009
                ("branch", "VARCHAR(256) DEFAULT ''"),  # 0010
                ("mr_url", "VARCHAR(1024) DEFAULT ''"),  # 0010
                ("clarification", "JSON"),  # 0019
                ("design_key", "VARCHAR(64)"),  # 0023
            ):
                conn.execute(
                    text(f"ALTER TABLE backlog_items ADD COLUMN IF NOT EXISTS {col} {ddl}")
                )

    def session(self) -> Session:
        return self._session_factory()
