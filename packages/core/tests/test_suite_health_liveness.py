"""LIVENESS: do the two new controls actually FIRE?

Not a unit test with stubs. Every measurement here is a REAL pytest execution in a REAL sandbox
against a REAL git repo, and the count is taken by having the fixture repo's own test append a line
to a file OUTSIDE the workspace. Nothing is mocked, so nothing can pass because a mock said so.

This exists because this repo keeps finding controls that were built, shipped and never fired —
ADR-0025's behaviour floor (never matches a src-layout package), QMB's cost dimension (no price
table, always $0.00), `escalate_arm` (unreachable from a no-progress park), and the code-evidence
fail-open that hid whether grounding reached production at all. A test that asserts "the function
returns the right dict" would have passed in every one of those cases.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from git import Repo
from mosaera_core.graph import _baseline as bl
from mosaera_core.sandbox import SubprocessSandbox
from mosaera_core.tools.repo import Workspace
from mosaera_memory import MemoryStore

_DB_URL = os.environ.get("MOSAERA_TEST_DB_URL")
requires_db = pytest.mark.requires_db


@pytest.fixture
def counter(tmp_path: Path) -> Path:
    """Where the fixture repo's test records that it RAN. Outside the workspace on purpose — a
    file inside it would change the tree hash and defeat the very cache under test."""
    return tmp_path / "suite-runs.log"


@pytest.fixture
def repo(tmp_path: Path, counter: Path) -> Workspace:
    root = tmp_path / "clone"
    (root / "tests").mkdir(parents=True)
    (root / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    # The suite records each execution, then asserts on the source file. Both halves matter: the
    # append proves it ran, the assert lets us make it go red by editing src.py.
    (root / "tests" / "test_value.py").write_text(
        "from pathlib import Path\n"
        "import sys\n"
        f"sys.path.insert(0, {str(root)!r})\n"
        f"Path({str(counter)!r}).open('a').write('ran\\n')\n"
        "def test_value():\n"
        "    import src\n"
        "    assert src.VALUE == 1\n",
        encoding="utf-8",
    )
    r = Repo.init(root, initial_branch="main")
    with r.config_writer() as cw:
        cw.set_value("user", "name", "T")
        cw.set_value("user", "email", "t@example.com")
    # Mirror what `clone_project` writes (clone.py:97-99). Without it a suite run leaves untracked
    # __pycache__/.pytest_cache and the tree reads DIRTY — so the fixture would test a repo shape
    # the product never produces, and the durable key would never be taken.
    (root / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (root / ".git" / "info" / "exclude").write_text(
        "\n__pycache__/\n*.pyc\n.pytest_cache/\n.mypy_cache/\n.ruff_cache/\n"
        ".coverage\n.venv/\n/node_modules/\n/.mosaera/\n",
        encoding="utf-8",
    )
    r.git.add("-A")
    r.index.commit("green")
    r.git.checkout("-B", "mosaera/item-1")
    return Workspace(root=root, run_id="run-1", branch="mosaera/item-1")


@pytest.fixture
def store() -> MemoryStore:
    s = MemoryStore.from_url(_DB_URL)  # type: ignore[arg-type]
    s.init()
    return s


def _ctx(ws: Workspace, store: MemoryStore, project_id: str) -> Any:
    return SimpleNamespace(
        workspace=ws,
        sandbox=SubprocessSandbox(ws.root),
        test_cmd=None,
        memory=store,
        project_id=project_id,
        run_id="run-1",
        settings=SimpleNamespace(sandbox_install=False, sandbox_install_timeout=None),
    )


def _runs(counter: Path) -> int:
    return len(counter.read_text(encoding="utf-8").splitlines()) if counter.exists() else 0


@requires_db
def test_the_verdict_cache_fires_and_saves_a_real_suite_run(
    repo: Workspace, store: MemoryStore, counter: Path
) -> None:
    """Control 1. The suite must run once for a tree and NEVER again for that same tree."""
    from mosaera_memory.models import Project

    pid = f"proj-live-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "P", str(repo.root))
    ctx = _ctx(repo, store, pid)

    first = bl.run_start_baseline(ctx)
    # A DELTA, not an absolute — same reasoning as the offline twins in test_suite_baseline.py: a
    # cache MISS now makes two sandbox invocations (the suite, plus one `pytest --collect-only`
    # checking our reading of the repo's pytest config against pytest's own answer), and the seed
    # suite's counter increments on COLLECTION too. Both are keyed to the tree; the property this
    # control exists for is unchanged below: an UNCHANGED tree costs zero.
    per_miss = _runs(counter)
    assert first["suite_baseline"]["green"] is True
    assert per_miss > 0, "the suite did not actually execute"
    # The CONTENT key, not `Workspace.tree_hash` — the distinction this suite exists to pin.
    row = store.suite_health(pid, bl._content_key(ctx))
    assert row is not None and row["verdict"] == "pass", "the verdict was not recorded"

    second = bl.run_start_baseline(ctx)
    assert second["suite_baseline"]["green"] is True
    assert _runs(counter) == per_miss, (
        "CACHE DID NOT FIRE — a sandbox invocation happened on an unchanged tree"
    )

    # …and a real edit invalidates it: the tree hash moves, so the answer no longer applies.
    (repo.root / "src.py").write_text("VALUE = 1  # touched\n", encoding="utf-8")
    third = bl.run_start_baseline(ctx)
    assert _runs(counter) == 2 * per_miss, (
        "a MOVED tree reused a verdict that no longer describes it"
    )
    assert third["suite_baseline"]["green"] is True

    with store.session() as s, s.begin():
        s.delete(s.get(Project, pid))


@requires_db
def test_the_cache_survives_a_REAL_run_boundary(
    repo: Workspace, store: MemoryStore, counter: Path
) -> None:
    """The case the first cut got wrong, caught on the live instance by one log line.

    Two calls in one process prove nothing: the key was `Workspace.tree_hash`, which hashes
    `(path, size, mtime_ns)` and says in its own docstring that it is "run/process-scoped". A real
    run WRITES files and the next run's `git reset --hard` rewrites them, so identical content got a
    different fingerprint and the verdict was recorded and never reused — every run re-measured,
    which is the cost this control exists to remove.

    So this simulates the boundary: measure, dirty the tree the way a run does, reset the way run
    start does, and only THEN ask again.
    """
    from mosaera_memory.models import Project

    pid = f"proj-live-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "P", str(repo.root))
    ctx = _ctx(repo, store, pid)

    bl.run_start_baseline(ctx)
    per_miss = _runs(counter)  # suite + the collect-only drift check — see the sibling test
    assert per_miss > 0

    # What a run does: write files. Then what the NEXT run's start does: sweep them.
    (repo.root / "scratch_edit.py").write_text("tmp = 1\n", encoding="utf-8")
    (repo.root / "src.py").write_text("VALUE = 1  # edited by a run\n", encoding="utf-8")
    r = Repo(repo.root)
    r.git.reset("--hard", "HEAD")
    r.git.clean("-fd")

    bl.run_start_baseline(ctx)
    assert _runs(counter) == per_miss, (
        "CACHE MISSED ACROSS A RUN BOUNDARY — the key is not content-addressed, so every run "
        "re-measures a tree it already has a verdict for"
    )

    with store.session() as s, s.begin():
        s.delete(s.get(Project, pid))


@requires_db
def test_the_delivery_backstop_fires_on_a_tree_that_changed_after_validation(
    repo: Workspace, store: MemoryStore, counter: Path
) -> None:
    """Control 2. A green verdict, then a real edit that breaks the suite, then delivery."""
    import mosaera_core.graph.nodes_deliver as nd
    from mosaera_memory.models import Project

    pid = f"proj-live-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "P", str(repo.root))
    ctx = _ctx(repo, store, pid)

    verified_tree = bl._stat_key(ctx)
    state = {"tests_passed": True, "verified_tree": verified_tree, "approved": True, "diff": "d"}

    # An unchanged tree must cost NOTHING — the property that makes the backstop affordable.
    assert bl.delivery_check(ctx, state) == {}
    assert _runs(counter) == 0

    # Now the tree changes AFTER validation, the way hygiene's autofix does — and breaks the suite.
    (repo.root / "src.py").write_text("VALUE = 999\n", encoding="utf-8")
    check = bl.delivery_check(ctx, state)

    assert _runs(counter) == 1, "BACKSTOP DID NOT FIRE — no suite ran on the changed tree"
    assert check["verdict"] == "failed"
    assert any("test_value" in t for t in check["failing"])

    green_tip = Repo(repo.root).head.commit.hexsha
    deliver_ctx = SimpleNamespace(
        workspace=repo,
        run_id="run-1",
        source="local",
        project_id=pid,
        item_id=1,
        memory=None,
        # The measurement's settings must be present: without them `take_suite_baseline` cannot
        # run, correctly declines to call the tree red, and delivery proceeds — which is the right
        # behaviour on an unmeasurable tree and a WRONG fixture for proving the backstop fires.
        settings=SimpleNamespace(
            reports_dir=repo.root.parent / "reports",
            sandbox_install=False,
            sandbox_install_timeout=None,
        ),
        sandbox=ctx.sandbox,
        test_cmd=None,
    )
    deliver_state: Any = {**state, "task": "t"}
    out = nd.deliver_node(deliver_ctx, deliver_state)  # type: ignore[arg-type]

    r = Repo(repo.root)
    assert out["commit_sha"] == "", "a tree that fails its own suite was committed"
    assert out["approved"] is False
    assert r.commit("mosaera/quarantine-run-1"), "the work was DESTROYED instead of quarantined"
    assert r.commit("mosaera/item-1").hexsha == green_tip, "the red entered the stack"
    assert r.active_branch.name == "mosaera/item-1"

    with store.session() as s, s.begin():
        s.delete(s.get(Project, pid))
