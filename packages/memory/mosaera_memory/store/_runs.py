"""Run lifecycle, run sub-events, and latency/cost-read methods."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from mosaera_memory.models import (
    Approval,
    AuditEvent,
    BacklogItem,
    Decision,
    LatencySample,
    RepoChange,
    Run,
    RunEvent,
    TestResult,
    _utcnow,
)
from mosaera_memory.store._base import StoreBase, _iso, _json_or_none, _run_summary


class RunsMixin(StoreBase):
    # --- writes ---

    def record_run(
        self,
        *,
        run_id: str,
        source: str,
        branch: str,
        task: str,
        status: str,
        tests_passed: bool,
        iterations: int,
        commit_sha: str = "",
        project_id: str | None = None,
        item_id: int | None = None,
        validation_status: str | None = None,
        engine_version: str | None = None,
        receipt_id: str | None = None,
    ) -> None:
        """Insert or update the run row (idempotent on run_id)."""
        with self.session() as s, s.begin():
            run = s.get(Run, run_id)
            if run is not None and run.status == "CANCELLED":
                # A cancel is authoritative and terminal: a worker that finishes
                # delivery after the operator cancelled must not resurrect the run
                # to APPROVED/NOT APPROVED (mirrors mark_run_error's guard).
                return
            if run is None:
                run = Run(id=run_id, source=source, branch=branch, task=task, status=status)
                s.add(run)
            run.source = source
            run.branch = branch
            run.task = task
            run.status = status
            run.tests_passed = tests_passed
            run.iterations = iterations
            run.commit_sha = commit_sha
            # The seal (#63): record_run is the finalize upsert, so this IS the honest
            # end time. Interim ensure_run stubs never pass the seal kwargs.
            run.finished_at = _utcnow()
            if engine_version is not None:
                run.engine_version = engine_version
            if receipt_id is not None:
                run.receipt_id = receipt_id
            if validation_status is not None:
                run.validation_status = validation_status
            if project_id is not None:
                run.project_id = project_id
            if item_id is not None:
                run.item_id = item_id

    def delete_run(self, run_id: str) -> None:
        """Delete a run and its children (decisions/diffs/tests/approvals/audit)."""
        with self.session() as s, s.begin():
            run = s.get(Run, run_id)
            if run is not None:
                s.delete(run)

    def cancel_run(self, run_id: str) -> None:
        """Mark a run CANCELLED and free its backlog item (recovers a stuck run)."""
        with self.session() as s, s.begin():
            run = s.get(Run, run_id)
            if run is None:
                return
            run.status = "CANCELLED"
            if run.finished_at is None:
                run.finished_at = _utcnow()
            if run.item_id is not None:
                item = s.get(BacklogItem, run.item_id)
                if item is not None and item.status == "in_progress":
                    item.status = "todo"

    def mark_run_error(self, run_id: str) -> None:
        """Durably finalize a crashed/timed-out run as ERROR and free its item.

        Only a RUNNING row transitions — a settled status (APPROVED /
        NOT APPROVED / CANCELLED) is never overwritten, so a late worker crash
        can't stomp an endpoint-written CANCELLED. Idempotent.
        """
        with self.session() as s, s.begin():
            run = s.get(Run, run_id)
            if run is None or run.status != "RUNNING":
                return
            run.status = "ERROR"
            if run.finished_at is None:
                run.finished_at = _utcnow()
            if run.item_id is not None:
                item = s.get(BacklogItem, run.item_id)
                if item is not None and item.status == "in_progress":
                    item.status = "todo"

    def mark_run_awaiting(self, run_id: str) -> None:
        """RUNNING → AWAITING_APPROVAL when a run parks at a human gate. This is
        the durable marker that survives a restart: finalize_orphans only sweeps
        RUNNING rows, so a parked run is no longer mistaken for an orphan and
        cancelled. Only a RUNNING row transitions (idempotent)."""
        with self.session() as s, s.begin():
            run = s.get(Run, run_id)
            if run is not None and run.status == "RUNNING":
                run.status = "AWAITING_APPROVAL"

    def mark_run_running(self, run_id: str) -> None:
        """AWAITING_APPROVAL → RUNNING when a parked run resumes, so a crash
        during delivery is again catchable by mark_run_error/finalize_orphans."""
        with self.session() as s, s.begin():
            run = s.get(Run, run_id)
            if run is not None and run.status == "AWAITING_APPROVAL":
                run.status = "RUNNING"

    def mark_run_incomplete(self, run_id: str, reason: str) -> None:
        """A run that reached the end WITHOUT delivering (iteration cap / no progress
        / no capable tool / reviewer unsatisfied) → INCOMPLETE + the honest reason,
        so history distinguishes a delivery from a give-up. A settled CANCELLED row
        is authoritative and never overwritten. Idempotent."""
        with self.session() as s, s.begin():
            run = s.get(Run, run_id)
            if run is None or run.status == "CANCELLED":
                return
            run.status = "INCOMPLETE"
            run.termination_reason = reason[:80] if reason else None
            if run.finished_at is None:
                run.finished_at = _utcnow()

    def record_run_diagnosis(self, run_id: str, diagnosis: dict[str, Any]) -> None:
        """Store HOW the run ended, structured (#75, migration 0022).

        Written for every terminal run — a delivery too, because "it concluded honestly" is a claim
        about deliveries as much as parks. Independent of the status write (`record_run` on the
        delivery path, `mark_run_incomplete` on the give-up path) so ONE call site covers both and
        the diagnosis cannot be recorded on one path and forgotten on the other.

        **A CANCELLED row is written too, and that is the whole point.** This method sets only
        ``diagnosis``; it never touches ``status``, so the "a settled CANCELLED row is
        authoritative" guard the status-writers above carry does not belong here. It was copied in
        anyway, and it silently voided the F50 fix for exactly the case F50 existed for:
        ``/runs/{id}/cancel`` marks the row CANCELLED synchronously before responding, so the
        worker's diagnosis — written later, when RunCancelled propagates — always arrived at an
        already-settled row and was dropped. Not a race: the endpoint's write is necessarily
        first. The runner's call is wrapped in a best-effort ``_safe``, so the no-op left no
        trace, and the diagnosis lived only in the in-memory session while the durable row the
        PM reads stayed null.

        Idempotent; last write wins, since a run finalizes once."""
        if not diagnosis:
            return
        with self.session() as s, s.begin():
            run = s.get(Run, run_id)
            if run is None:
                return
            run.diagnosis = dict(diagnosis)

    def stamp_run_receipt(self, run_id: str, *, engine_version: str, receipt_id: str) -> None:
        """Seal a run whose graph never resumed past the gate (the ADR-0078 capture path):
        deliver_node's record_run never runs there, so the runner stamps the seal directly.
        Never overwrites an existing seal (record_run's stamp is authoritative)."""
        with self.session() as s, s.begin():
            run = s.get(Run, run_id)
            if run is None:
                return
            if run.engine_version is None:
                run.engine_version = engine_version
            if run.receipt_id is None:
                run.receipt_id = receipt_id

    def parked_runs(self) -> list[dict[str, Any]]:
        """Runs durably parked at a human gate (AWAITING_APPROVAL) — the set a
        restart can rehydrate. Enough of each row to rebuild the run."""
        stmt = select(Run).where(Run.status == "AWAITING_APPROVAL")
        with self.session() as s:
            return [
                {
                    "run_id": r.id,
                    "source": r.source,
                    "branch": r.branch,
                    "task": r.task,
                    "project_id": r.project_id,
                    "item_id": r.item_id,
                }
                for r in s.scalars(stmt)
            ]

    def finalize_orphans(self) -> int:
        """On startup no runs are live, so any still-RUNNING row is orphaned — mark
        it CANCELLED and free its item. AWAITING_APPROVAL rows are deliberately
        NOT swept: they parked at a human gate and are rehydratable. Returns how
        many were finalized."""
        stmt = select(Run).where(Run.status == "RUNNING")
        with self.session() as s, s.begin():
            orphans = list(s.scalars(stmt))
            for run in orphans:
                run.status = "CANCELLED"
                if run.finished_at is None:
                    run.finished_at = _utcnow()
                if run.item_id is not None:
                    item = s.get(BacklogItem, run.item_id)
                    if item is not None and item.status == "in_progress":
                        item.status = "todo"
            return len(orphans)

    def record_latency_sample(
        self, project_id: str, path: str, elapsed_ms: int, run_id: str | None = None
    ) -> None:
        """Record one interactive-path timing sample (#22). Best-effort by
        contract: callers wrap this so a failed write never breaks the path."""
        with self.session() as s, s.begin():
            s.add(
                LatencySample(
                    project_id=project_id,
                    run_id=run_id,
                    path=path,
                    elapsed_ms=int(elapsed_ms),
                )
            )

    def tag_run(
        self, run_id: str, project_id: str | None = None, item_id: int | None = None
    ) -> None:
        """Attach a run to its project / backlog item (best-effort, if the row exists)."""
        with self.session() as s, s.begin():
            run = s.get(Run, run_id)
            if run is None:
                return
            if project_id is not None:
                run.project_id = project_id
            if item_id is not None:
                run.item_id = item_id

    def ensure_run(
        self,
        run_id: str,
        *,
        source: str = "",
        branch: str = "",
        task: str = "",
        status: str = "RUNNING",
    ) -> None:
        """Insert a stub run row if absent, so child rows (approvals, audit
        events) recorded mid-run don't violate the foreign key before the final
        ``record_run`` upsert at delivery."""
        with self.session() as s, s.begin():
            if s.get(Run, run_id) is None:
                s.add(Run(id=run_id, source=source, branch=branch, task=task, status=status))

    def project_receipts(self, project_id: str) -> dict[str, str]:
        """The LATEST receipt row per run of a project, as raw JSON strings.

        One query instead of a `run_detail` per run: the project-proof aggregate reads every
        delivered run's receipt, and thirteen round trips to summarize thirteen rows is a cost the
        page would pay on every load.

        Returns the receipts VERBATIM. Parsing, and any judgement about what a receipt means, is
        the caller's — this method must not become a second place where a receipt is interpreted,
        because two interpreters is how a summary starts disagreeing with its own sources.
        """
        stmt = (
            select(Decision.run_id, Decision.content)
            .join(Run, Run.id == Decision.run_id)
            .where(Run.project_id == project_id, Decision.kind == "receipt")
            .order_by(Decision.id)
        )
        with self.session() as s:
            rows = list(s.execute(stmt))
        # Ascending id ⇒ the last write for a run wins, matching `parseReceipt`'s "latest row"
        # rule on the web. Same precedence, one origin.
        return {str(run_id): str(content) for run_id, content in rows}

    def add_decision(self, run_id: str, kind: str, content: str) -> None:
        with self.session() as s, s.begin():
            s.add(Decision(run_id=run_id, kind=kind, content=content))

    def add_repo_change(self, run_id: str, diff: str, commit_sha: str = "") -> None:
        with self.session() as s, s.begin():
            s.add(RepoChange(run_id=run_id, diff=diff, commit_sha=commit_sha))

    def add_test_result(self, run_id: str, passed: bool, output: str) -> None:
        with self.session() as s, s.begin():
            s.add(TestResult(run_id=run_id, passed=passed, output=output))

    def add_approval(self, run_id: str, action: str, approved: bool, feedback: str = "") -> None:
        with self.session() as s, s.begin():
            s.add(Approval(run_id=run_id, action=action, approved=approved, feedback=feedback))

    def add_audit_event(self, run_id: str, event: str, detail: str = "") -> None:
        with self.session() as s, s.begin():
            s.add(AuditEvent(run_id=run_id, event=event, detail=detail))

    def add_run_event(
        self, run_id: str, seq: int, type_: str, node: str | None, ts: int, data: str
    ) -> None:
        """Append one durable transcript event (best-effort; callers guard)."""
        with self.session() as s, s.begin():
            s.add(RunEvent(run_id=run_id, seq=seq, type=type_, node=node, ts=ts, data=data))

    # --- reads ---

    def get_run(self, run_id: str) -> Run | None:
        with self.session() as s:
            return s.get(Run, run_id)

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Run summaries, newest first — materialized to dicts for the API."""
        stmt = select(Run).order_by(Run.created_at.desc()).limit(limit)
        with self.session() as s:
            return [_run_summary(r) for r in s.scalars(stmt)]

    def list_run_events(self, run_id: str) -> list[dict[str, Any]]:
        """The durable transcript for a run, in true insert order. Ordered by the
        autoincrement id (not seq) so a rehydrated run — whose session restarts its
        seq counter — still reads chronologically after a restart."""
        stmt = select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.id)
        with self.session() as s:
            return [
                {
                    "seq": e.seq,
                    "type": e.type,
                    "node": e.node,
                    "ts": e.ts,
                    "data": _json_or_none(e.data),
                }
                for e in s.scalars(stmt)
            ]

    def run_detail(self, run_id: str) -> dict[str, Any] | None:
        """Full run view (summary + children) as plain dicts, or None if absent."""
        with self.session() as s:
            run = s.get(Run, run_id)
            if run is None:
                return None
            detail = _run_summary(run)
            ordered = sorted(run.decisions, key=lambda d: d.id)
            # The `cost` decision carries the run's token/$ rollup as JSON — lift
            # it into a structured `cost` field (latest wins) and keep it out of
            # the raw decisions list so the UI's generic rows stay clean.
            cost_rows = [d for d in ordered if d.kind == "cost"]
            detail["cost"] = _json_or_none(cost_rows[-1].content) if cost_rows else None
            detail["decisions"] = [
                {"kind": d.kind, "content": d.content, "created_at": _iso(d.created_at)}
                for d in ordered
                if d.kind != "cost"
            ]
            detail["test_results"] = [
                {"passed": t.passed, "output": t.output, "created_at": _iso(t.created_at)}
                for t in sorted(run.test_results, key=lambda t: t.id)
            ]
            detail["repo_changes"] = [
                {"diff": c.diff, "commit_sha": c.commit_sha, "created_at": _iso(c.created_at)}
                for c in sorted(run.repo_changes, key=lambda c: c.id)
            ]
            detail["approvals"] = [
                {
                    "action": a.action,
                    "approved": a.approved,
                    "feedback": a.feedback,
                    "created_at": _iso(a.created_at),
                }
                for a in sorted(run.approvals, key=lambda a: a.id)
            ]
        # The claim ledger (ADR-0079) rides the detail view — the UI always wants the
        # per-claim verdicts with the decisions, so no separate endpoint. Own session
        # (the mixin method opens one); called outside the block above deliberately.
        detail["claims"] = self.list_run_claims(run_id)  # type: ignore[attr-defined]
        return detail

    def latest_cost(self, run_id: str) -> dict[str, Any] | None:
        """The newest persisted cost rollup for a run (else None). Used to seed a
        rehydrated run's CostMeter so live spend survives an API restart instead of
        resetting to zero (which would make a hard budget cap re-askable)."""
        with self.session() as s:
            row = (
                s.execute(
                    select(Decision)
                    .where(Decision.run_id == run_id, Decision.kind == "cost")
                    .order_by(Decision.id.desc())
                )
                .scalars()
                .first()
            )
            return _json_or_none(row.content) if row is not None else None
