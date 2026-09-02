"""The Layer-2 disposition sweep rung (#76, ADR-0074): ``_try_close_named_gap``.

The core gap-closer (``mosaera_core.disposition.close_oracle_gap``) is exercised end-to-end in
``packages/core/tests/test_disposition.py``. Here we test only the SWEEP wiring: the convertible-
class detection, the default-OFF short-circuit, and that a ``verified`` disposition ships in place
(commit → in_review → per-item MR → advance) while any other verdict preserves the honest park.
``close_oracle_gap`` and ``_open_author_context`` are monkeypatched so no sandbox/model runs.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from mosaera_core.config import Settings
from mosaera_core.disposition import DispositionResult


class _FakeSession:
    def __init__(self, status: str, final: dict[str, Any] | None = None) -> None:
        self.status = status
        self.final = final or {}


class _FakeMemory:
    """The minimal durable-memory surface the disposition rung touches."""

    def __init__(self) -> None:
        self.items: dict[int, dict[str, Any]] = {}
        self.projects: dict[str, dict[str, Any]] = {}
        self.audits: list[tuple[str, str, str]] = []

    def add_item(self, iid: int, **kw: Any) -> None:
        self.items[iid] = {"id": iid, "status": "todo", **kw}

    def update_backlog_item(self, iid: int, **kw: Any) -> None:
        self.items.setdefault(iid, {"id": iid}).update(kw)

    def update_project(self, pid: str, **kw: Any) -> None:
        self.projects.setdefault(pid, {"id": pid}).update({k: v for k, v in kw.items()})

    def add_audit_event(self, run_id: str, event: str, detail: str = "") -> None:
        self.audits.append((run_id, event, detail))


def _settings(**over: Any) -> Settings:
    fields = {"disposition_gap_close": True, **over}
    return dataclasses.replace(Settings.from_env(env={}), **fields)


def _ctx() -> Any:
    from mosaera_api.routes.context import AppContext

    return AppContext(memory=_FakeMemory())  # type: ignore[arg-type]


def _convertible_final(reasons: list[str] | None = None) -> dict[str, Any]:
    return {
        "gate_decision": {"reasons": reasons or ["reviewer_unknown", "oracle_unverified"]},
        "tests_passed": True,
        "tests_modified": False,
        "outcome_verdict": {"vetoed": False},
        "diff": "diff --git a/calc.py b/calc.py\n",
    }


# --- convertible-class detection (pure) -------------------------------------------------------


@pytest.mark.parametrize(
    "reasons",
    [
        ["oracle_unverified"],
        ["reviewer_unknown", "oracle_unverified"],
        ["oracle_unverified", "iteration_limit"],
        ["reviewer_unknown", "oracle_unverified", "iteration_limit"],
    ],
)
def test_convertible_reason_sets(reasons: list[str]) -> None:
    from mosaera_api.app_context._escalation import _is_convertible_park

    assert _is_convertible_park(_convertible_final(reasons)) is True


@pytest.mark.parametrize(
    "final",
    [
        {"gate_decision": {"reasons": []}},  # a clean deliver, not a park
        {"gate_decision": {"reasons": ["validation_failed"]}},  # tests red
        {
            "gate_decision": {"reasons": ["oracle_unverified", "security_findings"]}
        },  # real objection
        {"gate_decision": {"reasons": ["oracle_unverified", "reviewer_requested_changes"]}},
        {"gate_decision": {"reasons": ["oracle_unverified", "tests_tampered"]}},  # tamper
        {"gate_decision": {"reasons": ["oracle_unverified", "critic_vetoed"]}},  # held-out veto
    ],
)
def test_non_convertible_reason_sets(final: dict[str, Any]) -> None:
    from mosaera_api.app_context._escalation import _is_convertible_park

    final.setdefault("tests_passed", True)
    assert _is_convertible_park(final) is False


def test_convertible_rejected_when_tests_modified() -> None:
    from mosaera_api.app_context._escalation import _is_convertible_park

    final = _convertible_final()
    final["tests_modified"] = True
    assert _is_convertible_park(final) is False


def test_convertible_rejected_when_critic_vetoed_flag() -> None:
    from mosaera_api.app_context._escalation import _is_convertible_park

    final = _convertible_final(["oracle_unverified"])
    final["outcome_verdict"] = {"vetoed": True}
    assert _is_convertible_park(final) is False


@pytest.mark.parametrize(
    "channel,value",
    [
        ("stalled", True),
        ("give_up_reason", "escalation unresolved: need a human decision"),
        ("plan_unworkable_reason", "no workable plan"),
        ("blocked_reason", "needs a product call"),
        ("escalate_reason", "coder raised a scope question"),
    ],
)
def test_convertible_rejected_when_an_honest_stop_channel_is_set(channel: str, value: Any) -> None:
    # Red-team agent 1: a thrash/plan/supervise stop or a coder hand-raise carries its real reason
    # OUT OF BAND (not in gate_decision.reasons) while an incidental green `oracle_unverified` rides
    # in the gate reasons. Such a park is a safety stop / the escalate arm — never convertible.
    from mosaera_api.app_context._escalation import _is_convertible_park

    final = _convertible_final(["oracle_unverified"])
    final[channel] = value
    assert _is_convertible_park(final) is False


def test_convertible_non_dict_outcome_verdict_does_not_crash() -> None:
    # A malformed (non-dict) outcome_verdict must not raise (deny-by-default robustness).
    from mosaera_api.app_context._escalation import _is_convertible_park

    final = _convertible_final(["oracle_unverified"])
    final["outcome_verdict"] = ["not", "a", "dict"]
    assert isinstance(_is_convertible_park(final), bool)


# --- the sweep rung ---------------------------------------------------------------------------


def test_off_by_default_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _ctx()

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("must not open an author context when the knob is OFF")

    monkeypatch.setattr("mosaera_api.app_context._escalation._open_author_context", _boom)
    item = {"id": 1, "title": "t", "acceptance": "a"}
    sess: Any = _FakeSession("incomplete", _convertible_final())
    assert (
        ctx._try_close_named_gap(
            "p", item, "autonomous", "r", sess, _settings(disposition_gap_close=False)
        )
        is False
    )


def test_non_convertible_park_falls_through(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _ctx()

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a non-convertible park must never open an author context")

    monkeypatch.setattr("mosaera_api.app_context._escalation._open_author_context", _boom)
    item = {"id": 1, "title": "t", "acceptance": "a"}
    sess: Any = _FakeSession("incomplete", {"gate_decision": {"reasons": ["validation_failed"]}})
    assert ctx._try_close_named_gap("p", item, "autonomous", "r", sess, _settings()) is False


def test_guided_mode_never_disposes(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _ctx()
    monkeypatch.setattr(
        "mosaera_api.app_context._escalation._open_author_context",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no dispose off the autonomous path")),
    )
    item = {"id": 1, "title": "t", "acceptance": "a"}
    sess: Any = _FakeSession("incomplete", _convertible_final())
    assert ctx._try_close_named_gap("p", item, "guided", "r", sess, _settings()) is False


class _FakeWorkspace:
    def __init__(self) -> None:
        self.committed: str | None = None

    def commit_all(self, message: str) -> str:
        self.committed = message
        return "abc123def456"


def _wire_verified(
    monkeypatch: pytest.MonkeyPatch, ctx: Any, result: DispositionResult
) -> tuple[_FakeWorkspace, list[Any], list[Any]]:
    ws = _FakeWorkspace()
    monkeypatch.setattr(
        "mosaera_api.app_context._escalation._open_author_context",
        lambda *a, **k: (ws, object(), lambda _instr: None),
    )
    monkeypatch.setattr(
        "mosaera_api.app_context._escalation.close_oracle_gap", lambda *a, **k: result
    )
    opened: list[Any] = []
    advanced: list[Any] = []
    monkeypatch.setattr(ctx, "_maybe_open_item_mr", lambda pid, iid, rid: opened.append((pid, iid)))
    monkeypatch.setattr(ctx, "advance_project", lambda pid: advanced.append(pid))
    return ws, opened, advanced


def test_verified_ships_in_place(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _ctx()
    ctx.history.add_item(7, title="t", status="todo")
    result = DispositionResult(
        "verified", "proven", authored=("tests/test_acc.py",), green=True, mutation_caught=True
    )
    ws, opened, advanced = _wire_verified(monkeypatch, ctx, result)
    item = {"id": 7, "title": "Add sum", "acceptance": "add returns the sum"}
    sess: Any = _FakeSession("incomplete", _convertible_final())

    shipped = ctx._try_close_named_gap("p1", item, "autonomous", "run-9", sess, _settings())

    assert shipped is True
    assert ws.committed is not None and "Layer-2 verified" in ws.committed
    assert ctx.history.items[7]["status"] == "in_review"
    assert opened == [("p1", 7)] and advanced == ["p1"]
    assert any(e[1] == "disposition.verified-ship" for e in ctx.history.audits)


def test_unverified_stays_parked(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _ctx()
    ctx.history.add_item(7, title="t", status="todo")
    result = DispositionResult(
        "unverified", "a mutation survived", green=True, mutation_caught=False
    )
    ws, opened, advanced = _wire_verified(monkeypatch, ctx, result)
    item = {"id": 7, "title": "Add sum", "acceptance": "add returns the sum"}
    sess: Any = _FakeSession("incomplete", _convertible_final())

    shipped = ctx._try_close_named_gap("p1", item, "autonomous", "run-9", sess, _settings())

    assert shipped is False
    assert ws.committed is None  # never committed
    assert ctx.history.items[7]["status"] == "todo"  # unchanged — the honest park stands
    assert opened == [] and advanced == []
    assert any(e[1] == "disposition.not-verified" for e in ctx.history.audits)


def test_no_sandbox_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _ctx()
    monkeypatch.setattr(
        "mosaera_api.app_context._escalation._open_author_context", lambda *a, **k: None
    )
    item = {"id": 7, "title": "t", "acceptance": "a"}
    sess: Any = _FakeSession("incomplete", _convertible_final())
    assert ctx._try_close_named_gap("p1", item, "autonomous", "r", sess, _settings()) is False
    assert any(e[1] == "disposition.unavailable" for e in ctx.history.audits)


def test_verified_ship_holds_then_releases_the_project_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Red-team agent 3 F1: the whole author→verify→commit must run under the project mutex, and the
    # lock must be released before the sweep advances (advance_project re-reserves via launch_item).
    ctx = _ctx()
    ctx.history.add_item(7, title="t", status="todo")
    result = DispositionResult("verified", "proven", authored=("tests/test_acc.py",))
    ws, _opened, advanced = _wire_verified(monkeypatch, ctx, result)
    seen_reserved: list[bool] = []
    # Observe that the lock is HELD at commit time (inside the disposition body).
    orig_commit = ws.commit_all

    def _spy_commit(msg: str) -> str:
        seen_reserved.append("p1" in ctx.active_project_runs)
        return orig_commit(msg)

    monkeypatch.setattr(ws, "commit_all", _spy_commit)
    item = {"id": 7, "title": "Add sum", "acceptance": "add returns the sum"}
    sess: Any = _FakeSession("incomplete", _convertible_final())

    shipped = ctx._try_close_named_gap("p1", item, "autonomous", "run-9", sess, _settings())

    assert shipped is True
    assert seen_reserved == [True]  # lock was held during the commit
    assert "p1" not in ctx.active_project_runs  # released before advance
    assert advanced == ["p1"]


def test_busy_project_leaves_the_park(monkeypatch: pytest.MonkeyPatch) -> None:
    # If another run already owns the clone, disposition must not touch it — the park stands.
    ctx = _ctx()

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("must not open the clone when the project is busy")

    monkeypatch.setattr("mosaera_api.app_context._escalation._open_author_context", _boom)
    ctx.reserve_project("p1")  # a concurrent run holds the mutex
    item = {"id": 7, "title": "t", "acceptance": "a"}
    sess: Any = _FakeSession("incomplete", _convertible_final())
    assert ctx._try_close_named_gap("p1", item, "autonomous", "r", sess, _settings()) is False


def test_faulted_gap_closer_falls_through_and_releases(monkeypatch: pytest.MonkeyPatch) -> None:
    # Red-team agent 3 F3: a fault in close_oracle_gap must NOT propagate (it would swallow the
    # _after tail and silently stall the sweep) — it audits, returns False, and releases the lock.
    ctx = _ctx()
    ws = _FakeWorkspace()
    monkeypatch.setattr(
        "mosaera_api.app_context._escalation._open_author_context",
        lambda *a, **k: (ws, object(), lambda _i: None),
    )

    def _raise(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("index.lock")

    monkeypatch.setattr("mosaera_api.app_context._escalation.close_oracle_gap", _raise)
    item = {"id": 7, "title": "t", "acceptance": "a"}
    sess: Any = _FakeSession("incomplete", _convertible_final())
    assert ctx._try_close_named_gap("p1", item, "autonomous", "r", sess, _settings()) is False
    assert ws.committed is None
    assert "p1" not in ctx.active_project_runs  # released despite the fault
    assert any(e[1] == "disposition.faulted" for e in ctx.history.audits)


def test_mark_failure_does_not_advance(monkeypatch: pytest.MonkeyPatch) -> None:
    # Red-team agent 3 F4: a DB fault marking the item in_review after the commit must NOT advance
    # (a committed-but-unmarked item would be re-selected and delivered twice) — it returns False.
    ctx = _ctx()
    result = DispositionResult("verified", "proven", authored=("tests/test_acc.py",))
    _ws, opened, advanced = _wire_verified(monkeypatch, ctx, result)

    def _raise(_iid: int, **_kw: Any) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(ctx.history, "update_backlog_item", _raise)
    item = {"id": 7, "title": "t", "acceptance": "a"}
    sess: Any = _FakeSession("incomplete", _convertible_final())

    assert ctx._try_close_named_gap("p1", item, "autonomous", "r", sess, _settings()) is False
    assert advanced == [] and opened == []  # never advanced on a mark fault
    assert "p1" not in ctx.active_project_runs  # lock still released
    assert any(e[1] == "disposition.mark-failed" for e in ctx.history.audits)


# --- convertible class 2: the engine-blocked give-up rung behaviour (ADR-0075) ------------------


def _give_up_final() -> dict[str, Any]:
    return {
        "give_up_reason": "no convergence: failing count 2 -> 2",
        "stalled": False,
        "coder_escalated": False,
        "tests_modified": False,
        "outcome_verdict": None,
        "gate_decision": {"reasons": ["validation_failed", "reviewer_unknown"]},
        "authored_tests": ["tests/test_authored.py"],
        "proctor_edits": {},
        "test_output": "FAILED tests/test_authored.py::test_a - AssertionError\n1 failed\n",
    }


class _FakeSuiteOutcome:
    def __init__(self, passed: Any) -> None:
        self.passed = passed


def _wire_give_up(
    monkeypatch: pytest.MonkeyPatch,
    ctx: Any,
    result: DispositionResult,
    *,
    superseded: list[str] | None = None,
    suite_passed: Any = True,
) -> tuple[_FakeWorkspace, list[Any], list[Any]]:
    ws = _FakeWorkspace()
    monkeypatch.setattr(
        "mosaera_api.app_context._escalation._open_author_context",
        lambda *a, **k: (ws, object(), lambda _instr: None),
    )
    monkeypatch.setattr(
        "mosaera_api.app_context._escalation.close_oracle_gap", lambda *a, **k: result
    )
    monkeypatch.setattr(
        "mosaera_api.app_context._escalation.supersede_engine_tests",
        lambda _ws, trapping: list(superseded if superseded is not None else trapping),
    )
    monkeypatch.setattr(
        "mosaera_api.app_context._escalation.run_plan",
        lambda *a, **k: _FakeSuiteOutcome(suite_passed),
    )
    monkeypatch.setattr(
        "mosaera_api.app_context._escalation.resolve_plan", lambda *a, **k: object()
    )
    opened: list[Any] = []
    advanced: list[Any] = []
    monkeypatch.setattr(ctx, "_maybe_open_item_mr", lambda pid, iid, rid: opened.append((pid, iid)))
    monkeypatch.setattr(ctx, "advance_project", lambda pid: advanced.append(pid))
    return ws, opened, advanced


def test_give_up_class_ships_with_supersession(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _ctx()
    ctx.history.add_item(9, title="t", status="todo")
    result = DispositionResult("verified", "proven", authored=("tests/test_fresh.py",))
    ws, opened, advanced = _wire_give_up(monkeypatch, ctx, result)
    item = {"id": 9, "title": "Add sum", "acceptance": "adds correctly"}
    sess: Any = _FakeSession("incomplete", _give_up_final())

    shipped = ctx._try_close_named_gap("p1", item, "autonomous", "run-2", sess, _settings())

    assert shipped is True
    assert ws.committed is not None
    assert "engine_blocked_give_up" in ws.committed  # the class is named in the commit
    assert "tests/test_authored.py" in ws.committed  # the superseded file is recorded
    assert ctx.history.items[9]["status"] == "in_review"
    assert opened == [("p1", 9)] and advanced == ["p1"]
    note = next(e[2] for e in ctx.history.audits if e[1] == "disposition.verified-ship")
    assert "superseded" in note and "tests/test_authored.py" in note


def test_give_up_class_denied_when_suite_not_green(monkeypatch: pytest.MonkeyPatch) -> None:
    # The post-supersession whole-suite check: a deleted engine test another test imported breaks
    # the tree -> deny, park stands.
    ctx = _ctx()
    ctx.history.add_item(9, title="t", status="todo")
    result = DispositionResult("verified", "proven", authored=("tests/test_fresh.py",))
    ws, opened, advanced = _wire_give_up(monkeypatch, ctx, result, suite_passed=False)
    item = {"id": 9, "title": "t", "acceptance": "a"}
    sess: Any = _FakeSession("incomplete", _give_up_final())

    assert ctx._try_close_named_gap("p1", item, "autonomous", "r", sess, _settings()) is False
    assert ws.committed is None  # never committed
    assert ctx.history.items[9]["status"] == "todo"
    assert opened == [] and advanced == []
    assert any(e[1] == "disposition.suite-not-green" for e in ctx.history.audits)


def test_give_up_class_denied_when_nothing_on_disk_to_supersede(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The trapping files are absent from the reopened clone (raced/reset tree) -> deny-by-default.
    ctx = _ctx()
    result = DispositionResult("verified", "proven", authored=("tests/test_fresh.py",))
    ws, _opened, _advanced = _wire_give_up(monkeypatch, ctx, result, superseded=[])
    item = {"id": 9, "title": "t", "acceptance": "a"}
    sess: Any = _FakeSession("incomplete", _give_up_final())

    assert ctx._try_close_named_gap("p1", item, "autonomous", "r", sess, _settings()) is False
    assert ws.committed is None
    assert any(e[1] == "disposition.no-trapping-on-disk" for e in ctx.history.audits)


def test_oracle_unverified_class_never_supersedes(monkeypatch: pytest.MonkeyPatch) -> None:
    # Class 1 must not touch any test file and must not run the whole-suite check.
    ctx = _ctx()
    ctx.history.add_item(7, title="t", status="todo")
    result = DispositionResult("verified", "proven", authored=("tests/test_acc.py",))
    ws, _opened, _advanced = _wire_verified(monkeypatch, ctx, result)

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("class 1 must never supersede")

    monkeypatch.setattr("mosaera_api.app_context._escalation.supersede_engine_tests", _boom)
    item = {"id": 7, "title": "t", "acceptance": "a"}
    sess: Any = _FakeSession("incomplete", _convertible_final())

    assert ctx._try_close_named_gap("p1", item, "autonomous", "r", sess, _settings()) is True
    assert "oracle_unverified" in (ws.committed or "")
    assert "Superseded" not in (ws.committed or "")


def test_give_up_class_requires_a_held_out_tester(monkeypatch: pytest.MonkeyPatch) -> None:
    # RED-TEAM R1: class 2 deletes the only in-tree oracle + has a higher wrong-code prior, so it
    # may ONLY run with an INDEPENDENT tester. When the critic (the held-out author model) equals
    # the coder model, there is no independence → park stands, before any clone work.
    ctx = _ctx()

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("must not open the clone without a held-out tester")

    monkeypatch.setattr("mosaera_api.app_context._escalation._open_author_context", _boom)
    same = _settings(critic_model="qwen3-coder:30b", coder_model="qwen3-coder:30b")
    assert same.held_out_ok() is False
    item = {"id": 9, "title": "t", "acceptance": "a"}
    sess: Any = _FakeSession("incomplete", _give_up_final())
    assert ctx._try_close_named_gap("p1", item, "autonomous", "r", sess, same) is False
    assert any(e[1] == "disposition.no-held-out-tester" for e in ctx.history.audits)
