"""Project lifecycle, project-scoped read aggregates, and backlog clearing."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mosaera_memory.models import (
    RUN_MODES,
    AuditEvent,
    BacklogItem,
    Decision,
    LatencySample,
    Project,
    RepoChange,
    Run,
)
from mosaera_memory.secrets import decrypt_secret, encrypt_secret
from mosaera_memory.store._base import (
    StoreBase,
    _backlog_summary,
    _changed_paths,
    _iso,
    _json_or_none,
    _project_summary,
    _run_summary,
)


def _latest_decision_by_run(s: Session, run_ids: list[str], kind: str) -> dict[str, str]:
    """The content of the latest ``kind`` decision for each run in ``run_ids`` — ONE query
    instead of one-per-run (the batched-IN pattern used by ``_content.list_messages``). Rows
    arrive ordered by ``(run_id, id DESC)``, so the first row seen for a run_id is its latest;
    runs with no such decision are simply absent from the map."""
    if not run_ids:
        return {}
    rows = s.execute(
        select(Decision.run_id, Decision.content)
        .where(Decision.run_id.in_(run_ids), Decision.kind == kind)
        .order_by(Decision.run_id, Decision.id.desc())
    )
    latest: dict[str, str] = {}
    for run_id, content in rows:
        latest.setdefault(run_id, content)  # first per run_id (id DESC) is the newest
    return latest


def _latest_diff_by_run(s: Session, run_ids: list[str]) -> dict[str, str]:
    """The latest ``RepoChange.diff`` for each run in ``run_ids`` — batched like
    ``_latest_decision_by_run`` (one query, newest-per-run picked in Python)."""
    if not run_ids:
        return {}
    rows = s.execute(
        select(RepoChange.run_id, RepoChange.diff)
        .where(RepoChange.run_id.in_(run_ids))
        .order_by(RepoChange.run_id, RepoChange.id.desc())
    )
    latest: dict[str, str] = {}
    for run_id, diff in rows:
        latest.setdefault(run_id, diff)
    return latest


class ProjectsMixin(StoreBase):
    def create_project(
        self,
        project_id: str,
        name: str,
        source_repo: str,
        goal: str = "",
        gitlab_token: str = "",
        autonomous: bool = False,
    ) -> None:
        with self.session() as s, s.begin():
            s.add(
                Project(
                    id=project_id,
                    name=name,
                    source_repo=source_repo,
                    goal=goal,
                    status="draft",
                    gitlab_token=encrypt_secret(gitlab_token),  # encrypted at rest (ADR-0039)
                    autonomous=autonomous,
                )
            )

    def get_project_token(self, project_id: str) -> str | None:
        """The project's scoped token — server-only (clone/push/MR). Never sent to clients.
        Decrypts the at-rest value (ADR-0039); a legacy plaintext token is returned unchanged."""
        with self.session() as s:
            project = s.get(Project, project_id)
            token = decrypt_secret(project.gitlab_token) if project is not None else ""
            return token or None

    def get_project_api_token(self, project_id: str) -> str | None:
        """The project's OPTIONAL `api`-scoped token (ADR-0103) — server-only, operator REST
        metadata calls ONLY, never git transport, never the sweep. Decrypts at rest (ADR-0039)."""
        with self.session() as s:
            project = s.get(Project, project_id)
            token = decrypt_secret(project.gitlab_api_token) if project is not None else ""
            return token or None

    def get_repo_overview(self, project_id: str) -> str:
        """The cached repository overview (server-only; not in the API detail payload,
        which the UI polls — it's large)."""
        with self.session() as s:
            project = s.get(Project, project_id)
            return project.repo_overview if project is not None else ""

    def get_repo_overview_key(self, project_id: str) -> str:
        """The clone HEAD ``repo_overview`` was built from (0030), or "" if never keyed.

        Read separately from the text so the freshness check costs one small column rather
        than dragging the whole overview back on every PM turn just to compare a sha.
        """
        with self.session() as s:
            project = s.get(Project, project_id)
            return project.repo_overview_key if project is not None else ""

    def set_repo_overview(self, project_id: str, overview: str, key: str) -> None:
        """Write the overview and the HEAD it was built from TOGETHER.

        One method, both columns, on purpose: a text written without its key would look
        permanently fresh, and a key written without its text would hide a real change. The
        design-cache precedent (`BacklogItem.design` + `design_key`) is the same rule.
        """
        with self.session() as s, s.begin():
            project = s.get(Project, project_id)
            if project is None:
                return
            project.repo_overview = overview
            project.repo_overview_key = key

    def delete_project(self, project_id: str) -> None:
        """Delete a project (cascades its backlog; runs are unlinked via SET NULL)."""
        with self.session() as s, s.begin():
            project = s.get(Project, project_id)
            if project is not None:
                s.delete(project)

    def finalize_orphan_projects(self) -> int:
        """On startup no intake/decompose threads survive, so a project stuck
        mid-intake (``drafting``) or mid-decompose (``active`` with an empty
        backlog) is orphaned and would spin forever in the UI. Reset it:
        ``drafting`` → ``draft`` (recreate to retry the clone), and an
        ``active`` project with no backlog → ``ready`` (re-click Build the
        backlog). Returns how many were reset."""
        reset = 0
        with self.session() as s, s.begin():
            for project in s.scalars(select(Project).where(Project.status == "drafting")):
                project.status = "draft"
                project.error = (
                    "intake was interrupted by a restart — recreate the project to retry"
                )
                reset += 1
            for project in s.scalars(select(Project).where(Project.status == "active")):
                if not project.backlog:  # decompose never finished
                    project.status = "ready"
                    project.error = (
                        "backlog build was interrupted by a restart — "
                        "open the project and click Build the backlog again"
                    )
                    reset += 1
        return reset

    def clear_todo_backlog(self, project_id: str) -> int:
        """Remove not-yet-started (todo) backlog items — used before regenerating. Returns the
        number kept back.

        `todo` does NOT imply "no merge request". A run that is cancelled, times out, or crashes
        resets its item to `todo` (`runner/_loop.py`) while `branch`/`mr_url` persist in their own
        columns — so an item with a LIVE merge request can be sitting in `todo`, and deleting its
        row here orphans that MR and destroys the record branch protection reads. This was the
        fourth row-deleting door, after delete/split/merge (red-team 2026-08-18 round 2).
        """
        stmt = select(BacklogItem).where(
            BacklogItem.project_id == project_id, BacklogItem.status == "todo"
        )
        kept = 0
        with self.session() as s, s.begin():
            for item in s.scalars(stmt):
                if item.mr_url and item.mr_state not in ("merged", ""):
                    kept += 1  # skip, never delete: a regenerate must not orphan a live MR
                    continue
                s.delete(item)
        return kept

    def update_project(
        self,
        project_id: str,
        *,
        brief: str | None = None,
        repo_overview: str | None = None,
        status: str | None = None,
        branch: str | None = None,
        mr_url: str | None = None,
        mr_source: str | None = None,
        source_repo: str | None = None,
        gitlab_token: str | None = None,
        gitlab_api_token: str | None = None,
        github_installation_id: str | None = None,
        autonomous: bool | None = None,
        default_run_mode: str | None = None,
        test_cmd: str | None = None,
        setup_completed: bool | None = None,
        error: str | None = None,
    ) -> None:
        """Patch the given fields on a project (idempotent, only non-None fields).

        ``default_run_mode`` must be one of ``RUN_MODES`` or this raises ``ValueError`` —
        deny-by-default at the persistence boundary, the same treatment ``upsert_charter`` gives
        posture (ADR-0005 applied where a typo would otherwise become stored config).
        ``setup_completed=True`` stamps the onboarding card as answered; ``False`` clears it."""
        if default_run_mode is not None and default_run_mode not in RUN_MODES:
            raise ValueError(
                f"unknown run mode {default_run_mode!r}; expected one of {sorted(RUN_MODES)}"
            )
        with self.session() as s, s.begin():
            project = s.get(Project, project_id)
            if project is None:
                return
            if brief is not None:
                project.brief = brief
            if repo_overview is not None:
                project.repo_overview = repo_overview
            if status is not None:
                project.status = status
            if branch is not None:
                project.branch = branch
            if mr_url is not None:
                project.mr_url = mr_url
            if mr_source is not None:
                project.mr_source = mr_source  # 0029: recorded, never recomputed
            if source_repo is not None:
                # ADR-0120: a cached installation id belongs to the OLD source — clear it.
                project.source_repo = source_repo
                project.github_installation_id = ""
            if gitlab_token is not None:
                project.gitlab_token = encrypt_secret(gitlab_token)  # encrypted at rest
            if gitlab_api_token is not None:
                project.gitlab_api_token = encrypt_secret(gitlab_api_token)  # ADR-0103
            if github_installation_id is not None:
                # NOT encrypted (ADR-0114): an installation id is an identifier, not a
                # credential — the token it mints is short-lived and never stored.
                project.github_installation_id = github_installation_id
            if autonomous is not None:
                project.autonomous = autonomous
            if default_run_mode is not None:
                project.default_run_mode = default_run_mode
            if test_cmd is not None:
                project.test_cmd = test_cmd[:512]
            if setup_completed is not None:
                project.setup_completed_at = datetime.now(UTC) if setup_completed else None
            if error is not None:
                project.error = error

    def set_project_budget(
        self, project_id: str, *, budget_usd: float | None, budget_tokens: int | None
    ) -> dict[str, Any] | None:
        """Set (or clear, via None) the project's monthly spend ceilings. Unlike
        ``update_project`` this always writes both — None means NULL/no cap, not
        'leave unchanged' — so a cap can be removed. Returns the updated summary."""
        with self.session() as s, s.begin():
            project = s.get(Project, project_id)
            if project is None:
                return None
            project.budget_usd = budget_usd
            project.budget_tokens = budget_tokens
            return _project_summary(project)

    def list_projects(self, limit: int = 100) -> list[dict[str, Any]]:
        stmt = select(Project).order_by(Project.created_at.desc()).limit(limit)
        with self.session() as s:
            return [_project_summary(p) for p in s.scalars(stmt)]

    def project_detail(self, project_id: str) -> dict[str, Any] | None:
        """Project summary plus its backlog and runs, or None if absent."""
        with self.session() as s:
            project = s.get(Project, project_id)
            if project is None:
                return None
            detail = _project_summary(project)
            detail["backlog"] = [
                _backlog_summary(i)
                for i in sorted(project.backlog, key=lambda i: (i.position, i.id))
            ]
            detail["runs"] = [
                _run_summary(r)
                for r in sorted(project.runs, key=lambda r: r.created_at, reverse=True)
            ]
            return detail

    def project_history(self, project_id: str, limit: int = 8) -> list[dict[str, Any]]:
        """A digest of a project's DELIVERED work, for the shared run-time context
        (#26): read back so a later item run knows what earlier items already built,
        instead of starting cold. Newest first, deduped to the latest APPROVED run
        per backlog item (a re-run supersedes its predecessor). Deterministic —
        pure read-back of what runs already persisted, no model calls.

        Each entry: ``{item_id, title, summary, files}`` — the coder's own SUMMARY
        (what it did) and the files that run touched (parsed from its stored diff)."""
        stmt = (
            select(Run.id, Run.item_id, Run.task, BacklogItem.title)
            .join(BacklogItem, Run.item_id == BacklogItem.id, isouter=True)
            .where(Run.project_id == project_id, Run.status == "APPROVED")
            .order_by(Run.created_at.desc(), Run.id.desc())
        )
        seen_items: set[int] = set()
        with self.session() as s:
            # Dedup to the latest APPROVED run per item and bound to `limit` FIRST, then batch-
            # fetch summaries + diffs for only the chosen runs — 2 queries total instead of 2
            # per run (and diffs, which can be large, are loaded only for rows we emit).
            chosen: list[tuple[str, int | None, str, str | None]] = []
            for run_id, item_id, task, title in s.execute(stmt).all():
                if item_id is not None:
                    if item_id in seen_items:
                        continue  # keep only the latest delivered run per item
                    seen_items.add(item_id)
                chosen.append((run_id, item_id, task, title))
                if len(chosen) >= limit:
                    break
            run_ids = [row[0] for row in chosen]
            summary_by_run = _latest_decision_by_run(s, run_ids, "summary")
            diff_by_run = _latest_diff_by_run(s, run_ids)
        return [
            {
                "item_id": item_id,
                "title": (title or task or "").strip(),
                "summary": (summary_by_run.get(run_id) or "").strip(),
                "files": _changed_paths(diff_by_run.get(run_id) or ""),
            }
            for run_id, item_id, task, title in chosen
        ]

    def project_cost(self, project_id: str, since: datetime | None = None) -> dict[str, Any]:
        """Aggregate durable per-run cost across a project's runs.

        Sums the latest ``cost`` decision of every run tagged to the project
        (runs predating cost accounting simply contribute nothing). Returns the
        same shape as a single run's rollup plus how many runs were metered.
        ``since`` restricts to runs created at/after that instant (the monthly
        budget window); None = lifetime."""
        totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0}
        total_usd = 0.0
        by_model: dict[str, dict[str, Any]] = {}
        by_agent: dict[str, dict[str, Any]] = {}
        metered = 0

        def merge(bucket: dict[str, dict[str, Any]], key_field: str, rows: Any) -> None:
            for r in rows if isinstance(rows, list) else []:
                key = str(r.get(key_field, ""))
                agg = bucket.setdefault(
                    key,
                    {
                        key_field: key,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "total_tokens": 0,
                        "calls": 0,
                        "usd": 0.0,
                    },
                )
                for k in ("input_tokens", "output_tokens", "total_tokens", "calls"):
                    agg[k] += int(r.get(k) or 0)
                agg["usd"] += float(r.get("usd") or 0.0)

        with self.session() as s:
            stmt = select(Run.id).where(Run.project_id == project_id)
            if since is not None:
                stmt = stmt.where(Run.created_at >= since)
            run_ids = list(s.execute(stmt).scalars().all())
            cost_by_run = _latest_decision_by_run(s, run_ids, "cost")
        for content in cost_by_run.values():
            data = _json_or_none(content)
            if not data:
                continue
            metered += 1
            for k in totals:
                totals[k] += int(data.get(k) or 0)
            total_usd += float(data.get("usd") or 0.0)
            merge(by_model, "model", data.get("by_model"))
            merge(by_agent, "agent", data.get("by_agent"))

        def finalize(bucket: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
            rows = sorted(bucket.values(), key=lambda x: x["total_tokens"], reverse=True)
            for r in rows:
                r["usd"] = round(r["usd"], 6)
            return rows

        return {
            **totals,
            "usd": round(total_usd, 6),
            "runs_metered": metered,
            "runs_total": len(run_ids),
            "by_agent": finalize(by_agent),
            "by_model": finalize(by_model),
        }

    def project_metrics(self, project_id: str, since: datetime | None = None) -> dict[str, Any]:
        """Deterministic-first discipline metrics (#22) across a project's runs.

        Reads each run's latest ``cost`` decision — which now also carries
        ``det_ops`` (the deterministic tool-op count) — alongside its status:
        - ``calls_per_delivered_item``: model calls per APPROVED (delivered) run;
        - ``det_llm_ratio``: deterministic tool ops per model call (higher = more
          deterministic-first).
        Each is ``None`` when its denominator is 0 (honest empty state)."""
        total_calls = 0
        total_det_ops = 0
        delivered_calls = 0
        delivered_items = 0
        metered = 0
        by_agent: dict[str, dict[str, Any]] = {}

        with self.session() as s:
            # Interactive-path latency (#22, metric 3): p50/p95 over recorded
            # samples (currently the synchronous PM chat turn). Nearest-rank in
            # pure Python, matching this method's deterministic aggregation.
            lat_stmt = select(LatencySample.elapsed_ms).where(
                LatencySample.project_id == project_id
            )
            if since is not None:
                lat_stmt = lat_stmt.where(LatencySample.created_at >= since)
            samples = sorted(int(v) for (v,) in s.execute(lat_stmt).all())

            stmt = select(Run.id, Run.status).where(Run.project_id == project_id)
            if since is not None:
                stmt = stmt.where(Run.created_at >= since)
            run_rows = s.execute(stmt).all()
            cost_by_run = _latest_decision_by_run(s, [rid for rid, _status in run_rows], "cost")
        for rid, status in run_rows:
            content = cost_by_run.get(rid)
            data = _json_or_none(content) if content is not None else None
            if not data:
                continue
            metered += 1
            calls = int(data.get("calls") or 0)
            total_calls += calls
            total_det_ops += int(data.get("det_ops") or 0)
            for r in data.get("by_agent") or []:
                agent = str(r.get("agent", ""))
                agg = by_agent.setdefault(agent, {"agent": agent, "calls": 0})
                agg["calls"] += int(r.get("calls") or 0)
            if str(status) == "APPROVED":
                delivered_items += 1
                delivered_calls += calls

        def percentile(values: list[int], pct: float) -> int | None:
            # Nearest-rank: smallest sample >= pct of the ordered set. None when
            # there are no samples (honest empty state).
            if not values:
                return None
            rank = max(1, math.ceil(pct / 100 * len(values)))
            return values[rank - 1]

        return {
            "runs_metered": metered,
            "delivered_items": delivered_items,
            "total_calls": total_calls,
            "total_det_ops": total_det_ops,
            "delivered_calls": delivered_calls,
            "calls_per_delivered_item": (
                round(delivered_calls / delivered_items, 2) if delivered_items else None
            ),
            "det_llm_ratio": (round(total_det_ops / total_calls, 2) if total_calls else None),
            "latency_samples": len(samples),
            "latency_p50_ms": percentile(samples, 50),
            "latency_p95_ms": percentile(samples, 95),
            "by_agent": sorted(by_agent.values(), key=lambda x: x["calls"], reverse=True),
        }

    def project_activity(self, project_id: str, limit: int = 200) -> list[dict[str, Any]]:
        """The persisted audit trail for a project's runs, newest first.

        Audit rows carry only ``run_id``, so project scope comes from the runs
        join. The joined ``task`` gives each event a human anchor without a
        second query.
        """
        stmt = (
            select(AuditEvent, Run.task)
            .join(Run, AuditEvent.run_id == Run.id)
            .where(Run.project_id == project_id)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(limit)
        )
        with self.session() as s:
            return [
                {
                    "run_id": ev.run_id,
                    "event": ev.event,
                    "detail": ev.detail,
                    "created_at": _iso(ev.created_at),
                    "task": task,
                }
                for ev, task in s.execute(stmt).all()
            ]
