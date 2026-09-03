"""A2: the commit-picker engine — commit_list + cherry_pick_into_branch.

Pure git on a temp repo, no network. Covers the happy path (pick a subset onto a fresh branch)
and the load-bearing safety: a conflicting pick aborts and leaves the shared clone clean.
"""

from pathlib import Path

from git import Repo
from mosaera_core.tools.repo import Workspace, cherry_pick_into_branch, commit_list


def _repo(tmp_path: Path) -> Repo:
    r = Repo.init(tmp_path, initial_branch="main")
    with r.config_writer() as cw:
        cw.set_value("user", "name", "T")
        cw.set_value("user", "email", "t@local")
    (tmp_path / "base.txt").write_text("base\n", encoding="utf-8")
    r.index.add(["base.txt"])
    r.index.commit("base")
    return r


def _ws(root: Path) -> Workspace:
    return Workspace(root=root, run_id="t", branch=Repo(root).active_branch.name)


def _add(r: Repo, root: Path, name: str, text: str, msg: str) -> str:
    (root / name).write_text(text, encoding="utf-8")
    r.index.add([name])
    return r.index.commit(msg).hexsha


def test_commit_list_reports_commits_ahead_of_base(tmp_path: Path) -> None:
    r = _repo(tmp_path)
    r.git.checkout("-b", "work")
    _add(r, tmp_path, "a.txt", "a\n", "add a")
    _add(r, tmp_path, "b.txt", "b\n", "add b")
    rows = commit_list(_ws(tmp_path), "main", "work")
    assert [c["subject"] for c in rows] == ["add b", "add a"]  # newest first
    assert all(len(c["short"]) == 8 and c["sha"] and c["author"] for c in rows)


def test_cherry_pick_selects_a_subset_onto_a_fresh_branch(tmp_path: Path) -> None:
    r = _repo(tmp_path)
    r.git.checkout("-b", "work")
    sha_a = _add(r, tmp_path, "a.txt", "a\n", "add a")
    _add(r, tmp_path, "b.txt", "b\n", "add b")
    sha_c = _add(r, tmp_path, "c.txt", "c\n", "add c")
    # Pick only a and c onto a branch cut at main — b must NOT appear.
    res = cherry_pick_into_branch(_ws(tmp_path), "main", [sha_a, sha_c], "mosaera/combined-p1")
    assert res.error is None and res.branch == "mosaera/combined-p1"
    assert res.picked == [sha_a, sha_c]
    subjects = [c["subject"] for c in commit_list(_ws(tmp_path), "main", "mosaera/combined-p1")]
    assert "add a" in subjects and "add c" in subjects and "add b" not in subjects


def test_conflict_aborts_and_leaves_the_tree_clean(tmp_path: Path) -> None:
    # Two commits that both touch the same file with divergent content → the second conflicts
    # when cherry-picked onto a branch that already has the first's change baked in differently.
    r = _repo(tmp_path)
    r.git.checkout("-b", "work")
    _add(r, tmp_path, "x.txt", "line-one\n", "x one")
    sha_two = _add(r, tmp_path, "x.txt", "line-two\n", "x two")
    # Base branch already has a DIFFERENT x.txt, so cherry-picking "x two" conflicts.
    r.git.checkout("main")
    _add(r, tmp_path, "x.txt", "totally-different\n", "x base")
    res = cherry_pick_into_branch(_ws(tmp_path), "main", [sha_two], "mosaera/combined-p1")
    assert res.conflict_sha == sha_two and res.error
    # The clone is CLEAN — no CHERRY_PICK_HEAD, no conflict markers left to poison the next run.
    repo = Repo(tmp_path)
    assert not (Path(repo.git_dir) / "CHERRY_PICK_HEAD").exists()
    assert not repo.is_dirty(untracked_files=True)


def test_empty_selection_is_an_honest_error(tmp_path: Path) -> None:
    _repo(tmp_path)
    res = cherry_pick_into_branch(_ws(tmp_path), "main", [], "mosaera/combined-p1")
    assert res.error and res.branch == ""
