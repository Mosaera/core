"""MemoryStore integration tests against Postgres + pgvector.

Skipped unless MOSAERA_TEST_DB_URL points at a reachable database (bring one up
with `make db-up`). Each test uses an isolated run id and cleans up after itself.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator

import pytest
from mosaera_memory import EMBED_DIM, MemoryStore
from mosaera_memory.models import BacklogItem, LatencySample, Project, Run
from sqlalchemy import inspect as sa_inspect

# Read at import: the repo-root autouse fixture strips MOSAERA_* per test.
_DB_URL = os.environ.get("MOSAERA_TEST_DB_URL")

# The gate lives in the repo-root conftest (#58): probed once, reason printed,
# and an ERROR rather than a skip when MOSAERA_INTEGRATION=required.
requires_db = pytest.mark.requires_db


def test_try_open_unreachable_returns_none() -> None:
    # Port 1 refuses immediately — no DB needed to exercise the degrade path.
    assert MemoryStore.try_open("postgresql://u:p@127.0.0.1:1/nope") is None


def test_open_or_reason_returns_the_cause() -> None:
    # `try_open` swallowed the exception whole, so the API degraded to amnesia with no log
    # line and no way to explain itself. The caller cannot report what it was never told
    # (ADR-0035) — this package has no logger by design, so it hands the reason back.
    store, reason = MemoryStore.open_or_reason("postgresql://u:p@127.0.0.1:1/nope")
    assert store is None
    assert reason  # non-empty: names the exception type and message
    assert "127.0.0.1" in reason or "connect" in reason.lower()


@pytest.fixture
def store() -> MemoryStore:
    s = MemoryStore.from_url(_DB_URL)  # type: ignore[arg-type]
    s.init()
    return s


@pytest.fixture
def run_id(store: MemoryStore) -> Iterator[str]:
    rid = f"test-{uuid.uuid4().hex[:10]}"
    store.record_run(
        run_id=rid,
        source="local",
        branch=f"mosaera/{rid}",
        task="fix the failing test",
        status="APPROVED",
        tests_passed=True,
        iterations=1,
        commit_sha="abc123",
    )
    yield rid
    with store.session() as sess, sess.begin():
        obj = sess.get(Run, rid)
        if obj is not None:
            sess.delete(obj)  # cascades to children


@requires_db
def test_project_summary_degrades_on_locked_token(
    store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The headline M-2 scenario: a project token encrypted under a key we've since lost must NOT
    # 500 the whole projects list — it degrades to a "locked" status/mask for that one project.
    from cryptography.fernet import Fernet

    pid = f"lock-{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())
    store.create_project(pid, "locked-proj", "https://gitlab.example/x.git", gitlab_token="glpat-x")
    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())  # lose the key
    try:
        row = next(p for p in store.list_projects() if p["id"] == pid)  # must NOT raise
        assert row["has_gitlab_token"] is True
        assert row["gitlab_token_status"] == "locked"
        assert row["gitlab_token_masked"] == "locked"
    finally:
        store.delete_project(pid)


@requires_db
def test_record_run_stamps_the_seal(store: MemoryStore, run_id: str) -> None:
    # (#63, migration 0020) record_run IS the finalize upsert — it stamps finished_at
    # always, and engine_version/receipt_id when the caller passes them.
    store.record_run(
        run_id=run_id,
        source="local",
        branch="b",
        task="t",
        status="APPROVED",
        tests_passed=True,
        iterations=1,
        commit_sha="abc",
        engine_version="0.6.0",
        receipt_id="a" * 64,
    )
    row = next(r for r in store.list_runs() if r["id"] == run_id)
    assert row["finished_at"] is not None
    assert row["engine_version"] == "0.6.0"
    assert row["receipt_id"] == "a" * 64


@requires_db
def test_seal_fields_null_when_never_passed(store: MemoryStore, run_id: str) -> None:
    # The fixture's record_run passed no seal kwargs → honest nulls, never invented.
    row = next(r for r in store.list_runs() if r["id"] == run_id)
    assert row["engine_version"] is None
    assert row["receipt_id"] is None
    assert row["finished_at"] is not None  # finalize time itself is always stamped


@requires_db
def test_terminal_transitions_stamp_finished_at(store: MemoryStore) -> None:
    rid = f"test-{uuid.uuid4().hex[:10]}"
    store.ensure_run(rid, source="local", branch="b", task="t")  # RUNNING stub — no seal
    try:
        row = next(r for r in store.list_runs() if r["id"] == rid)
        assert row["finished_at"] is None  # a live stub has no end time
        store.mark_run_incomplete(rid, "iteration cap")
        row = next(r for r in store.list_runs() if r["id"] == rid)
        assert row["finished_at"] is not None
    finally:
        store.delete_run(rid)


@requires_db
def test_stamp_run_receipt_never_overwrites(store: MemoryStore, run_id: str) -> None:
    # The ADR-0078 park-capture path seals a never-resumed run; record_run's stamp
    # (when present) is authoritative and must survive.
    store.stamp_run_receipt(run_id, engine_version="0.6.0", receipt_id="b" * 64)
    row = next(r for r in store.list_runs() if r["id"] == run_id)
    assert row["engine_version"] == "0.6.0" and row["receipt_id"] == "b" * 64
    store.stamp_run_receipt(run_id, engine_version="9.9.9", receipt_id="c" * 64)
    row = next(r for r in store.list_runs() if r["id"] == run_id)
    assert row["engine_version"] == "0.6.0" and row["receipt_id"] == "b" * 64


@requires_db
def test_record_run_is_idempotent(store: MemoryStore, run_id: str) -> None:
    store.record_run(
        run_id=run_id,
        source="local",
        branch="b",
        task="t",
        status="NOT APPROVED",
        tests_passed=False,
        iterations=3,
        commit_sha="",
    )
    run = store.get_run(run_id)
    assert run is not None
    assert run.status == "NOT APPROVED"
    assert run.iterations == 3


@requires_db
def test_project_metrics_ratio_and_calls_per_item(store: MemoryStore, run_id: str) -> None:
    pid = f"proj-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "metrics", "src")  # runs.project_id has a FK
    # Delivered (APPROVED) run: 10 LLM calls, 30 deterministic ops.
    store.record_run(
        run_id=run_id,
        source="local",
        branch="b",
        task="a",
        status="APPROVED",
        tests_passed=True,
        iterations=1,
        project_id=pid,
    )
    store.add_decision(run_id, "cost", json.dumps({"calls": 10, "det_ops": 30, "by_agent": []}))
    # Not delivered: 5 calls, 15 ops (counts toward the ratio, not the item avg).
    rb = f"test-{uuid.uuid4().hex[:10]}"
    store.record_run(
        run_id=rb,
        source="local",
        branch="b",
        task="b",
        status="NOT APPROVED",
        tests_passed=False,
        iterations=2,
        project_id=pid,
    )
    store.add_decision(rb, "cost", json.dumps({"calls": 5, "det_ops": 15, "by_agent": []}))
    try:
        m = store.project_metrics(pid)
        assert m["runs_metered"] == 2
        assert m["delivered_items"] == 1
        assert m["total_calls"] == 15 and m["total_det_ops"] == 45
        assert m["calls_per_delivered_item"] == 10.0  # 10 delivered calls / 1 delivered
        assert m["det_llm_ratio"] == 3.0  # 45 ops / 15 calls
        # No history → honest None, never a fake 0.
        empty = store.project_metrics(f"proj-empty-{uuid.uuid4().hex[:6]}")
        assert empty["calls_per_delivered_item"] is None and empty["det_llm_ratio"] is None
    finally:
        with store.session() as s, s.begin():
            o = s.get(Run, rb)
            if o is not None:
                s.delete(o)  # run_id fixture deletes its own run; project_id FK is SET NULL
            p = s.get(Project, pid)
            if p is not None:
                s.delete(p)


@requires_db
def test_project_metrics_latency_p50_p95_nearest_rank(store: MemoryStore) -> None:
    # #22 metric 3: p50/p95 interactive latency over recorded samples, computed
    # by nearest-rank in Python. A project with latency but zero runs still yields
    # percentiles (latency exists before any run) and runs_metered stays 0.
    pid = f"proj-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "latency", "src")
    try:
        for ms in (100, 200, 300, 400, 500):
            store.record_latency_sample(pid, "pm_chat", ms)
        m = store.project_metrics(pid)
        assert m["latency_samples"] == 5
        assert m["latency_p50_ms"] == 300  # ceil(0.50*5)=3 → 3rd smallest
        assert m["latency_p95_ms"] == 500  # ceil(0.95*5)=5 → 5th smallest
        assert m["runs_metered"] == 0  # latency without runs
        # No samples → honest None, never a fake 0.
        empty = store.project_metrics(f"proj-empty-{uuid.uuid4().hex[:6]}")
        assert empty["latency_samples"] == 0
        assert empty["latency_p50_ms"] is None and empty["latency_p95_ms"] is None
    finally:
        with store.session() as s, s.begin():
            o = s.get(Project, pid)
            if o is not None:
                s.delete(o)  # cascades to latency_samples


@requires_db
def test_project_history_digests_and_dedups_delivered_items(store: MemoryStore) -> None:
    # #26 shared context: read back what earlier items delivered — the coder's
    # summary + files touched — deduped to the latest APPROVED run per item, with
    # non-approved runs excluded.
    pid = f"proj-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "hist", "src")
    i1 = store.add_backlog_item(pid, "Add login")
    i2 = store.add_backlog_item(pid, "Add logout")
    rids: list[str] = []

    def deliver(item_id: int, task: str, status: str, summary: str, diff: str) -> None:
        rid = f"test-{uuid.uuid4().hex[:10]}"
        rids.append(rid)
        store.record_run(
            run_id=rid,
            source="local",
            branch="b",
            task=task,
            status=status,
            tests_passed=status == "APPROVED",
            iterations=1,
            project_id=pid,
            item_id=item_id,
        )
        if summary:
            store.add_decision(rid, "summary", summary)
        if diff:
            store.add_repo_change(rid, diff, "sha")

    try:
        deliver(i1, "Add login", "APPROVED", "SUMMARY: first attempt", "+++ b/auth/old.py\n")
        deliver(
            i1,
            "Add login",
            "APPROVED",
            "SUMMARY: added AuthService",
            "+++ b/auth/service.py\n+++ b/auth/routes.py\n",
        )
        deliver(i2, "Add logout", "NOT APPROVED", "", "")  # excluded — not delivered

        hist = store.project_history(pid)
        by_item = {h["item_id"]: h for h in hist}
        assert set(by_item) == {i1}  # dedup to latest-per-item; non-approved absent
        assert "added AuthService" in by_item[i1]["summary"]  # newest run, not "first attempt"
        assert by_item[i1]["files"] == ["auth/service.py", "auth/routes.py"]
        assert by_item[i1]["title"] == "Add login"
    finally:
        with store.session() as s, s.begin():
            for rid in rids:
                o = s.get(Run, rid)
                if o is not None:
                    s.delete(o)
            p = s.get(Project, pid)
            if p is not None:
                s.delete(p)


@requires_db
def test_project_activity_scopes_by_project_and_orders_newest_first(
    store: MemoryStore, run_id: str
) -> None:
    pid = f"proj-{uuid.uuid4().hex[:8]}"
    other_pid = f"proj-{uuid.uuid4().hex[:8]}"
    other = f"test-{uuid.uuid4().hex[:10]}"
    store.create_project(pid, "ours", "src")  # runs.project_id has a FK
    store.create_project(other_pid, "theirs", "src")
    # `run_id` (fixture) has NO project; make it belong to our project instead,
    # then add an unrelated project's run that must NOT leak into the results.
    store.record_run(
        run_id=run_id,
        source="local",
        branch="b",
        task="ours",
        status="APPROVED",
        tests_passed=True,
        iterations=1,
        project_id=pid,
    )
    store.record_run(
        run_id=other,
        source="local",
        branch="b",
        task="theirs",
        status="APPROVED",
        tests_passed=True,
        iterations=1,
        project_id=other_pid,
    )
    try:
        store.add_audit_event(run_id, "run.started")
        store.add_audit_event(run_id, "node", "test")
        store.add_audit_event(run_id, "auto-park", "validation_failed")
        store.add_audit_event(other, "run.started")  # different project — excluded

        events = store.project_activity(pid)
        assert [e["event"] for e in events] == ["auto-park", "node", "run.started"]  # newest first
        assert {e["run_id"] for e in events} == {run_id}  # scoped
        assert all(e["task"] == "ours" for e in events)  # joined task
    finally:
        with store.session() as sess, sess.begin():
            obj = sess.get(Run, other)
            if obj is not None:
                sess.delete(obj)
            for p in (sess.get(Project, pid), sess.get(Project, other_pid)):
                if p is not None:
                    sess.delete(p)


@requires_db
def test_init_migrates_to_head_with_full_schema(store: MemoryStore) -> None:
    # After init() the DB is Alembic-managed (alembic_version present) and carries
    # the full ORM schema — the drift guard: a model column with no migration
    # would surface here as a missing physical column.
    store.init()
    insp = sa_inspect(store._engine)  # type: ignore[attr-defined]
    assert "alembic_version" in set(insp.get_table_names())
    for model in (Project, Run, BacklogItem, LatencySample):
        physical = {c["name"] for c in insp.get_columns(model.__tablename__)}
        orm = {c.name for c in model.__table__.columns}
        missing = orm - physical
        assert not missing, f"{model.__tablename__} missing physical columns: {missing}"


@requires_db
def test_pre_alembic_baseline_reaches_head_for_legacy_backlog_items() -> None:
    # A DB created by the OLD create_all path has runs/projects/backlog_items but no
    # alembic_version, and its backlog_items predates the post-0001 columns. init() must ALTER
    # those columns IN before it stamps head (M2) — else Alembic reports head while every backlog
    # read 500s on the missing column. Uses a throwaway database so the shared one is untouched.
    import sqlalchemy as sa
    from mosaera_memory.models import Base

    added = ("design", "locked", "lock_reason", "branch", "mr_url")
    # Admin engine for CREATE/DROP DATABASE — use the same psycopg3 driver the store uses
    # (a bare postgresql:// URL would try the uninstalled psycopg2).
    admin_url = _DB_URL.replace("postgresql://", "postgresql+psycopg://", 1)  # type: ignore[union-attr]
    admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    dbname = f"mosaera_baseline_{uuid.uuid4().hex[:8]}"
    with admin.connect() as c:
        c.execute(sa.text(f'CREATE DATABASE "{dbname}"'))
    try:
        url = _DB_URL.rsplit("/", 1)[0] + "/" + dbname  # type: ignore[union-attr]
        store = MemoryStore.from_url(url)
        engine = store._engine  # type: ignore[attr-defined]
        with engine.begin() as conn:
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Emulate the old create_all output, then drop the later columns + any alembic_version
        # so init() takes the pre-Alembic baseline branch (runs/projects present, no version).
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            for col in added:
                conn.execute(sa.text(f"ALTER TABLE backlog_items DROP COLUMN IF EXISTS {col}"))
            conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))
        pre = {c["name"] for c in sa_inspect(engine).get_columns("backlog_items")}
        assert not (set(added) & pre)  # precondition: the columns really are gone

        store.init()  # baseline path: create_all (no-op on existing) + ALTER ADD + stamp head

        insp = sa_inspect(engine)
        cols = {c["name"] for c in insp.get_columns("backlog_items")}
        assert set(added) <= cols, f"baseline left backlog_items missing: {set(added) - cols}"
        assert "alembic_version" in set(insp.get_table_names())  # stamped as Alembic-managed
        engine.dispose()
    finally:
        with admin.connect() as c:
            c.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


@requires_db
def test_finalize_orphan_projects_resets_stranded_states(store: MemoryStore) -> None:
    stranded_intake = f"proj-{uuid.uuid4().hex[:8]}"
    stranded_build = f"proj-{uuid.uuid4().hex[:8]}"
    store.create_project(stranded_intake, "d", "src")
    store.update_project(stranded_intake, status="drafting")  # clone interrupted
    store.create_project(stranded_build, "a", "src")
    store.update_project(stranded_build, status="active")  # active but no backlog
    try:
        n = store.finalize_orphan_projects()
        assert n >= 2
        di = store.project_detail(stranded_intake)
        db = store.project_detail(stranded_build)
        assert di is not None and di["status"] == "draft" and "interrupted" in di["error"]
        assert db is not None and db["status"] == "ready" and "Build the backlog" in db["error"]
    finally:
        with store.session() as sess, sess.begin():
            for pid in (stranded_intake, stranded_build):
                obj = sess.get(Project, pid)
                if obj is not None:
                    sess.delete(obj)


@requires_db
def test_record_run_does_not_resurrect_a_cancelled_run(store: MemoryStore) -> None:
    rid = f"test-{uuid.uuid4().hex[:10]}"
    store.record_run(
        run_id=rid,
        source="local",
        branch="b",
        task="t",
        status="CANCELLED",
        tests_passed=False,
        iterations=1,
    )
    # A worker that finishes delivery after the operator cancelled must NOT flip
    # the run back to a delivered status.
    store.record_run(
        run_id=rid,
        source="local",
        branch="b",
        task="t",
        status="APPROVED",
        tests_passed=True,
        iterations=2,
    )
    run = store.get_run(rid)
    assert run is not None and run.status == "CANCELLED" and run.iterations == 1
    with store.session() as sess, sess.begin():
        obj = sess.get(Run, rid)
        if obj is not None:
            sess.delete(obj)


@requires_db
def test_children_recorded(store: MemoryStore, run_id: str) -> None:
    store.add_decision(run_id, "plan", "1. fix add()")
    store.add_decision(run_id, "review", "VERDICT: APPROVE")
    store.add_repo_change(run_id, "diff --git ...", "abc123")
    store.add_test_result(run_id, True, "1 passed")
    run = store.get_run(run_id)
    assert run is not None
    with store.session() as s:
        loaded = s.get(Run, run_id)
        assert loaded is not None
        assert {d.kind for d in loaded.decisions} == {"plan", "review"}
        assert len(loaded.repo_changes) == 1
        assert loaded.test_results[0].passed is True


@requires_db
def test_ensure_run_then_approvals_and_audit(store: MemoryStore) -> None:
    import uuid as _uuid

    rid = f"test-{_uuid.uuid4().hex[:10]}"
    # No record_run yet — ensure_run must create the parent so child rows insert.
    store.ensure_run(rid, task="do a thing")
    store.add_approval(rid, "deliver", True, "")
    store.add_audit_event(rid, "run.started")
    store.add_audit_event(rid, "node", "plan")
    with store.session() as s:
        loaded = s.get(Run, rid)
        assert loaded is not None
        assert loaded.status == "RUNNING"
        assert len(loaded.approvals) == 1
        assert loaded.approvals[0].approved is True
        assert {e.event for e in loaded.audit_events} == {"run.started", "node"}
        s.delete(loaded)
        s.commit()


@requires_db
def test_list_runs_and_run_detail(store: MemoryStore, run_id: str) -> None:
    store.add_decision(run_id, "plan", "1. fix add()")
    store.add_decision(run_id, "review", "VERDICT: APPROVE")
    store.add_repo_change(run_id, "diff --git a/calc.py b/calc.py", "abc123")
    store.add_test_result(run_id, True, "1 passed")
    store.add_approval(run_id, "deliver", True, "")

    listed = store.list_runs(limit=10)
    assert any(r["id"] == run_id and r["status"] == "APPROVED" for r in listed)
    assert all("created_at" in r for r in listed)

    detail = store.run_detail(run_id)
    assert detail is not None
    assert {d["kind"] for d in detail["decisions"]} == {"plan", "review"}
    assert detail["repo_changes"][0]["diff"].startswith("diff --git")
    assert detail["test_results"][0]["passed"] is True
    assert detail["approvals"][0]["action"] == "deliver"
    assert store.run_detail("does-not-exist") is None


@requires_db
def test_run_detail_lifts_cost_decision_into_structured_field(
    store: MemoryStore, run_id: str
) -> None:
    # No cost decision yet → cost is None, not an error.
    assert store.run_detail(run_id)["cost"] is None  # type: ignore[index]

    rollup = {
        "input_tokens": 1200,
        "output_tokens": 340,
        "total_tokens": 1540,
        "usd": 0.0,
        "calls": 3,
    }
    store.add_decision(run_id, "plan", "1. do it")
    store.add_decision(run_id, "cost", json.dumps(rollup))

    detail = store.run_detail(run_id)
    assert detail is not None
    # The cost row is lifted into a structured field and kept OUT of decisions.
    assert detail["cost"] == rollup
    assert "cost" not in {d["kind"] for d in detail["decisions"]}
    assert "plan" in {d["kind"] for d in detail["decisions"]}


@requires_db
def test_project_cost_aggregates_across_metered_runs(store: MemoryStore) -> None:
    import uuid as _uuid

    pid = f"proj-{_uuid.uuid4().hex[:8]}"
    store.create_project(pid, "cost-test", "src")  # runs.project_id has a FK
    r1, r2, r3 = (f"test-{_uuid.uuid4().hex[:10]}" for _ in range(3))
    for rid in (r1, r2, r3):  # r3 is never metered
        store.record_run(
            run_id=rid,
            source="local",
            branch="b",
            task="t",
            status="APPROVED",
            tests_passed=True,
            iterations=1,
            project_id=pid,
        )
    store.add_decision(
        r1,
        "cost",
        json.dumps(
            {
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
                "usd": 0.5,
                "calls": 2,
                "by_model": [
                    {
                        "model": "gpt",
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "total_tokens": 120,
                        "usd": 0.5,
                        "calls": 2,
                    },
                ],
                "by_agent": [
                    {
                        "agent": "Reviewer",
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "total_tokens": 120,
                        "usd": 0.5,
                        "calls": 2,
                    },
                ],
            }
        ),
    )
    store.add_decision(
        r2,
        "cost",
        json.dumps(
            {
                "input_tokens": 50,
                "output_tokens": 10,
                "total_tokens": 60,
                "usd": 0.0,
                "calls": 1,
                "by_model": [
                    {
                        "model": "qwen",
                        "input_tokens": 50,
                        "output_tokens": 10,
                        "total_tokens": 60,
                        "usd": 0.0,
                        "calls": 1,
                    },
                ],
                "by_agent": [
                    {
                        "agent": "Coder",
                        "input_tokens": 50,
                        "output_tokens": 10,
                        "total_tokens": 60,
                        "usd": 0.0,
                        "calls": 1,
                    },
                ],
            }
        ),
    )
    try:
        c = store.project_cost(pid)
        assert c["total_tokens"] == 180
        assert c["calls"] == 3
        assert c["usd"] == 0.5
        assert c["runs_metered"] == 2
        assert c["runs_total"] == 3
        by = {m["model"]: m for m in c["by_model"]}
        assert by["gpt"]["total_tokens"] == 120 and by["qwen"]["total_tokens"] == 60
        assert c["by_model"][0]["model"] == "gpt"  # sorted by tokens desc
        agents = {a["agent"]: a for a in c["by_agent"]}
        assert agents["Reviewer"]["usd"] == 0.5 and agents["Reviewer"]["total_tokens"] == 120
        assert agents["Coder"]["usd"] == 0.0 and agents["Coder"]["total_tokens"] == 60
    finally:
        with store.session() as sess, sess.begin():
            for rid in (r1, r2, r3):
                obj = sess.get(Run, rid)
                if obj is not None:
                    sess.delete(obj)
            proj = sess.get(Project, pid)
            if proj is not None:
                sess.delete(proj)


@requires_db
def test_set_project_budget_sets_and_clears(store: MemoryStore) -> None:
    pid = f"proj-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "budget", "src")
    try:
        d0 = store.project_detail(pid)
        assert d0 is not None and d0["budget_usd"] is None and d0["budget_tokens"] is None
        store.set_project_budget(pid, budget_usd=25.0, budget_tokens=1_000_000)
        d1 = store.project_detail(pid)
        assert d1 is not None and d1["budget_usd"] == 25.0 and d1["budget_tokens"] == 1_000_000
        # None clears the cap back to NULL (unlike update_project's skip sentinel).
        store.set_project_budget(pid, budget_usd=None, budget_tokens=None)
        d2 = store.project_detail(pid)
        assert d2 is not None and d2["budget_usd"] is None and d2["budget_tokens"] is None
    finally:
        with store.session() as sess, sess.begin():
            proj = sess.get(Project, pid)
            if proj is not None:
                sess.delete(proj)


@requires_db
def test_project_crud_and_run_link(store: MemoryStore) -> None:
    pid = f"proj-test-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "My Project", "https://gitlab.example/x.git", goal="ship it")
    detail = store.project_detail(pid)
    assert detail is not None
    assert detail["name"] == "My Project" and detail["status"] == "draft" and detail["runs"] == []

    store.update_project(pid, status="ready", brief="## Goals\nship", branch="mosaera/project-x")
    detail = store.project_detail(pid)
    assert detail is not None
    assert detail["status"] == "ready" and detail["brief"].startswith("## Goals")

    # A run tagged with the project shows up under it.
    rid = f"test-{uuid.uuid4().hex[:10]}"
    store.record_run(
        run_id=rid,
        source="local",
        branch="b",
        task="t",
        status="APPROVED",
        tests_passed=True,
        iterations=1,
        project_id=pid,
    )
    assert any(p["id"] == pid for p in store.list_projects())
    detail = store.project_detail(pid)
    assert detail is not None and [r["id"] for r in detail["runs"]] == [rid]

    with store.session() as s, s.begin():
        from mosaera_memory.models import Project

        run = s.get(Run, rid)
        if run is not None:
            s.delete(run)
        proj = s.get(Project, pid)
        if proj is not None:
            s.delete(proj)

    assert store.project_detail("nope") is None


@requires_db
def test_backlog_crud_and_run_link(store: MemoryStore) -> None:
    from mosaera_memory.models import Project

    pid = f"proj-test-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "P", "src")
    iid = store.add_backlog_item(pid, "item one", "desc", "acc", 0)
    store.add_backlog_item(pid, "item two", position=1)

    items = store.list_backlog_items(pid)
    assert [i["title"] for i in items] == ["item one", "item two"]
    assert store.get_backlog_item(iid)["status"] == "todo"  # type: ignore[index]

    store.update_backlog_item(iid, status="in_review", title="renamed")
    got = store.get_backlog_item(iid)
    assert got is not None and got["status"] == "in_review" and got["title"] == "renamed"

    # Per-item design (#3): defaults to "", round-trips through update/get/list.
    assert got["design"] == ""
    store.update_backlog_item(iid, design="## Approach\nUse the Foo interface")
    reread = store.get_backlog_item(iid)
    assert reread is not None and "Use the Foo interface" in reread["design"]
    assert any("Foo interface" in i["design"] for i in store.list_backlog_items(pid))

    # Per-item stacked-MR delivery (ADR-0021): branch + mr_url default "" and
    # round-trip through update/get/list, so the sweep can record each item's MR.
    assert reread["branch"] == "" and reread["mr_url"] == "" and reread["mr_state"] == ""
    store.update_backlog_item(
        iid, branch="mosaera/item-1", mr_url="https://gitlab/x/-/merge_requests/3"
    )
    store.update_backlog_item(iid, mr_state="merged")  # ADR-0102: the polled MR state
    delivered = store.get_backlog_item(iid)
    assert delivered is not None and delivered["branch"] == "mosaera/item-1"
    assert delivered["mr_url"].endswith("/merge_requests/3") and delivered["mr_state"] == "merged"
    assert any(i["mr_url"].endswith("/merge_requests/3") for i in store.list_backlog_items(pid))

    detail = store.project_detail(pid)
    assert detail is not None and len(detail["backlog"]) == 2

    # A run tagged with project + item.
    rid = f"test-{uuid.uuid4().hex[:10]}"
    store.record_run(
        run_id=rid,
        source="s",
        branch="b",
        task="t",
        status="APPROVED",
        tests_passed=True,
        iterations=1,
        project_id=pid,
        item_id=iid,
    )
    assert store.run_detail(rid)["project_id"] == pid  # type: ignore[index]

    with store.session() as s, s.begin():
        run = s.get(Run, rid)
        if run is not None:
            s.delete(run)
        proj = s.get(Project, pid)  # cascades to backlog items
        if proj is not None:
            s.delete(proj)


@requires_db
def test_delete_project_and_clear_todo(store: MemoryStore) -> None:
    from mosaera_memory.models import BacklogItem, Project

    pid = f"proj-test-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "P", "src")
    store.add_backlog_item(pid, "todo item", position=0)
    done = store.add_backlog_item(pid, "done item", position=1)
    store.update_backlog_item(done, status="done")

    store.clear_todo_backlog(pid)  # removes only the todo item
    assert [i["title"] for i in store.list_backlog_items(pid)] == ["done item"]

    store.delete_project(pid)  # cascades the remaining backlog
    assert store.project_detail(pid) is None
    with store.session() as s:
        assert s.get(Project, pid) is None
        assert s.get(BacklogItem, done) is None


@requires_db
def test_cancel_run_and_finalize_orphans(store: MemoryStore) -> None:
    from mosaera_memory.models import Project, Run

    pid = f"proj-test-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "P", "src")
    iid = store.add_backlog_item(pid, "one", position=0)
    store.update_backlog_item(iid, status="in_progress")
    rid = f"test-{uuid.uuid4().hex[:10]}"
    store.record_run(
        run_id=rid,
        source="s",
        branch="b",
        task="t",
        status="RUNNING",
        tests_passed=False,
        iterations=0,
        project_id=pid,
        item_id=iid,
    )

    store.cancel_run(rid)
    run = store.get_run(rid)
    assert run is not None and run.status == "CANCELLED"
    got = store.get_backlog_item(iid)
    assert got is not None and got["status"] == "todo"  # item freed

    # A second RUNNING run is swept by finalize_orphans.
    rid2 = f"test-{uuid.uuid4().hex[:10]}"
    store.record_run(
        run_id=rid2,
        source="s",
        branch="b",
        task="t",
        status="RUNNING",
        tests_passed=False,
        iterations=0,
    )
    assert store.finalize_orphans() >= 1
    r2 = store.get_run(rid2)
    assert r2 is not None and r2.status == "CANCELLED"

    with store.session() as s, s.begin():
        for x in (rid, rid2):
            o = s.get(Run, x)
            if o is not None:
                s.delete(o)
        p = s.get(Project, pid)
        if p is not None:
            s.delete(p)


@requires_db
def test_awaiting_approval_survives_finalize_orphans(store: MemoryStore) -> None:
    # A run parked at a gate (AWAITING_APPROVAL) must NOT be swept on restart —
    # it is rehydratable. mark_run_awaiting/mark_run_running gate the transitions.
    from mosaera_memory.models import Run

    rid = f"test-{uuid.uuid4().hex[:10]}"
    store.record_run(
        run_id=rid,
        source="s",
        branch="b",
        task="t",
        status="RUNNING",
        tests_passed=False,
        iterations=0,
    )
    store.mark_run_awaiting(rid)
    assert (store.get_run(rid)).status == "AWAITING_APPROVAL"  # type: ignore[union-attr]

    # finalize_orphans only sweeps RUNNING — the parked run is left alone.
    store.finalize_orphans()
    assert (store.get_run(rid)).status == "AWAITING_APPROVAL"  # type: ignore[union-attr]
    assert rid in {r["run_id"] for r in store.parked_runs()}

    # Resuming flips it back to RUNNING (crash-catchable again).
    store.mark_run_running(rid)
    assert (store.get_run(rid)).status == "RUNNING"  # type: ignore[union-attr]

    with store.session() as s, s.begin():
        o = s.get(Run, rid)
        if o is not None:
            s.delete(o)


@requires_db
def test_mark_run_error_finalizes_only_running(store: MemoryStore) -> None:
    from mosaera_memory.models import Project, Run

    pid = f"proj-test-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "P", "src")
    iid = store.add_backlog_item(pid, "one", position=0)
    store.update_backlog_item(iid, status="in_progress")
    rid = f"test-{uuid.uuid4().hex[:10]}"
    store.record_run(
        run_id=rid,
        source="s",
        branch="b",
        task="t",
        status="RUNNING",
        tests_passed=False,
        iterations=0,
        project_id=pid,
        item_id=iid,
    )

    store.mark_run_error(rid)
    run = store.get_run(rid)
    assert run is not None and run.status == "ERROR"
    got = store.get_backlog_item(iid)
    assert got is not None and got["status"] == "todo"  # item freed

    store.mark_run_error(rid)  # second call: no-op (already settled)
    run = store.get_run(rid)
    assert run is not None and run.status == "ERROR"

    # A settled CANCELLED row is never stomped by a late worker error.
    rid2 = f"test-{uuid.uuid4().hex[:10]}"
    store.record_run(
        run_id=rid2,
        source="s",
        branch="b",
        task="t",
        status="RUNNING",
        tests_passed=False,
        iterations=0,
    )
    store.cancel_run(rid2)
    store.mark_run_error(rid2)
    r2 = store.get_run(rid2)
    assert r2 is not None and r2.status == "CANCELLED"

    with store.session() as s, s.begin():
        for x in (rid, rid2):
            o = s.get(Run, x)
            if o is not None:
                s.delete(o)
        p = s.get(Project, pid)
        if p is not None:
            s.delete(p)


@requires_db
def test_delete_run_removes_children(store: MemoryStore, run_id: str) -> None:
    store.add_decision(run_id, "plan", "1.")
    store.delete_run(run_id)
    assert store.get_run(run_id) is None


@requires_db
def test_vector_similarity_ranks_closest(store: MemoryStore, run_id: str) -> None:
    near = [0.0] * EMBED_DIM
    near[0] = 1.0
    far = [0.0] * EMBED_DIM
    far[1] = 1.0
    store.add_artifact(run_id, "diff", "near artifact", embedding=near)
    store.add_artifact(run_id, "diff", "far artifact", embedding=far)

    query = [0.0] * EMBED_DIM
    query[0] = 0.9
    query[1] = 0.1
    results = store.similar_artifacts(query, k=2)
    assert len(results) >= 1
    assert results[0][0].content == "near artifact"


@requires_db
def test_attachment_lifecycle(store: MemoryStore) -> None:
    from mosaera_memory.models import Attachment, Project

    pid = f"proj-test-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "P", "src")
    att = f"att-{uuid.uuid4().hex[:10]}"
    store.add_attachment(
        att,
        pid,
        filename="notes.md",
        mime_type="text/markdown",
        size_bytes=42,
        sha256="a" * 64,
        storage_path=f"projects/{pid}/{att}/original/notes.md",
        status="ready",
        token_estimate=10,
        scope="project_context",
    )
    got = store.get_attachment(att)
    assert got is not None and got["status"] == "ready" and got["scope"] == "project_context"
    assert store.list_attachments(pid)[0]["id"] == att

    # Dedup lookup finds it by content hash; a different hash finds nothing.
    assert store.find_attachment_by_hash(pid, "a" * 64) is not None
    assert store.find_attachment_by_hash(pid, "b" * 64) is None

    # Message linkage survives soft deletion (history never breaks).
    mid = store.add_message(pid, "user", "see attached")
    store.link_message_attachments(mid, [att])
    assert store.attachments_for_message(mid)[0]["id"] == att
    # The transcript carries its attachments (rendered as chips in the UI).
    linked = store.list_messages(pid)[-1]["attachments"]
    assert linked[0]["filename"] == "notes.md" and linked[0]["scope"] == "project_context"
    store.soft_delete_attachment(att)
    assert store.list_attachments(pid) == []  # gone from active lists
    assert store.list_attachments(pid, include_deleted=True)[0]["deleted_at"] is not None
    assert store.attachments_for_message(mid)[0]["id"] == att  # link intact

    with store.session() as s, s.begin():
        for row in s.query(Attachment).filter_by(project_id=pid):
            s.delete(row)
        p = s.get(Project, pid)
        if p is not None:
            s.delete(p)


@requires_db
def test_derivatives_and_context_items(store: MemoryStore) -> None:
    from mosaera_memory.models import Attachment, Project, ProjectContextItem

    pid = f"proj-test-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "P", "src")
    att = f"att-{uuid.uuid4().hex[:10]}"
    store.add_attachment(
        att,
        pid,
        filename="brand.md",
        mime_type="text/markdown",
        size_bytes=9,
        sha256="c" * 64,
        storage_path="p",
        status="processing",
        token_estimate=2,
        scope="project_context",
    )

    # Derivatives replace atomically — reprocessing never duplicates a kind.
    store.replace_derivatives(
        att,
        [
            {"kind": "text_extract", "content": "brand rules", "token_count": 3},
            {"kind": "chunk", "content": "part one", "token_count": 2, "chunk_index": 0},
            {"kind": "chunk", "content": "part two", "token_count": 2, "chunk_index": 1},
        ],
    )
    store.replace_derivatives(
        att,
        [
            {"kind": "text_extract", "content": "brand rules v2", "token_count": 4},
            {"kind": "summary_short", "content": "Brand guide.", "token_count": 3, "model": "m"},
        ],
    )
    all_d = store.list_derivatives(att)
    assert [d["kind"] for d in all_d] == ["summary_short", "text_extract"]
    assert store.list_derivatives(att, kind="summary_short")[0]["content"] == "Brand guide."

    # update_attachment patches only allowed fields.
    store.update_attachment(att, status="ready", token_estimate=4, nonsense="x")
    got = store.get_attachment(att)
    assert got is not None and got["status"] == "ready" and got["token_estimate"] == 4

    # Context items: upsert enables/updates, disable hides (guardrail 8).
    store.upsert_project_context_item(
        pid, att, title="brand.md", summary="Brand guide.", token_count=3
    )
    assert store.list_project_context_items(pid)[0]["title"] == "brand.md"
    store.upsert_project_context_item(pid, att, title="brand.md", summary="Updated.", token_count=4)
    items = store.list_project_context_items(pid)
    assert len(items) == 1 and items[0]["summary"] == "Updated."
    store.disable_project_context_item(pid, att)
    assert store.list_project_context_items(pid) == []
    store.upsert_project_context_item(  # re-enable revives the same row
        pid, att, title="brand.md", summary="Back.", token_count=1
    )
    assert store.list_project_context_items(pid)[0]["summary"] == "Back."

    with store.session() as s, s.begin():
        for item_row in s.query(ProjectContextItem).filter_by(project_id=pid):
            s.delete(item_row)
        for att_row in s.query(Attachment).filter_by(project_id=pid):
            s.delete(att_row)
        p = s.get(Project, pid)
        if p is not None:
            s.delete(p)


@requires_db
def test_message_context_sources(store: MemoryStore) -> None:
    from mosaera_memory.models import Attachment, MessageContextSource, Project

    pid = f"proj-test-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "P", "src")
    mid = store.add_message(pid, "pm", "reply")
    store.add_message_context_sources(
        mid,
        [
            {"source_type": "brief", "title": "Project brief"},
            {
                "source_type": "attachment",
                "source_id": "att-1",
                "title": "brand.md",
                "included_as": "summary",
                "token_count": 42,
            },
        ],
    )
    msg = store.list_messages(pid)[-1]
    assert [s["source_type"] for s in msg["context_sources"]] == ["brief", "attachment"]
    assert msg["context_sources"][1]["included_as"] == "summary"
    assert msg["context_sources"][1]["token_count"] == 42

    with store.session() as s, s.begin():
        for row in s.query(MessageContextSource).all():
            if row.message_id == mid:
                s.delete(row)
        for att_row in s.query(Attachment).filter_by(project_id=pid):
            s.delete(att_row)
        p = s.get(Project, pid)
        if p is not None:
            s.delete(p)


def _drop_project(store: MemoryStore, pid: str) -> None:
    with store.session() as s, s.begin():
        p = s.get(Project, pid)
        if p is not None:
            s.delete(p)  # CASCADE removes backlog items + their dependency edges


@requires_db
def test_backlog_item_dependencies_and_blocked_derivation(store: MemoryStore) -> None:
    # B depends on A: B is blocked while A is undelivered, and unblocks once A reaches
    # in_review (delivered) — the runner never sets "done", so in_review must satisfy.
    pid = f"proj-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "deps", "src")
    try:
        a = store.add_backlog_item(pid, "A foundation")
        b = store.add_backlog_item(pid, "B dependent")
        store.set_item_dependencies(b, [a])
        bi = store.get_backlog_item(b)
        assert bi is not None
        assert bi["depends_on"] == [a] and bi["blocked_by"] == [a]
        assert store.blocking_dependencies(b) == [a]
        store.update_backlog_item(a, status="in_review")  # delivered
        bi = store.get_backlog_item(b)
        assert bi is not None
        assert bi["blocked_by"] == [] and store.blocking_dependencies(b) == []
    finally:
        _drop_project(store, pid)


@requires_db
def test_reorder_backlog_rewrites_positions(store: MemoryStore) -> None:
    pid = f"proj-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "reorder", "src")
    try:
        a = store.add_backlog_item(pid, "A", position=0)
        b = store.add_backlog_item(pid, "B", position=1)
        c = store.add_backlog_item(pid, "C", position=2)
        store.reorder_backlog(pid, [c, a, b])
        items = store.list_backlog_items(pid)  # returned position-ordered
        assert [i["id"] for i in items] == [c, a, b]
        assert [i["position"] for i in items] == [0, 1, 2]
        with pytest.raises(ValueError):
            store.reorder_backlog(pid, [a, b])  # incomplete set
        with pytest.raises(ValueError):
            store.reorder_backlog(pid, [a, b, c, 999999])  # foreign id
    finally:
        _drop_project(store, pid)


@requires_db
def test_soft_lock_set_get_and_summary(store: MemoryStore) -> None:
    pid = f"proj-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "lock", "src")
    try:
        a = store.add_backlog_item(pid, "A")
        assert store.is_item_locked(a) == (False, "")
        store.set_item_lock(a, True, "wait for the schema item to land first")
        assert store.is_item_locked(a) == (True, "wait for the schema item to land first")
        bi = store.get_backlog_item(a)
        assert bi is not None
        assert (
            bi["locked"] is True and bi["lock_reason"] == "wait for the schema item to land first"
        )
        store.set_item_lock(a, False)  # unlock clears the caveat
        assert store.is_item_locked(a) == (False, "")
        assert store.get_backlog_item(a)["lock_reason"] == ""  # type: ignore[index]
    finally:
        _drop_project(store, pid)


@requires_db
def test_delete_backlog_item_removes_edges_and_renumbers(store: MemoryStore) -> None:
    pid = f"proj-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "del", "src")
    try:
        a = store.add_backlog_item(pid, "A", position=0)
        b = store.add_backlog_item(pid, "B", position=1)
        c = store.add_backlog_item(pid, "C", position=2)
        store.set_item_dependencies(c, [b])  # C depends on B
        store.delete_backlog_item(b)
        items = store.list_backlog_items(pid)
        assert [i["id"] for i in items] == [a, c]  # B gone
        assert [i["position"] for i in items] == [0, 1]  # renumbered, gap closed
        got = store.get_backlog_item(c)
        assert got is not None and got["depends_on"] == []  # edge to B removed (CASCADE)
    finally:
        _drop_project(store, pid)


@requires_db
def test_split_backlog_item_inherits_deps_and_rewires_dependents(store: MemoryStore) -> None:
    pid = f"proj-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "split", "src")
    try:
        base = store.add_backlog_item(pid, "base", position=0)
        x = store.add_backlog_item(pid, "X", position=1)
        dep = store.add_backlog_item(pid, "dependent", position=2)
        store.set_item_dependencies(x, [base])  # X depends on base
        store.set_item_dependencies(dep, [x])  # dep depends on X
        children = store.split_backlog_item(
            x, [{"title": "X1", "description": "d1", "acceptance": "a1"}, {"title": "X2"}]
        )
        assert len(children) == 2
        items = {i["id"]: i for i in store.list_backlog_items(pid)}
        assert x not in items  # parent deleted
        for cid in children:  # each child inherits X's deps (base)
            assert items[cid]["depends_on"] == [base]
        assert set(items[dep]["depends_on"]) == set(children)  # dep now waits for ALL children
    finally:
        _drop_project(store, pid)


@requires_db
def test_merge_backlog_items_unions_deps_and_repoints_dependents(store: MemoryStore) -> None:
    pid = f"proj-{uuid.uuid4().hex[:8]}"
    p2 = f"proj-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "merge", "src")
    store.create_project(p2, "p2", "src")
    try:
        d1 = store.add_backlog_item(pid, "dep1", position=0)
        d2 = store.add_backlog_item(pid, "dep2", position=1)
        t = store.add_backlog_item(pid, "target", position=2)
        src = store.add_backlog_item(pid, "source", position=3)
        x = store.add_backlog_item(pid, "dependent-of-source", position=4)
        store.set_item_dependencies(t, [d1])  # target depends on d1
        store.set_item_dependencies(src, [d2])  # source depends on d2
        store.set_item_dependencies(x, [src])  # x depends on source
        store.merge_backlog_items(t, [src], title="merged target")
        items = {i["id"]: i for i in store.list_backlog_items(pid)}
        assert src not in items  # source deleted
        assert items[t]["title"] == "merged target"
        assert set(items[t]["depends_on"]) == {d1, d2}  # unioned deps
        assert items[x]["depends_on"] == [t]  # x repointed onto the target
        other = store.add_backlog_item(p2, "other-project item")
        with pytest.raises(ValueError):
            store.merge_backlog_items(t, [other])  # cross-project source rejected
    finally:
        _drop_project(store, pid)
        _drop_project(store, p2)


@requires_db
def test_set_item_dependencies_rejects_self_cycle_and_cross_project(store: MemoryStore) -> None:
    p1 = f"proj-{uuid.uuid4().hex[:8]}"
    p2 = f"proj-{uuid.uuid4().hex[:8]}"
    store.create_project(p1, "p1", "src")
    store.create_project(p2, "p2", "src")
    try:
        a = store.add_backlog_item(p1, "A")
        b = store.add_backlog_item(p1, "B")
        other = store.add_backlog_item(p2, "other-project item")
        with pytest.raises(ValueError):
            store.set_item_dependencies(a, [a])  # self
        with pytest.raises(ValueError):
            store.set_item_dependencies(a, [other])  # cross-project
        with pytest.raises(ValueError):
            store.set_item_dependencies(a, [999999])  # unknown
        store.set_item_dependencies(a, [b])  # A -> B is fine
        with pytest.raises(ValueError, match="cycle"):
            store.set_item_dependencies(b, [a])  # B -> A would close a cycle
    finally:
        _drop_project(store, p1)
        _drop_project(store, p2)


@requires_db
def test_latest_cost_returns_newest_rollup(store: MemoryStore) -> None:
    # latest_cost powers restart recovery: a rehydrated run seeds its meter from the
    # newest persisted cost rollup so spend isn't reset to zero.
    pid = f"proj-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "cost", "src")
    rid = f"test-{uuid.uuid4().hex[:10]}"
    store.record_run(
        run_id=rid,
        source="local",
        branch="b",
        task="t",
        status="APPROVED",
        tests_passed=True,
        iterations=1,
        project_id=pid,
    )
    try:
        assert store.latest_cost(rid) is None  # nothing persisted yet
        store.add_decision(rid, "cost", json.dumps({"total_tokens": 100, "usd": 0.1, "calls": 2}))
        store.add_decision(rid, "cost", json.dumps({"total_tokens": 300, "usd": 0.3, "calls": 5}))
        latest = store.latest_cost(rid)
        assert latest is not None and latest["total_tokens"] == 300 and latest["calls"] == 5
    finally:
        with store.session() as s, s.begin():
            r = s.get(Run, rid)
            if r is not None:
                s.delete(r)
        _drop_project(store, pid)


@requires_db
def test_mark_run_incomplete_sets_status_and_reason(store: MemoryStore, run_id: str) -> None:
    store.mark_run_incomplete(run_id, "reached the iteration limit without meeting acceptance")
    run = store.get_run(run_id)
    assert run is not None
    assert run.status == "INCOMPLETE"
    assert run.termination_reason == "reached the iteration limit without meeting acceptance"
    detail = store.run_detail(run_id)
    assert detail is not None
    assert detail["termination_reason"].startswith("reached the iteration")


@requires_db
def test_mark_run_incomplete_never_overwrites_cancelled(store: MemoryStore, run_id: str) -> None:
    store.cancel_run(run_id)
    store.mark_run_incomplete(run_id, "should not apply")
    run = store.get_run(run_id)
    assert run is not None and run.status == "CANCELLED"
    assert run.termination_reason is None


@requires_db
def test_run_events_append_and_list_in_insert_order(store: MemoryStore, run_id: str) -> None:
    # Listed in true insert order (by id), so a rehydrated run's restarted seq
    # counter can't scramble the chronology. Data round-trips as parsed JSON.
    store.add_run_event(run_id, 1, "thought", "plan", 100, json.dumps({"text": "hmm"}))
    store.add_run_event(
        run_id, 2, "activity", "implement", 200, json.dumps({"kind": "file_written"})
    )
    events = store.list_run_events(run_id)
    assert [e["type"] for e in events] == ["thought", "activity"]
    assert events[0]["seq"] == 1 and events[0]["node"] == "plan"
    assert events[0]["data"] == {"text": "hmm"}
    assert events[1]["ts"] == 200


@requires_db
def test_user_cap_and_unique_username(store: MemoryStore) -> None:
    """The seat cap and unique-username rule, both inside one transaction.

    Teardown deletes ONLY the accounts this test made. It used to delete every user in the
    database, which is a landmine for anyone who ever points MOSAERA_TEST_DB_URL at something
    real — it wiped a live admin account on 2026-08-05. A test that cleans up more than it
    created is not isolated, it is destructive.

    The cap is measured RELATIVE to the starting count for the same reason: assuming an empty
    users table silently couples this test to whatever else is in the database.
    """
    start = store.count_users()
    made = []
    try:
        for i in range(5):
            made.append(store.create_user(f"u{i}_{uuid.uuid4().hex[:4]}", "h", max_users=start + 5))
        assert store.count_users() >= start + 5
        with pytest.raises(ValueError, match="user_limit"):
            store.create_user("over_" + uuid.uuid4().hex[:4], "h", max_users=start + 5)
        with pytest.raises(ValueError, match="username_taken"):
            store.create_user(made[0]["username"], "h", max_users=start + 99)
    finally:
        for u in made:
            store.delete_user(u["id"])
        assert store.count_users() == start, "teardown must restore the starting state exactly"


@requires_db
def test_session_lifecycle_and_expiry(store: MemoryStore) -> None:
    from datetime import UTC, datetime, timedelta

    u = store.create_user("sess_" + uuid.uuid4().hex[:5], "h", is_admin=True)
    try:
        now = datetime.now(UTC)
        store.create_session("tok-live", u["id"], now + timedelta(hours=1))
        store.create_session("tok-dead", u["id"], now - timedelta(hours=1))
        live = store.session_user("tok-live", now)
        assert live is not None and live["username"] == u["username"]
        assert store.session_user("tok-dead", now) is None  # expired
        assert store.session_user("nope", now) is None
        assert store.count_admins() >= 1
        assert store.prune_sessions(now) >= 1  # sweeps the dead one
        # Deleting the user cascades to their remaining sessions.
        store.delete_user(u["id"])
        assert store.session_user("tok-live", now) is None
    finally:
        for x in store.list_users():
            store.delete_user(x["id"])


@requires_db
def test_doctrine_chunk_roundtrip_and_filters(store: MemoryStore) -> None:
    from mosaera_memory.models import DoctrineChunk

    cid = store.add_doctrine_chunk(
        "global", "Prefer small, single-purpose functions.", source="core.md", kind="methodology"
    )
    try:
        rows = store.load_doctrine("global")
        assert any(r["content"].startswith("Prefer small") for r in rows)
        assert store.load_doctrine("global", kind="methodology")  # kind filter matches
        assert store.load_doctrine("global", kind="nonexistent") == []
        # Scope isolation: a global chunk is never returned for the project scope.
        assert all("Prefer small" not in r["content"] for r in store.load_doctrine("project"))
    finally:
        with store.session() as s, s.begin():
            obj = s.get(DoctrineChunk, cid)
            if obj is not None:
                s.delete(obj)


@requires_db
def test_pm_sessions_scope_history_and_lifecycle(store: MemoryStore) -> None:
    from mosaera_memory.models import Project

    pid = f"proj-sess-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "sessions", "src")
    try:
        # No sessions yet; ensure_default mints the first one.
        assert store.list_pm_sessions(pid) == []
        default = store.ensure_default_pm_session(pid)
        assert [s["id"] for s in store.list_pm_sessions(pid)] == [default]
        # A second, explicitly-titled session.
        other = store.create_pm_session(pid, title="Research")

        # Turns are written into a session; history reads back per-session.
        store.add_message(pid, "user", "wire up OAuth", session_id=default)
        store.add_message(pid, "pm", "on it", session_id=default)
        store.add_message(pid, "user", "unrelated question", session_id=other)
        assert [m["content"] for m in store.list_messages(pid, default)] == [
            "wire up OAuth",
            "on it",
        ]
        assert [m["content"] for m in store.list_messages(pid, other)] == ["unrelated question"]
        # No session_id → the whole project's turns (decomposition path).
        assert len(store.list_messages(pid)) == 3

        # First user turn auto-names the untitled default; the titled one is untouched.
        titles = {s["id"]: s["title"] for s in store.list_pm_sessions(pid)}
        assert titles[default] == "wire up OAuth"
        assert titles[other] == "Research"
        # message_count is reported per session.
        counts = {s["id"]: s["message_count"] for s in store.list_pm_sessions(pid)}
        assert counts[default] == 2 and counts[other] == 1
        # Recency: `other` was written last, so it floats to the top.
        assert store.list_pm_sessions(pid)[0]["id"] == other

        # Rename.
        store.rename_pm_session(other, "Renamed")
        renamed = store.get_pm_session(other)
        assert renamed is not None and renamed["title"] == "Renamed"

        # Archive is soft: hidden from the active list AND the default resolver, still fetchable.
        store.set_pm_session_archived(other, True)
        active_ids = {s["id"] for s in store.list_pm_sessions(pid)}
        assert other not in active_ids and default in active_ids
        assert other in {s["id"] for s in store.list_pm_sessions(pid, include_archived=True)}
        archived = store.get_pm_session(other)
        assert archived is not None and archived["archived"] is True
        assert store.ensure_default_pm_session(pid) == default  # never an archived session
        # Unarchive restores it to the active set.
        store.set_pm_session_archived(other, False)
        assert other in {s["id"] for s in store.list_pm_sessions(pid)}
    finally:
        with store.session() as s, s.begin():
            p = s.get(Project, pid)
            if p is not None:
                s.delete(p)  # cascades to sessions + messages


@requires_db
def test_0013_backfill_adopts_legacy_messages(store: MemoryStore) -> None:
    """The 0013 backfill turns a pre-sessions 'forever-chat' into one default session per
    project: every NULL-session turn is adopted, nothing orphaned, title from the first user
    turn — so a migrated project is indistinguishable from a freshly-created one."""
    import importlib.util
    from pathlib import Path

    import mosaera_memory
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from mosaera_memory.models import Project
    from sqlalchemy import text

    pid = f"proj-bf-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "backfill", "src")
    try:
        # Simulate a pre-0013 project: turns with NULL session_id and no session rows.
        with store.session() as s, s.begin():
            for role, content in (("user", "Legacy first message"), ("pm", "legacy reply")):
                s.execute(
                    text(
                        "INSERT INTO project_messages "
                        "(project_id, session_id, role, content, created_at) "
                        "VALUES (:pid, NULL, :role, :content, now())"
                    ),
                    {"pid": pid, "role": role, "content": content},
                )

        # Load and run the migration's backfill against the live DB (digit-leading module name →
        # load by path, not import).
        path = (
            Path(mosaera_memory.__file__).parent / "migrations" / "versions" / "0013_pm_sessions.py"
        )
        spec = importlib.util.spec_from_file_location("mig_0013_pm_sessions", path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with store._engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                mod._backfill_default_sessions()

        sessions = store.list_pm_sessions(pid)
        assert len(sessions) == 1
        assert sessions[0]["title"] == "Legacy first message"
        assert sessions[0]["message_count"] == 2
        assert [m["content"] for m in store.list_messages(pid, sessions[0]["id"])] == [
            "Legacy first message",
            "legacy reply",
        ]
    finally:
        with store.session() as s, s.begin():
            p = s.get(Project, pid)
            if p is not None:
                s.delete(p)


@requires_db
def test_coverage_ledger_persists_selects_and_detects_rot(store: MemoryStore) -> None:
    """The durable test ledger (#32): a region's coverage persists + round-trips; a changed
    region resolves to its covering tests (impact selection); a region whose source_hash changed
    without re-verification surfaces as stale (rot)."""
    from mosaera_memory.models import Project

    pid = f"proj-cov-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "coverage", "src")
    try:
        # Two regions with distinct covering tests.
        store.upsert_coverage_region(
            pid,
            "pkg/a.py::foo",
            region_fingerprint="fp-foo",
            source_hash="hash-foo-v1",
            covering_tests=["tests/test_a.py::test_foo", "tests/test_a.py::test_shared"],
        )
        store.upsert_coverage_region(
            pid,
            "pkg/b.py::bar",
            region_fingerprint="fp-bar",
            source_hash="hash-bar-v1",
            covering_tests=["tests/test_b.py::test_bar", "tests/test_a.py::test_shared"],
        )

        # Round-trip.
        foo = store.get_coverage_region(pid, "pkg/a.py::foo")
        assert foo is not None
        assert foo["source_hash"] == "hash-foo-v1"
        assert foo["covering_tests"] == [
            "tests/test_a.py::test_foo",
            "tests/test_a.py::test_shared",
        ]
        assert foo["mutation_caught"] is None and foo["last_verified_at"] is not None
        assert {r["region_key"] for r in store.list_coverage_regions(pid)} == {
            "pkg/a.py::foo",
            "pkg/b.py::bar",
        }

        # Impact selection: changed regions → the UNION of their covering tests (shared test once).
        assert store.select_covering_tests(pid, ["pkg/a.py::foo"]) == [
            "tests/test_a.py::test_foo",
            "tests/test_a.py::test_shared",
        ]
        # `bar` is covered by tests/test_b.py::test_bar (see the upsert above) — the union is
        # sorted, so it lands LAST, not first. The old expectation named a `tests/test_a.py`
        # ::test_bar that was never inserted, so this assertion could only ever fail.
        assert store.select_covering_tests(pid, ["pkg/a.py::foo", "pkg/b.py::bar"]) == [
            "tests/test_a.py::test_foo",
            "tests/test_a.py::test_shared",
            "tests/test_b.py::test_bar",
        ]
        # An unknown changed region contributes nothing (caller falls back to the full suite).
        assert store.select_covering_tests(pid, ["pkg/z.py::gone"]) == []
        assert store.select_covering_tests(pid, []) == []

        # Idempotent upsert: re-verifying foo overwrites in place (no duplicate row) and can set
        # the mutation verdict; the compounding map stays one-row-per-region.
        store.upsert_coverage_region(
            pid,
            "pkg/a.py::foo",
            region_fingerprint="fp-foo",
            source_hash="hash-foo-v2",
            covering_tests=["tests/test_a.py::test_foo"],
            mutation_caught=True,
        )
        assert len(store.list_coverage_regions(pid)) == 2  # still two regions, not three
        foo2 = store.get_coverage_region(pid, "pkg/a.py::foo")
        assert foo2 is not None
        assert foo2["source_hash"] == "hash-foo-v2" and foo2["mutation_caught"] is True
        assert foo2["covering_tests"] == ["tests/test_a.py::test_foo"]

        # Rot: keyed on the churn-stable FINGERPRINT, not the raw source_hash — bar's CODE changed
        # (fingerprint differs) → stale; foo has a matching current fingerprint → fresh; a key not
        # passed is not evaluated. Note foo's source_hash IS different (v2) yet its fingerprint
        # matches → NOT stale, the whole point (a cosmetic edit mustn't invalidate coverage).
        stale = store.stale_coverage_regions(
            pid, {"pkg/a.py::foo": "fp-foo", "pkg/b.py::bar": "fp-bar-CHANGED"}
        )
        assert [r["region_key"] for r in stale] == ["pkg/b.py::bar"]
        assert store.stale_coverage_regions(pid, {"pkg/a.py::foo": "fp-foo"}) == []
        assert store.stale_coverage_regions(pid, {}) == []

        # Isolation: another project's identical region_key is never returned here.
        other = f"proj-cov2-{uuid.uuid4().hex[:8]}"
        store.create_project(other, "other", "src")
        store.upsert_coverage_region(
            other, "pkg/a.py::foo", region_fingerprint="x", source_hash="y", covering_tests=["t"]
        )
        assert store.select_covering_tests(pid, ["pkg/a.py::foo"]) == [
            "tests/test_a.py::test_foo"
        ]  # still foo's v2 tests, not other's
        with store.session() as s, s.begin():
            op = s.get(Project, other)
            if op is not None:
                s.delete(op)
    finally:
        with store.session() as s, s.begin():
            p = s.get(Project, pid)
            if p is not None:
                s.delete(p)  # FK CASCADE removes the ledger rows


@requires_db
def test_coverage_ledger_cascades_on_project_delete(store: MemoryStore) -> None:
    from mosaera_memory.models import CoverageLedger, Project

    pid = f"proj-covdel-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "covdel", "src")
    store.upsert_coverage_region(
        pid, "pkg/a.py::foo", region_fingerprint="fp", source_hash="h", covering_tests=["t"]
    )
    with store.session() as s, s.begin():
        s.delete(s.get(Project, pid))
    with store.session() as s:
        remaining = s.query(CoverageLedger).filter_by(project_id=pid).count()
    assert remaining == 0  # deleting the project cascades to its ledger rows


@requires_db
def test_the_run_diagnosis_is_durable(store: MemoryStore, run_id: str) -> None:
    """How a run ended, structured (#75, migration 0022). Before this a finished run kept
    `termination_reason` — 80 characters — so every failure seen through the UI was an anecdote
    with nothing to answer "did this recur?" three days later."""
    diagnosis = {
        "outcome": "honest_park",
        "park_cause": "give_up",
        "gate_reasons": ["validation_failed", "unsatisfied_claim"],
        "give_up_reason": "no convergence: failing count 4 -> 4 -> 4",
        "vouch": "no_vouch:not_behavior_preserving",
    }
    store.record_run_diagnosis(run_id, diagnosis)
    row = next(r for r in store.list_runs() if r["id"] == run_id)
    assert row["diagnosis"]["outcome"] == "honest_park"
    assert row["diagnosis"]["gate_reasons"] == ["validation_failed", "unsatisfied_claim"]
    detail = store.run_detail(run_id)
    assert detail is not None and detail["diagnosis"]["park_cause"] == "give_up"


@requires_db
def test_the_diagnosis_is_null_until_written(store: MemoryStore, run_id: str) -> None:
    """Null is honest: a pre-0022 row, a run in flight, or a terminal path that never reached the
    diagnosis. It must never be inferred from anything else."""
    row = next(r for r in store.list_runs() if r["id"] == run_id)
    assert row["diagnosis"] is None
    store.record_run_diagnosis(run_id, {})  # an empty record is not a record
    row = next(r for r in store.list_runs() if r["id"] == run_id)
    assert row["diagnosis"] is None


@requires_db
def test_a_cancelled_run_keeps_its_status_but_still_records_why_it_ended(
    store: MemoryStore,
) -> None:
    """A cancel is authoritative for STATUS — a worker finishing after the operator cancelled must
    not write over the settled verdict. It is NOT authoritative for the diagnosis.

    This test previously asserted `diagnosis is None` here, encoding the defect F50 was filed
    against: `/runs/{id}/cancel` marks the row CANCELLED synchronously, so the worker's diagnosis
    always arrived afterwards and was dropped. Every LedgerCLI run was cancelled, so the project's
    entire history was diagnostically blank and the PM correctly reported it could not say why any
    run ended. The status half of the original intent is what mattered and is still asserted below;
    the diagnosis half was the bug being locked in.
    """
    rid = f"test-{uuid.uuid4().hex[:10]}"
    store.ensure_run(rid, source="local", branch="b", task="t")
    try:
        store.cancel_run(rid)
        store.record_run_diagnosis(rid, {"outcome": "honest_park", "ended_by": "cancelled"})
        row = next(r for r in store.list_runs() if r["id"] == rid)
        assert row["status"] == "CANCELLED"  # the verdict is still untouchable
        assert row["diagnosis"]["ended_by"] == "cancelled"  # but the reason now survives
    finally:
        store.delete_run(rid)


@requires_db
def test_a_late_status_write_still_cannot_stomp_a_cancel(store: MemoryStore) -> None:
    """The guard that F50's fix removed from `record_run_diagnosis` must remain on every writer
    that actually sets `status` — dropping it there would let a late worker resurrect a cancelled
    run. Pins the boundary of the fix."""
    rid = f"test-{uuid.uuid4().hex[:10]}"
    store.ensure_run(rid, source="local", branch="b", task="t")
    try:
        store.cancel_run(rid)
        store.mark_run_incomplete(rid, "no convergence")
        store.mark_run_error(rid)
        row = next(r for r in store.list_runs() if r["id"] == rid)
        assert row["status"] == "CANCELLED"
        assert row["termination_reason"] is None
    finally:
        store.delete_run(rid)
