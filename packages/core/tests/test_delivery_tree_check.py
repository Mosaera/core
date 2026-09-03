"""The tree that ships must be the tree that passed.

`tests_passed` described the tree the `test` node measured and lived in a channel nothing
invalidated. Two paths changed the tree before `commit_all` — hygiene's autofix wrote and routed on
without re-testing (every Python delivery), and the give-up diversion reached the gate carrying a
verdict from before the coder's last writes — and nothing ran after the commit at all.

Because item branches are cut at the clone's current tip, a red commit is inherited by every later
item, and the run-start baseline then reports those failures as "already failing" — blaming nobody.
So a red tree is QUARANTINED: the work survives on its own branch, the tip stays green.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from git import Repo
from mosaera_core.graph import _baseline as bl
from mosaera_core.tools.repo import Workspace


@pytest.fixture
def repo(tmp_path: Path) -> Workspace:
    root = tmp_path / "clone"
    root.mkdir()
    r = Repo.init(root, initial_branch="main")
    with r.config_writer() as cw:
        cw.set_value("user", "name", "T")
        cw.set_value("user", "email", "t@example.com")
    (root / "kept.py").write_text("x = 1\n", encoding="utf-8")
    r.index.add(["kept.py"])
    r.index.commit("green tip")
    r.git.checkout("-B", "mosaera/item-1")
    return Workspace(root=root, run_id="run-1", branch="mosaera/item-1")


def test_quarantine_preserves_the_work_and_leaves_the_tip_green(repo: Workspace) -> None:
    """Asserted on GIT STATE, not on a message: the whole claim is about which commit the next
    item will be cut from."""
    green_tip = Repo(repo.root).head.commit.hexsha
    (repo.root / "broken.py").write_text("y = 2\n", encoding="utf-8")

    sha = repo.commit_onto("mosaera/quarantine-run-1", "quarantined")

    r = Repo(repo.root)
    assert sha and sha != green_tip
    # The work exists…
    assert "broken.py" in r.git.show("--name-only", "--format=", "mosaera/quarantine-run-1")
    # …the tip every later item is cut from did NOT move…
    assert r.commit("mosaera/item-1").hexsha == green_tip
    # …and the clone is back on the branch it started on, so the next run is not re-targeted.
    assert r.active_branch.name == "mosaera/item-1"


def _ctx(ws: Workspace, tree: str, *, health: Any = None) -> Any:
    return SimpleNamespace(
        # `evidence_hash`, not `tree_hash`: ADR-0106's pin moved onto the git-sourced evidence
        # listing when ADR-0108's successor unified the two (a walk-based hash cannot see
        # `src/.mosaera/`, `htmlcov/` etc., which the delivery path commits). Stubbing the wrong
        # one makes `_stat_key` return "" and `delivery_check` silently answer `{}` — this fixture
        # did exactly that, which is why it is spelled out here.
        workspace=SimpleNamespace(root=ws.root, evidence_hash=lambda: tree, tree_hash=lambda: tree),
        sandbox=object(),
        test_cmd=None,
        memory=health,
        project_id="p1",
        run_id="run-1",
        settings=SimpleNamespace(sandbox_install=True, sandbox_install_timeout=None),
    )


def _stub_suite(monkeypatch: pytest.MonkeyPatch, *, passed: bool, output: str) -> list[int]:
    calls: list[int] = []

    def _run(*a: Any, **k: Any) -> Any:
        calls.append(1)
        return SimpleNamespace(passed=passed, output=output)

    monkeypatch.setattr(bl, "resolve_plan", lambda *a, **k: SimpleNamespace(as_dict=dict))
    monkeypatch.setattr(bl, "run_plan", _run)
    return calls


def test_an_unchanged_tree_is_not_re_verified(
    repo: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordinary case, and the reason the backstop is affordable at all."""
    calls = _stub_suite(monkeypatch, passed=True, output="1 passed")
    state = {"tests_passed": True, "verified_tree": "tree-aaa"}

    assert bl.delivery_check(_ctx(repo, "tree-aaa"), state) == {}
    assert calls == []


