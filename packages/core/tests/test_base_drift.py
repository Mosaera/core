"""ADR-0102 slice D: the base-drift check before the item-branch cut.

A stacked item branch is cut from the project clone's current tip; if a merged MR
advanced the remote base past that tip, the next item's diff is wrong. These tests
drive every classification against a real local "remote" — pure git, no network.
"""

from pathlib import Path

import pytest
from git import Repo
from mosaera_core.tools.repo import (
    Workspace,
    branch_standing,
    check_base_drift,
    clone_project,
    local_branches,
    remote_synced,
)
from mosaera_core.tools.repo.clone import reset_clone_to_remote


def _commit(repo: Repo, path: Path, name: str, text: str) -> None:
    (path / name).write_text(text, encoding="utf-8")
    repo.index.add([name])
    repo.index.commit(f"add {name}")


@pytest.fixture()
def remote(tmp_path: Path) -> Path:
    src = tmp_path / "remote"
    src.mkdir()
    repo = Repo.init(src, initial_branch="main")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "T")
        cw.set_value("user", "email", "t@local")
    _commit(repo, src, "a.txt", "one\n")
    return src


@pytest.fixture()
def clone(remote: Path, tmp_path: Path) -> Path:
    ws = clone_project(str(remote), tmp_path / "projects", "p1")
    with ws.repo.config_writer() as cw:
        cw.set_value("user", "name", "T")
        cw.set_value("user", "email", "t@local")
    return ws.root


def test_in_sync_when_remote_base_is_contained(clone: Path) -> None:
    assert check_base_drift(clone, "main").kind == "in_sync"


def test_fast_forward_when_strictly_behind_moves_the_tip(remote: Path, clone: Path) -> None:
    rrepo = Repo(remote)
    _commit(rrepo, remote, "b.txt", "two\n")
    status = check_base_drift(clone, "main")
    assert status.kind == "fast_forwarded"
    # The local tip now IS the remote base — the next item stacks on reality.
    crepo = Repo(clone)
    assert crepo.head.commit.hexsha == rrepo.head.commit.hexsha


def test_diverged_fails_closed_and_cuts_nothing(remote: Path, clone: Path) -> None:
    rrepo = Repo(remote)
    _commit(rrepo, remote, "b.txt", "remote-side\n")
    crepo = Repo(clone)
    before_branch = crepo.active_branch.name
    before_sha = crepo.head.commit.hexsha
    _commit(crepo, clone, "c.txt", "local-side\n")
    status = check_base_drift(clone, "main")
    assert status.kind == "diverged"
    assert "each carry commits the other lacks" in status.detail
    # The check classifies; it never resets or cuts on divergence.
    assert crepo.active_branch.name == before_branch
    assert crepo.head.commit.hexsha != before_sha  # the local commit is untouched


def test_missing_remote_branch_is_no_remote_base(clone: Path) -> None:
    assert check_base_drift(clone, "does-not-exist").kind == "no_remote_base"


def test_unreachable_remote_is_a_warning_not_a_wall(remote: Path, clone: Path) -> None:
    crepo = Repo(clone)
    crepo.remotes.origin.set_url(str(remote / "gone"))
    assert check_base_drift(clone, "main").kind == "unreachable"
    crepo.delete_remote(crepo.remotes.origin)
    assert check_base_drift(clone, "main").kind == "unreachable"


def test_base_derived_from_origin_head_when_not_given(clone: Path) -> None:
    # base=None derives the same default project_base does (origin/HEAD → main).
    assert check_base_drift(clone).kind == "in_sync"


def _ws(clone: Path) -> Workspace:
    return Workspace(root=clone, run_id="t", branch=Repo(clone).active_branch.name)


def test_remote_synced_reads_the_truth(remote: Path, clone: Path) -> None:
    # ADR-0102 slice H: the clone's project branch was never pushed → provably False.
    assert remote_synced(_ws(clone)) is False
    crepo = Repo(clone)
    crepo.git.push("origin", f"{crepo.active_branch.name}:{crepo.active_branch.name}")
    assert remote_synced(_ws(clone)) is True
    # A new local commit makes the remote tip stale again.
    (clone / "z.txt").write_text("z\n", encoding="utf-8")
    crepo.index.add(["z.txt"])
    crepo.index.commit("local only")
    assert remote_synced(_ws(clone)) is False


def test_remote_synced_unknown_is_none_never_a_verdict(remote: Path, clone: Path) -> None:
    crepo = Repo(clone)
    crepo.remotes.origin.set_url(str(remote / "gone"))
    assert remote_synced(_ws(clone)) is None
    crepo.delete_remote(crepo.remotes.origin)
    assert remote_synced(_ws(clone)) is None


