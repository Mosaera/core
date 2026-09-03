"""task 4E: a failed clone must not poison the next retry.

`_clone_into` used to leave `dest` behind on failure — usually just the `.git` directory
`Repo.clone_from` half-writes before the transport error, but a failure inside
`_init_empty`/`_prepare_workspace` could leave a full clone with a partially-prepared working
tree too. Either way, git's "destination path already exists and is not an empty directory"
poisoned every retry with the SAME leftover, even against a perfectly good source, because
nothing ever cleaned up the failed attempt.

Kept in its own small file rather than added to `test_repo_tools.py` — that file already sits
at the test-file line ceiling the god-file guard enforces.
"""

from pathlib import Path

import pytest
from git import Repo
from mosaera_core.tools.repo import clone_project


@pytest.fixture()
def source_repo(tmp_path: Path) -> Path:
    src = tmp_path / "source"
    src.mkdir()
    repo = Repo.init(src)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "T")
        cw.set_value("user", "email", "t@local")
    (src / "a.txt").write_text("one\n", encoding="utf-8")
    repo.index.add(["a.txt"])
    repo.index.commit("init")
    return src


def test_a_failed_clone_removes_the_partial_dest_so_retry_works(
    tmp_path: Path, source_repo: Path
) -> None:
    bad = "https://gitlab.invalid.localhost/g/r.git"
    with pytest.raises(RuntimeError, match="clone failed:"):
        clone_project(bad, tmp_path / "projects", "proj-retry")

    dest = tmp_path / "projects" / "proj-retry" / "repo"
    assert not dest.exists(), "the partial clone must not survive its own failure"

    # The retry — against a GOOD source, exactly as a user pressing "Try again" would do —
    # must succeed rather than fail on a leftover directory from the first attempt.
    ws = clone_project(str(source_repo), tmp_path / "projects", "proj-retry")
    assert ws.root.is_dir() and (ws.root / ".git").is_dir()


def test_a_failure_after_the_clone_step_still_cleans_up(
    tmp_path: Path, source_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not just a transport failure — anything inside `_clone_into` after `clone_from`
    succeeds (workspace preparation, the greenfield init) must clean up too."""
    import mosaera_core.tools.repo.clone as clone_mod

    def _boom(*a: object, **k: object) -> None:
        raise RuntimeError("boom during workspace prep")

    monkeypatch.setattr(clone_mod, "_prepare_workspace", _boom)
    with pytest.raises(RuntimeError, match="boom during workspace prep"):
        clone_project(str(source_repo), tmp_path / "projects", "proj-boom")

    assert not (tmp_path / "projects" / "proj-boom" / "repo").exists()
