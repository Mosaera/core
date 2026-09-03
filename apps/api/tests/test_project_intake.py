"""Project intake: the clone that must happen before onboarding can begin, and its recovery.

Split from `test_api.py`, which is at its grandfathered line ratchet. These tests share a subject
rather than a fixture: a failed clone used to be TERMINAL — `run_intake` parks the project at
status "draft" with an error and nothing anywhere restarted it, so a typo'd repo URL or a private
repo (the case the New-project page tells you to fix by connecting GitLab) left a permanently dead
project whose only recovery was creating another one.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, cast

import pytest
from mosaera_memory import MemoryStore
from test_api import _client_with, _FakeProjectMemory


def test_a_failed_intake_can_be_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """The dead end this closes: `run_intake` parks a failed clone at status "draft" with an error
    and NOTHING restarts it — not even setting the GitLab token, which is the recovery the
    New-project page advertises for a private repo. The project was terminal."""
    started: list[str] = []
    monkeypatch.setattr(
        "mosaera_api.routes.projects.start_intake", lambda mem, pid, *a: started.append(pid)
    )
    mem = _FakeProjectMemory()
    c = _client_with(mem)
    pid = c.post("/api/projects", json={"name": "P", "source_repo": "s", "goal": "g"}).json()["id"]
    started.clear()

    # A project that is merely STARTING has nothing to retry — retrying would run a second clone
    # underneath the one in flight.
    assert c.post(f"/api/projects/{pid}/intake/retry").status_code == 409
    assert started == []

    mem.update_project(pid, status="draft", error="intake failed: repository does not exist")
    r = c.post(f"/api/projects/{pid}/intake/retry")
    assert r.status_code == 202
    assert started == [pid]  # the SAME project, re-cloned in place
    # The RESPONSE is what the UI renders next, so it must already show the retry underway —
    # returning the failed row left the operator staring at the error they just acted on.
    assert r.json()["status"] == "drafting"
    assert r.json()["error"] == ""
    assert c.post("/api/projects/nope/intake/retry").status_code == 404


def test_a_retried_intake_does_not_carry_the_old_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """`error` is what distinguishes a failed project from a starting one, so it must be cleared as
    the retry begins — otherwise the UI keeps rendering the failure while the clone is running."""
    from mosaera_api.projects import run_intake

    # The fake implements the slice `run_intake` touches, deliberately and not the whole protocol —
    # the point of the test is the ORDER of two writes around a failing clone.
    mem = cast(MemoryStore, _FakeProjectMemory())
    mem.create_project("p1", "P", "src")
    mem.update_project("p1", status="draft", error="intake failed: boom")
    seen: list[str] = []

    def _clone(*_a: Any, **_k: Any) -> None:
        # Snapshot the project AS THE CLONE BEGINS — that is the moment the old error must already
        # be gone, not after a retry happens to succeed.
        seen.append(str(mem.project_detail("p1")))
        raise RuntimeError("still broken")

    monkeypatch.setattr("mosaera_api.projects.clone_project", _clone)
    run_intake(mem, "p1", "src")
    assert "intake failed: boom" not in seen[0]  # cleared BEFORE the clone was attempted
    detail = cast(dict[str, Any], mem.project_detail("p1"))
    assert detail["error"] == "intake failed: still broken"


# --- local-first projects (ADR-0123) ---------------------------------------------------


def test_a_project_can_be_created_with_no_source_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Lovable-shaped flow: name it, and Mosaera gives it a repository. Requiring a source is
    also why nothing on an instance could ever exercise repository creation — every project
    already had a repository."""
    started: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "mosaera_api.routes.projects.start_intake",
        lambda mem, pid, source: started.append((pid, source)),
    )
    c = _client_with(_FakeProjectMemory())
    r = c.post("/api/projects", json={"name": "Ledger", "goal": "g"})

    assert r.status_code == 201
    assert started and started[0][1] == "", "intake is told there is no upstream, explicitly"


def test_intake_initializes_instead_of_cloning_when_there_is_no_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Which path runs is the whole decision. Cloning a blank source would resolve `Path("")` to
    the server's working directory, so this must reach `init_project` and never `clone_project`."""
    from mosaera_api import projects as proj

    calls: list[str] = []

    def _no_clone(*a: Any, **k: Any) -> Any:  # pragma: no cover - must never run
        raise AssertionError("a project with no upstream must never take the clone path")

    class _WS:
        branch = "mosaera/project-p1"
        root = Path(tempfile.gettempdir()) / "mosaera-test-ws"

    monkeypatch.setattr(proj, "clone_project", _no_clone)

    def _init(projects_dir: Any, pid: str) -> Any:
        calls.append(pid)
        return _WS()

    monkeypatch.setattr(proj, "init_project", _init)
    monkeypatch.setattr(proj, "build_overview", lambda *a, **k: "")
    monkeypatch.setattr(proj, "open_intake", lambda *a, **k: None, raising=False)

    mem = _FakeProjectMemory()
    cast(Any, mem).create_project("p1", "P", "", "g")
    proj.run_intake(cast(MemoryStore, mem), "p1", "")

    assert calls == ["p1"]