def test_local_branches_lists_remote_targets_and_hides_mosaera_branches(
    remote: Path, clone: Path
) -> None:
    # A1: the target-branch picker reads the LOCAL clone (no token). Remote-tracking refs are
    # the human targets; Mosaera's own mosaera/* branches are never a target and are hidden.
    rrepo = Repo(remote)
    rrepo.git.branch("develop")  # a second real branch on the remote
    Repo(clone).git.fetch("origin")
    names = [b["name"] for b in local_branches(_ws(clone))]
    assert "main" in names and "develop" in names
    assert not any(n.startswith("mosaera/") for n in names)  # the clone's own branch is hidden
    # `main` (origin/HEAD default) sorts first and is marked protected/default.
    assert names[0] == "main"
    assert next(b for b in local_branches(_ws(clone)) if b["name"] == "main")["protected"] is True


def test_branch_standing_counts_ahead_and_proves_in_sync(remote: Path, clone: Path) -> None:
    """The half that IS computable offline: ahead, from objects the clone already holds."""
    crepo = Repo(clone)
    crepo.git.push("origin", f"{crepo.active_branch.name}:main")
    assert branch_standing(_ws(clone))["state"] == "in_sync"

    _commit(crepo, clone, "b.txt", "two\n")
    st = branch_standing(_ws(clone))
    assert st["state"] == "ahead" and st["ahead"] == 1 and st["behind"] == 0


def test_branch_standing_admits_a_behind_it_cannot_count(remote: Path, clone: Path) -> None:
    """The load-bearing honesty case.

    The remote base moves on; this function may NOT fetch (a fetch mutates .git and races a live
    run), so the clone does not hold the new commit and cannot count the gap. It must say
    "behind by an unknown amount" — not 0, not silence, and above all not in_sync.
    """
    crepo = Repo(clone)
    crepo.git.push("origin", f"{crepo.active_branch.name}:main")
    rrepo = Repo(remote)
    _commit(rrepo, remote, "c.txt", "three\n")  # the remote base advances, unseen by the clone

    st = branch_standing(_ws(clone))
    assert st["state"] == "behind_unknown"
    assert st["behind"] is None  # provably behind, honestly uncountable
    assert st["state"] != "in_sync"


def test_branch_standing_counts_behind_once_the_objects_are_local(
    remote: Path, clone: Path
) -> None:
    # After an unrelated fetch the clone HOLDS the remote commit, so the gap becomes countable.
    crepo = Repo(clone)
    crepo.git.push("origin", f"{crepo.active_branch.name}:main")
    rrepo = Repo(remote)
    _commit(rrepo, remote, "c.txt", "three\n")
    crepo.git.fetch("origin", "main")

    st = branch_standing(_ws(clone))
    assert st["state"] == "behind" and st["behind"] == 1


def test_branch_standing_is_unknown_never_a_verdict(remote: Path, clone: Path) -> None:
    crepo = Repo(clone)
    crepo.delete_remote(crepo.remotes.origin)
    assert branch_standing(_ws(clone))["state"] in {"no_remote", "unknown"}


# --- reset_clone_to_remote (task 4D, F12: the diverged-recovery action) -------------------


def test_reset_discards_local_only_commits_and_lands_on_the_remote_tip(
    remote: Path, clone: Path
) -> None:
    rrepo = Repo(remote)
    _commit(rrepo, remote, "b.txt", "remote-side\n")
    crepo = Repo(clone)
    _commit(crepo, clone, "c.txt", "local-side\n")
    assert check_base_drift(clone, "main").kind == "diverged"

    outcome = reset_clone_to_remote(clone, "main")
    assert outcome.ok is True
    assert crepo.head.commit.hexsha == rrepo.head.commit.hexsha
    assert not (clone / "c.txt").exists(), "the local-only commit's file must be gone too"
    assert (clone / "b.txt").exists()
    # The clone is no longer diverged — the exact property this action exists to restore.
    assert check_base_drift(clone, "main").kind == "in_sync"


def test_reset_is_a_no_op_shaped_action_when_already_in_sync(clone: Path) -> None:
    crepo = Repo(clone)
    before = crepo.head.commit.hexsha
    outcome = reset_clone_to_remote(clone, "main")
    assert outcome.ok is True
    assert crepo.head.commit.hexsha == before


def test_reset_reports_failure_on_an_unreachable_remote(remote: Path, clone: Path) -> None:
    crepo = Repo(clone)
    crepo.remotes.origin.set_url(str(remote / "gone"))
    outcome = reset_clone_to_remote(clone, "main")
    assert outcome.ok is False
    assert outcome.detail


def test_reset_reports_failure_when_the_clone_is_missing(tmp_path: Path) -> None:
    outcome = reset_clone_to_remote(tmp_path / "nowhere", "main")
    assert outcome.ok is False
    assert "no project clone" in outcome.detail


def test_reset_removes_untracked_leftovers_too(remote: Path, clone: Path) -> None:
    """Mirrors `open_project_workspace`'s own run-start sweep — an untracked file from a
    crashed/cancelled run must not survive a reset that is meant to restore a clean state."""
    (clone / "untracked.txt").write_text("leftover\n", encoding="utf-8")
    outcome = reset_clone_to_remote(clone, "main")
    assert outcome.ok is True
    assert not (clone / "untracked.txt").exists()
