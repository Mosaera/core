"""Local-first projects: a working repository with no upstream (ADR-0123).

Split from ``test_repo_tools.py``, which is at its test-file line ratchet. These share a
subject rather than a fixture: a project used to be unable to exist without an existing
repository, which is also why nothing on an instance could exercise repository creation.
"""

from pathlib import Path

import pytest
from git import Repo
from mosaera_core.tools.repo import clone_project, init_project


def test_init_project_gives_a_working_repo_with_real_history(tmp_path: Path) -> None:
    """The local-first path. It must land in the SAME place and shape `clone_project` produces,
    so every downstream step sees one kind of project rather than two."""
    ws = init_project(tmp_path, "proj-demo-abc123")

    assert ws.root == (tmp_path / "proj-demo-abc123" / "repo").resolve()
    repo = Repo(ws.root)
    assert repo.active_branch.name == "mosaera/project-proj-demo-abc123"
    # One real commit, so HEAD is valid and diff/delivery have a base to stand on.
    assert len(list(repo.iter_commits())) == 1
    assert (ws.root / "README.md").exists()
    # No upstream: inventing one would make the later publish step ambiguous about its target.
    assert repo.remotes == []
    # The clone-local excludes are what keep .venv/node_modules/scratch out of every diff and
    # delivery — a project that skipped them would ship dependencies.
    exclude = (ws.root / ".git" / "info" / "exclude").read_text()
    assert "/node_modules/" in exclude and "/.mosaera/" in exclude
    assert (ws.root / ".mosaera" / "scratch").is_dir()


def test_a_blank_source_is_refused_rather_than_cloning_the_working_directory(
    tmp_path: Path,
) -> None:
    """`Path("").exists()` is True and resolves to the CURRENT WORKING DIRECTORY, so a blank
    source would clone whatever the server was started in. That is the cwd-inheritance shape that
    destroyed the evidence store on 2026-08-10; a project with no upstream takes `init_project`.
    """
    for blank in ("", "   "):
        with pytest.raises(RuntimeError, match="no source repository"):
            clone_project(blank, tmp_path, "proj-x")
    assert not (tmp_path / "proj-x").exists(), "nothing may be created on the refused path"