def test_a_changed_tree_is_re_verified_and_a_red_one_is_named(
    repo: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_suite(monkeypatch, passed=False, output="FAILED tests/test_a.py::t - x\n1 failed")
    state = {"tests_passed": True, "verified_tree": "tree-aaa"}

    check = bl.delivery_check(_ctx(repo, "tree-bbb"), state)

    assert check["verdict"] == "failed"
    assert check["failing"] == ["tests/test_a.py::t"]
    reason = bl.stale_tree_reason(check, "mosaera/quarantine-run-1")
    assert "changed after it was validated" in reason
    assert "mosaera/quarantine-run-1" in reason
    assert "tests/test_a.py::t" in reason


def test_a_changed_tree_that_still_passes_delivers_normally(
    repo: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_suite(monkeypatch, passed=True, output="9 passed")
    check = bl.delivery_check(_ctx(repo, "tree-bbb"), {"tests_passed": True, "verified_tree": "a"})
    assert check["verdict"] == "pass"


def test_it_never_manufactures_a_verdict_where_none_existed(
    repo: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`deliver_unverified` and "no honest validation possible" both mean there is no green to
    invalidate. Inventing one here would be worse than the gap it closes."""
    calls = _stub_suite(monkeypatch, passed=False, output="1 failed")

    assert bl.delivery_check(_ctx(repo, "tree-bbb"), {"tests_passed": None}) == {}
    assert bl.delivery_check(_ctx(repo, "tree-bbb"), {"tests_passed": False}) == {}
    assert calls == []


def test_an_unreadable_recheck_does_not_refuse_delivery(
    repo: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A validator whose output could not be parsed has not shown the tree to be broken."""
    _stub_suite(monkeypatch, passed=False, output="Segmentation fault")
    check = bl.delivery_check(_ctx(repo, "tree-bbb"), {"tests_passed": True, "verified_tree": "a"})
    assert check["verdict"] == "unknown"


# --- gap A: hygiene rewrote the tree, so the green behind us describes a tree that is gone -------


def test_autofix_that_rewrote_the_tree_routes_back_to_test() -> None:
    """`ruff --select F --fix` removes "unused" imports, which can change import side effects — so
    hygiene's writes are not guaranteed behaviour-preserving, and it used to route straight on to
    scan/review/gate/deliver. Asserted on the ROUTE: a message assertion would pass while the run
    shipped an unmeasured tree anyway."""
    from mosaera_core.graph.nodes_impl import route_after_hygiene

    ctx = SimpleNamespace(
        settings=SimpleNamespace(hygiene_gate_enabled=True, hygiene_max_fixes=3), max_iter=3
    )
    assert route_after_hygiene(ctx, {"hygiene_rewrote": True}) == "test"  # type: ignore[arg-type]


def test_the_re_test_loop_terminates() -> None:
    """`autofix` is idempotent, so the second visit reports no change and the run proceeds. Without
    that, hygiene→test→hygiene would spin the suite forever."""
    from mosaera_core.graph.nodes_impl import route_after_hygiene

    ctx = SimpleNamespace(
        settings=SimpleNamespace(hygiene_gate_enabled=True, hygiene_max_fixes=3), max_iter=3
    )
    assert route_after_hygiene(ctx, {"hygiene_rewrote": False}) == "scan"  # type: ignore[arg-type]


def test_residual_findings_still_win_over_the_re_test() -> None:
    """A rewrite plus residual lint/type findings is still the coder's problem first — re-testing
    a tree we already know needs another edit just burns a suite run."""
    from mosaera_core.graph.nodes_impl import route_after_hygiene

    ctx = SimpleNamespace(
        settings=SimpleNamespace(hygiene_gate_enabled=True, hygiene_max_fixes=3), max_iter=3
    )
    state = {"hygiene_rewrote": True, "hygiene_findings": ["F401 x"], "iteration": 0}
    assert route_after_hygiene(ctx, state) == "hygiene_fix"  # type: ignore[arg-type]


# --- the refusal must reach the DURABLE record, not just the report -----------------------------


def test_a_refused_delivery_is_recorded_as_not_approved(
    repo: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A quarantined run must not read as a delivery that happened. `persist_run` derives both
    `status` and `validation_status` from the state it is handed, so the refusal has to ride into
    it — otherwise the record says APPROVED with a commit_sha of "" and nobody can tell."""
    import mosaera_core.graph.nodes_deliver as nd

    recorded: dict[str, Any] = {}
    monkeypatch.setattr(nd, "write_report", lambda *a, **k: "report.md")
    monkeypatch.setattr(
        nd, "persist_run", lambda mem, settings, rid, **kw: recorded.update(kw["state"])
    )
    monkeypatch.setattr(
        nd, "delivery_check", lambda ctx, state: {"verdict": "failed", "failing": ["t.py::x"]}
    )

    ctx = SimpleNamespace(
        workspace=repo,
        run_id="run-1",
        source="local",
        project_id="p1",
        item_id=1,
        memory=object(),
        settings=SimpleNamespace(reports_dir="reports"),
    )
    out = nd.deliver_node(ctx, {"approved": True, "diff": "d", "task": "t"})  # type: ignore[arg-type]

    assert out["commit_sha"] == ""  # nothing landed on the item branch
    assert out["approved"] is False  # …and the run does not claim it did
    assert "mosaera/quarantine-run-1" in out["quarantine_branch"]
    assert recorded["approved"] is False  # the DURABLE record agrees
    assert "t.py::x" in recorded["delivery_refused"]
    # The work is on the quarantine branch and the item branch is untouched.
    assert Repo(repo.root).commit("mosaera/quarantine-run-1")


def test_a_green_delivery_is_untouched(repo: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    """The ordinary path must behave exactly as before — this control may not change delivery."""
    import mosaera_core.graph.nodes_deliver as nd

    monkeypatch.setattr(nd, "write_report", lambda *a, **k: "report.md")
    monkeypatch.setattr(nd, "delivery_check", lambda ctx, state: {})

    (repo.root / "new.py").write_text("z = 3\n", encoding="utf-8")
    ctx = SimpleNamespace(
        workspace=repo,
        run_id="run-1",
        source="local",
        project_id="p1",
        item_id=1,
        memory=None,
        settings=SimpleNamespace(reports_dir="reports"),
    )
    out = nd.deliver_node(ctx, {"approved": True, "diff": "d", "task": "t"})  # type: ignore[arg-type]

    assert out["commit_sha"]  # it committed
    assert "approved" not in out and "quarantine_branch" not in out
    assert Repo(repo.root).active_branch.name == "mosaera/item-1"
