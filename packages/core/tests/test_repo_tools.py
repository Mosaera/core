import sys
from collections.abc import Sequence
from pathlib import Path

import pytest
from git import Repo
from mosaera_core.sandbox import SandboxResult, SandboxWorker, SubprocessSandbox
from mosaera_core.tools.repo import (
    CODER_TOOL_CAPABILITIES,
    PathEscapeError,
    Workspace,
    _auth_url,
    build_overview,
    build_repo_tools,
    clone_project,
    clone_repo,
    describe_coder_capabilities,
    open_project_workspace,
    parse_numstat,
    project_base,
    project_diff,
    project_diff_stats,
    project_item_diff,
)
from mosaera_core.tools.repo._exec import (
    EXEC_REPEAT_LIMIT as _EXEC_REPEAT_LIMIT,
)
from mosaera_core.tools.repo._exec import (
    EXEC_SESSION_LIMIT as _EXEC_SESSION_LIMIT,
)
from mosaera_policies import ROLE_TOOL_ALLOWLIST


@pytest.fixture
def source_repo(tmp_path: Path) -> Path:
    src = tmp_path / "source-repo"
    src.mkdir()
    repo = Repo.init(src, initial_branch="main")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test User")
        cw.set_value("user", "email", "test@example.com")
    (src / "hello.py").write_text("def greet():\n    return 'hello'\n", encoding="utf-8")
    (src / "README.md").write_text("# sample\n", encoding="utf-8")
    repo.index.add(["hello.py", "README.md"])
    repo.index.commit("init")
    return src


@pytest.fixture
def workspace(source_repo: Path, tmp_path: Path) -> Workspace:
    return clone_repo(str(source_repo), tmp_path / "workspaces", "test-run")


def test_tree_hash_changes_only_when_the_tree_changes(workspace: Workspace) -> None:
    # tree_hash is the memo key for within-run cached evidence (#23 / ADR-0003):
    # identical on an unchanged tree, different after any add / edit / delete.
    # This recompute-on-change invariant is what keeps the plan/test memoization
    # correct — reuse only while the tree is unchanged, never across a change.
    h0 = workspace.tree_hash()
    assert workspace.tree_hash() == h0  # stable when nothing changes → memo hits

    (workspace.root / "new_file.py").write_text("x = 1\n", encoding="utf-8")
    h_add = workspace.tree_hash()
    assert h_add != h0  # a new file changes the hash → recompute (e.g. re-detect)

    (workspace.root / "new_file.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    assert workspace.tree_hash() != h_add  # editing (size change) changes the hash

    (workspace.root / "new_file.py").unlink()
    assert workspace.tree_hash() == h0  # back to the original tree → memo hits again


def test_clone_is_isolated_and_on_run_branch(workspace: Workspace, source_repo: Path) -> None:
    assert workspace.root != source_repo.resolve()
    assert (workspace.root / "hello.py").exists()
    assert workspace.repo.active_branch.name == "mosaera/test-run"


def test_project_clone_persists_and_reopens_same_branch(source_repo: Path, tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    ws = clone_project(str(source_repo), projects, "proj-x")
    assert ws.root == (projects / "proj-x" / "repo").resolve()
    assert ws.branch == "mosaera/project-proj-x"
    # Reopen the existing clone on its branch (no re-clone).
    reopened = open_project_workspace(projects, "proj-x", "run-1")
    assert reopened.root == ws.root and reopened.branch == "mosaera/project-proj-x"
    assert reopened.run_id == "run-1"


def test_open_project_workspace_missing_clone_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        open_project_workspace(tmp_path / "projects", "nope", "run-1")


def test_clone_failure_scrubs_token_from_error(tmp_path: Path) -> None:
    # A bad https token source can't be cloned; git echoes the auth URL with
    # the token in its error — the raised message must never carry it. gitlab_url matches the
    # source host so the token IS injected (host-equality gate passes), keeping this a real test
    # of the scrubbing path.
    bad = "https://gitlab.invalid.localhost/g/r.git"
    with pytest.raises(RuntimeError) as exc:
        clone_project(
            bad,
            tmp_path / "projects",
            "proj-x",
            clone_token="glpat-supersecret",
            gitlab_url="https://gitlab.invalid.localhost",
        )
    msg = str(exc.value)
    assert "glpat-supersecret" not in msg
    assert msg.startswith("clone failed:")


def test_auth_url_injects_token_only_for_the_configured_gitlab_host() -> None:
    # ADR-0042 sink-containment: the scoped PAT is injected only when the source is on the
    # configured GitLab (host equality) — never sent to a look-alike / arbitrary host.
    from mosaera_core.tools.repo.clone import _auth_url

    gl = "https://gitlab.example.com"
    # On-host → token injected.
    assert _auth_url("https://gitlab.example.com/g/r.git", "glpat-x", gl) == (
        "https://oauth2:glpat-x@gitlab.example.com/g/r.git"
    )
    # Look-alike / foreign hosts → returned UNCHANGED (token never leaves the box).
    for foreign in (
        "https://gitlab.example.com.evil.io/g/r.git",  # suffix look-alike
        "https://evil.io/gitlab.example.com/g/r.git",  # host in the path
        "https://gitlab.example.com@evil.io/g/r.git",  # userinfo trick
        "https://github.com/g/r.git",  # unrelated host
    ):
        assert "glpat-x" not in _auth_url(foreign, "glpat-x", gl)
    # No gitlab_url configured → fail safe, never inject.
    assert _auth_url("https://gitlab.example.com/g/r.git", "glpat-x", None) == (
        "https://gitlab.example.com/g/r.git"
    )
    # No token → unchanged.
    assert _auth_url("https://gitlab.example.com/g/r.git", None, gl) == (
        "https://gitlab.example.com/g/r.git"
    )
    # http to a NETWORKED host → refuse to put the PAT on the wire in cleartext (finding D4),
    # even though it IS the configured GitLab host.
    assert _auth_url(
        "http://gitlab.example.com/g/r.git", "glpat-x", "http://gitlab.example.com"
    ) == ("http://gitlab.example.com/g/r.git")
    # http to a LOOPBACK host (local dev GitLab) → still injected (no wire to sniff).
    assert _auth_url("http://localhost/g/r.git", "glpat-x", "http://localhost") == (
        "http://oauth2:glpat-x@localhost/g/r.git"
    )


def test_reset_sweeps_uncommitted_but_keeps_accumulated_commits(
    source_repo: Path, tmp_path: Path
) -> None:
    projects = tmp_path / "projects"
    ws = clone_project(str(source_repo), projects, "proj-r")
    # Legitimate accumulated work: committed on the project branch.
    (ws.root / "KEEP.md").write_text("keep\n", encoding="utf-8")
    ws.commit_all("mosaera: add KEEP.md")
    # Leftovers from a crashed/cancelled/unapproved run: uncommitted.
    (ws.root / "junk.txt").write_text("junk\n", encoding="utf-8")
    (ws.root / "hello.py").write_text("def greet():\n    return 'tampered'\n", encoding="utf-8")
    cache = ws.root / "__pycache__"
    cache.mkdir()
    (cache / "x.pyc").write_bytes(b"\x00")

    # Read paths (reset=False, the default) must leave the dirt untouched.
    dirty = open_project_workspace(projects, "proj-r", "run-ro")
    assert (dirty.root / "junk.txt").exists()

    # Run start (reset=True) sweeps the dirt, keeps the committed work.
    clean = open_project_workspace(projects, "proj-r", "run-2", reset=True)
    assert not (clean.root / "junk.txt").exists()
    assert "hello" in (clean.root / "hello.py").read_text(encoding="utf-8")
    assert (clean.root / "KEEP.md").exists()
    _, diff = project_diff(clean)
    assert "KEEP.md" in diff  # accumulation intact
    assert (clean.root / "__pycache__").exists()  # excluded caches survive clean -fd


def test_item_branch_cuts_per_item_branches_stacked(source_repo: Path, tmp_path: Path) -> None:
    # Per-item stacked-MR model (ADR-0021): each item run works on its own branch,
    # cut from the current tip so it builds on all prior delivered items, yet its
    # per-item diff shows ONLY its own change.
    projects = tmp_path / "projects"
    clone_project(str(source_repo), projects, "proj-stack")
    base = project_base(open_project_workspace(projects, "proj-stack", "ro"))

    # Item A on its own branch.
    ws_a = open_project_workspace(
        projects, "proj-stack", "run-a", reset=True, item_branch="mosaera/item-1"
    )
    assert ws_a.branch == "mosaera/item-1"
    (ws_a.root / "A.md").write_text("a\n", encoding="utf-8")
    ws_a.commit_all("mosaera: item A")

    # Item B cut from the current tip (= item A) → carries A's work + adds its own.
    ws_b = open_project_workspace(
        projects, "proj-stack", "run-b", reset=True, item_branch="mosaera/item-2"
    )
    assert ws_b.branch == "mosaera/item-2"
    assert (ws_b.root / "A.md").exists()  # built on top of the predecessor
    (ws_b.root / "B.md").write_text("b\n", encoding="utf-8")
    ws_b.commit_all("mosaera: item B")

    # B's MR diff (vs its predecessor item-1) is JUST B — the clean, revertable unit.
    item_b_diff = project_item_diff(ws_b, "mosaera/item-1")
    assert "B.md" in item_b_diff and "A.md" not in item_b_diff
    # A's MR diff (vs the source base) is JUST A.
    repo = ws_b.repo
    repo.git.checkout("mosaera/item-1")
    ws_a_reopened = open_project_workspace(projects, "proj-stack", "ro-a")
    assert "A.md" in project_item_diff(ws_a_reopened, base)


def test_item_branch_none_leaves_active_branch(source_repo: Path, tmp_path: Path) -> None:
    # Read paths pass item_branch=None (and reset=False) → no checkout, the active
    # branch is untouched (a concurrent GET must never re-point the live branch).
    projects = tmp_path / "projects"
    clone_project(str(source_repo), projects, "proj-ro")
    open_project_workspace(projects, "proj-ro", "run-x", reset=True, item_branch="mosaera/item-9")
    reopened = open_project_workspace(projects, "proj-ro", "read")
    assert reopened.branch == "mosaera/item-9"  # whatever was last checked out, unchanged


def test_auth_url_rewrites_https_only() -> None:
    gl = "https://gitlab.rengifo.me"
    assert _auth_url("https://gitlab.rengifo.me/g/r.git", "tok", gl) == (
        "https://oauth2:tok@gitlab.rengifo.me/g/r.git"
    )
    assert (
        _auth_url("https://gitlab.rengifo.me/g/r.git", None, gl)
        == "https://gitlab.rengifo.me/g/r.git"
    )
    # A valid GitLab ssh source: host-equality passes but the scheme isn't http(s), so untouched.
    assert _auth_url("git@gitlab.rengifo.me:g/r.git", "tok", gl) == "git@gitlab.rengifo.me:g/r.git"
    assert _auth_url("/local/path", "tok", gl) == "/local/path"  # local untouched


def test_greenfield_clone_initializes_base(tmp_path: Path) -> None:
    # An empty bare repo as the source (no commits).
    src = tmp_path / "empty.git"
    Repo.init(src, bare=True, initial_branch="main")
    ws = clone_project(str(src), tmp_path / "projects", "proj-gf")
    assert ws.branch == "mosaera/project-proj-gf"
    assert (ws.root / "README.md").exists()  # base commit created
    assert project_base(ws) == "main"
    # No work yet → empty accumulated diff; a commit then shows up.
    assert project_diff(ws)[1].strip() == ""
    (ws.root / "index.html").write_text("<h1>hi</h1>\n", encoding="utf-8")
    ws.commit_all("mosaera: add index.html")
    base, diff = project_diff(ws)
    assert base == "main" and "index.html" in diff


def test_project_diff_shows_accumulated_change(source_repo: Path, tmp_path: Path) -> None:
    ws = clone_project(str(source_repo), tmp_path / "projects", "proj-d")
    assert project_base(ws) in ("main", "master")
    # No work yet → empty diff vs base.
    _, empty = project_diff(ws)
    assert empty.strip() == ""
    # Commit on the project branch → the accumulated diff reflects it.
    (ws.root / "NEW.md").write_text("hello\n", encoding="utf-8")
    ws.commit_all("mosaera: add NEW.md")
    base, diff = project_diff(ws)
    assert base in ("main", "master")
    assert "NEW.md" in diff and "+hello" in diff
    # Per-file stats agree with the diff (numstat is authoritative for the UI).
    stats = project_diff_stats(ws)
    assert {"path": "NEW.md", "additions": 1, "deletions": 0} in stats


def test_parse_numstat_binary_and_renames() -> None:
    out = "3\t1\tsrc/app.py\n-\t-\tassets/logo.png\n2\t0\tdocs/{old => new}/guide.md\n1\t0\told.md => new.md\n"  # noqa: E501
    assert parse_numstat(out) == [
        {"path": "src/app.py", "additions": 3, "deletions": 1},
        {"path": "assets/logo.png", "additions": None, "deletions": None},
        {"path": "docs/new/guide.md", "additions": 2, "deletions": 0},
        {"path": "new.md", "additions": 1, "deletions": 0},
    ]


def test_path_escape_rejected(workspace: Workspace) -> None:
    with pytest.raises(PathEscapeError):
        workspace.resolve("../outside.txt")
    with pytest.raises(PathEscapeError):
        workspace.resolve("a/../../outside.txt")
    with pytest.raises(PathEscapeError):
        workspace.resolve(str(workspace.root.parent / "abs.txt"))


def test_file_listing_skips_symlinks_out_of_clone(workspace: Workspace, tmp_path: Path) -> None:
    # A hostile target repo committing a symlink to a host file must not leak it
    # through the host-side listing (which backs the read-only search/list tools).
    secret = tmp_path / "host-secret.txt"
    secret.write_text("SENSITIVE", encoding="utf-8")
    link = workspace.root / "leak.txt"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform/permissions")
    listing = workspace.file_listing()
    assert "leak.txt" not in listing  # the escaping symlink is never listed
    assert "hello.py" in listing  # ordinary files still appear


def test_file_listing_never_descends_into_build_artifact_dirs(
    workspace: Workspace, tmp_path: Path
) -> None:
    # A build-artifact venv is PRUNED during the walk, never descended into (regression:
    # rglob used to stat every .venv entry before the skip-filter, so a platform-incompatible
    # symlink like a Linux `.venv/bin/python` on a Windows host crashed tree_hash with
    # WinError 1920 on any run that installed deps). Simulate the crash-prone shape: a broken
    # symlink under .venv must not be reached, and tree_hash must not raise.
    venv_bin = workspace.root / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (workspace.root / ".venv" / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    try:
        (venv_bin / "python").symlink_to("/nonexistent/usr/local/bin/python")
    except (OSError, NotImplementedError):
        # No symlink support → still assert the dir is pruned (a plain file stands in).
        (venv_bin / "python").write_text("", encoding="utf-8")
    listing = workspace.file_listing()
    assert not any(p.startswith(".venv/") for p in listing)  # never descended into .venv
    assert "hello.py" in listing
    # The crash path: tree_hash walks the tree — it must complete, not raise WinError 1920.
    assert isinstance(workspace.tree_hash(), str)


def test_write_tool_confined_to_clone(workspace: Workspace) -> None:
    tools = {
        t.name: t
        for t in build_repo_tools(workspace, SubprocessSandbox(workspace.root), approval_gate=False)
    }
    denied = tools["write_file"].invoke({"path": "../evil.txt", "content": "x"})
    assert denied.startswith("ERROR")
    assert not (workspace.root.parent / "evil.txt").exists()

    ok = tools["write_file"].invoke({"path": "sub/new.txt", "content": "content"})
    assert ok.startswith("Wrote")
    assert (workspace.root / "sub" / "new.txt").read_text(encoding="utf-8") == "content"


def test_write_file_refuses_scratch_and_root_test_files(workspace: Workspace) -> None:
    # Deterministic cleanliness guard: debug/scratch scripts and root-level test
    # files are refused at the source (they cluttered/poisoned earlier runs).
    tools = {
        t.name: t
        for t in build_repo_tools(workspace, SubprocessSandbox(workspace.root), approval_gate=False)
    }
    write = tools["write_file"]
    assert write.invoke({"path": "debug_thing.py", "content": "print(1)"}).startswith("REFUSED")
    assert write.invoke({"path": "src/manual_check.py", "content": "x"}).startswith("REFUSED")
    assert write.invoke({"path": "test_root.py", "content": "def test_x(): pass"}).startswith(
        "REFUSED"
    )
    assert not (workspace.root / "debug_thing.py").exists()
    # Legitimate files are allowed: package code, and tests placed under tests/.
    assert write.invoke({"path": "todo/cli.py", "content": "x = 1\n"}).startswith("Wrote")
    assert write.invoke(
        {"path": "tests/test_todo.py", "content": "def test_x(): pass\n"}
    ).startswith("Wrote")


# --- Scratch space (#59, ADR-0064) ---


def _scratch_write(workspace: Workspace, *, enabled: bool):
    tools = {
        t.name: t
        for t in build_repo_tools(
            workspace,
            SubprocessSandbox(workspace.root),
            approval_gate=False,
            enable_scratch=enabled,
        )
    }
    return tools["write_file"]


def test_scratch_dir_allows_any_name_when_enabled(workspace: Workspace) -> None:
    # The sanctioned scratch space accepts ANY name, incl. debug/scratch names refused elsewhere.
    write = _scratch_write(workspace, enabled=True)
    assert write.invoke(
        {"path": ".mosaera/scratch/debug_thing.py", "content": "print(1)\n"}
    ).startswith("Wrote")
    assert write.invoke({"path": ".mosaera/scratch/notes.md", "content": "exploring\n"}).startswith(
        "Wrote"
    )
    assert (workspace.root / ".mosaera" / "scratch" / "debug_thing.py").exists()


def test_scratch_name_still_refused_outside_scratch_even_when_enabled(workspace: Workspace) -> None:
    # The exemption is confined to the scratch dir — the shipped tree keeps the cleanliness guard.
    write = _scratch_write(workspace, enabled=True)
    assert write.invoke({"path": "debug_thing.py", "content": "print(1)"}).startswith("REFUSED")
    assert write.invoke({"path": "src/scratch_x.py", "content": "x"}).startswith("REFUSED")
    # A `..` escape out of scratch normalizes to the shipped tree, so it is NOT exempt.
    assert write.invoke(
        {"path": ".mosaera/scratch/../src/scratch_evil.py", "content": "x"}
    ).startswith("REFUSED")


def test_scratch_name_refused_in_scratch_dir_when_disabled(workspace: Workspace) -> None:
    # Knob off → no exemption → a scratch-NAMED file even under .mosaera/scratch/ is refused.
    write = _scratch_write(workspace, enabled=False)
    assert write.invoke(
        {"path": ".mosaera/scratch/debug_thing.py", "content": "print(1)"}
    ).startswith("REFUSED")


def test_git_internals_write_is_refused(workspace: Workspace) -> None:
    # The coder must never edit .git/ — in particular .git/info/exclude, which would let it
    # un-exclude the scratch space and smuggle it into the delivered commit (#59 red-team).
    write = _scratch_write(workspace, enabled=True)
    assert write.invoke({"path": ".git/info/exclude", "content": ""}).startswith("REFUSED")
    assert write.invoke({"path": ".git/hooks/pre-commit", "content": "#!/bin/sh\n"}).startswith(
        "REFUSED"
    )


def test_scratch_is_excluded_from_delivery(workspace: Workspace) -> None:
    # THE load-bearing property: nothing under .mosaera/scratch/ reaches diff_all() (grading)
    # or commit_all() (delivery). Also a real deliverable write, to prove the diff still works.
    write = _scratch_write(workspace, enabled=True)
    write.invoke({"path": ".mosaera/scratch/probe.py", "content": "print('scratch')\n"})
    write.invoke({"path": "shipped.py", "content": "x = 1\n"})
    diff = workspace.diff_all()
    assert "shipped.py" in diff
    assert "scratch" not in diff and ".mosaera" not in diff
    workspace.commit_all("deliver")
    tree = workspace.repo.git.ls_tree("-r", "--name-only", "HEAD")
    assert "shipped.py" in tree
    assert ".mosaera" not in tree and "scratch" not in tree


def test_scratch_gitignore_negation_cannot_ship(workspace: Workspace) -> None:
    # #59 red-team (HIGH): a coder-authored .gitignore that NEGATES the .mosaera exclusion outranks
    # .git/info/exclude in git's precedence. The delivery-seam enforcement (workspace._stage_all +
    # _assert_no_scratch_staged) must still keep scratch content out of the diff AND the commit.
    write = _scratch_write(workspace, enabled=True)
    write.invoke({"path": ".mosaera/scratch/evil.py", "content": "SECRET_EXFIL = 1\n"})
    write.invoke({"path": ".gitignore", "content": "!.mosaera/\n!.mosaera/scratch/\n"})
    # Grading path: the scratch CONTENT never enters the diff (the .gitignore itself may; harmless).
    assert "SECRET_EXFIL" not in workspace.diff_all()
    # Delivery path: the scratch FILE never enters the commit tree.
    workspace.commit_all("deliver")
    tree = workspace.repo.git.ls_tree("-r", "--name-only", "HEAD").split()
    assert ".mosaera/scratch/evil.py" not in tree


def test_pretracked_source_scratch_cannot_exfil(source_repo: Path, tmp_path: Path) -> None:
    # #59 red-team (MED-HIGH): a hostile source pre-TRACKS a .mosaera/scratch file (info/exclude
    # covers only UNTRACKED paths). The coder overwrites it with exfil; the seam reverts that so the
    # coder's content never ships.
    src_repo = Repo(source_repo)
    (source_repo / ".mosaera" / "scratch").mkdir(parents=True)
    (source_repo / ".mosaera" / "scratch" / "seed.py").write_text(
        "original = 1\n", encoding="utf-8"
    )
    src_repo.index.add([".mosaera/scratch/seed.py"])
    src_repo.index.commit("seed scratch")
    ws = clone_repo(str(source_repo), tmp_path / "ws-pretracked", "run-pt")
    write = _scratch_write(ws, enabled=True)
    write.invoke({"path": ".mosaera/scratch/seed.py", "content": "EXFIL = 1\n"})
    ws.commit_all("deliver")
    delivered = ws.repo.git.show("HEAD:.mosaera/scratch/seed.py")
    assert "EXFIL" not in delivered  # the coder's overwrite was reverted at the seam
    assert "original" in delivered


def test_write_file_refuses_noop_and_duplicate_writes(workspace: Workspace) -> None:
    # The coder-churn stopper: a write that changes nothing (or repeats content it
    # already wrote this run) is refused before it can prompt the human.
    tools = {
        t.name: t
        for t in build_repo_tools(workspace, SubprocessSandbox(workspace.root), approval_gate=False)
    }
    write = tools["write_file"]
    assert write.invoke({"path": "notes.txt", "content": "v1\n"}).startswith("Wrote")
    noop = write.invoke({"path": "notes.txt", "content": "v1\n"})  # identical to disk
    assert noop.startswith("REFUSED") and "changes nothing" in noop
    assert write.invoke({"path": "notes.txt", "content": "v2\n"}).startswith("Wrote")  # real change
    dup = write.invoke({"path": "notes.txt", "content": "v1\n"})  # content written earlier this run
    assert dup.startswith("REFUSED") and "already wrote this exact content" in dup
    assert "cannot delete" in dup  # the honest, actionable hint is attached


def test_edit_file_refuses_reproducing_prior_content(workspace: Workspace) -> None:
    tools = {
        t.name: t
        for t in build_repo_tools(workspace, SubprocessSandbox(workspace.root), approval_gate=False)
    }
    write, edit = tools["write_file"], tools["edit_file"]
    write.invoke({"path": "m.txt", "content": "alpha\n"})
    assert edit.invoke({"path": "m.txt", "old_str": "alpha", "new_str": "beta"}).startswith(
        "Edited"
    )
    back = edit.invoke(
        {"path": "m.txt", "old_str": "beta", "new_str": "alpha"}
    )  # reproduces "alpha\n"
    assert back.startswith("REFUSED") and "already wrote this exact content" in back


def test_edit_file_surgical_replace_and_guards(workspace: Workspace) -> None:
    tools = {
        t.name: t
        for t in build_repo_tools(workspace, SubprocessSandbox(workspace.root), approval_gate=False)
    }
    edit = tools["edit_file"]
    # Happy path: a unique anchor is replaced and the rest of the file is untouched.
    ok = edit.invoke({"path": "hello.py", "old_str": "return 'hello'", "new_str": "return 'hi'"})
    assert ok.startswith("Edited")
    text = (workspace.root / "hello.py").read_text(encoding="utf-8")
    assert "return 'hi'" in text and "def greet" in text  # untouched region preserved
    # Anchor not found → actionable error, nothing written.
    miss = edit.invoke({"path": "hello.py", "old_str": "does not exist", "new_str": "x"})
    assert miss.startswith("ERROR") and "anchor not found" in miss
    # Missing file → points at write_file instead of a silent create.
    nofile = edit.invoke({"path": "nope.py", "old_str": "a", "new_str": "b"})
    assert nofile.startswith("ERROR") and "write_file" in nofile
    # Path escape rejected (same guard as write_file).
    esc = edit.invoke({"path": "../evil.py", "old_str": "a", "new_str": "b"})
    assert esc.startswith("ERROR")
    assert not (workspace.root.parent / "evil.py").exists()


def test_edit_file_requires_unique_anchor(workspace: Workspace) -> None:
    (workspace.root / "dup.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    tools = {
        t.name: t
        for t in build_repo_tools(workspace, SubprocessSandbox(workspace.root), approval_gate=False)
    }
    edit = tools["edit_file"]
    # An ambiguous anchor is refused (silent clobber is the whole-file-write failure
    # mode this tool exists to avoid) — the file is left untouched.
    ambiguous = edit.invoke({"path": "dup.py", "old_str": "x = 1", "new_str": "x = 2"})
    assert ambiguous.startswith("ERROR") and "2 times" in ambiguous
    assert (workspace.root / "dup.py").read_text(encoding="utf-8") == "x = 1\nx = 1\n"
    # replace_all makes replacing every occurrence explicit.
    ok = edit.invoke(
        {"path": "dup.py", "old_str": "x = 1", "new_str": "x = 2", "replace_all": True}
    )
    assert ok.startswith("Edited")
    assert (workspace.root / "dup.py").read_text(encoding="utf-8") == "x = 2\nx = 2\n"


def test_edit_file_respects_approval_denial(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaera_policies import approval

    monkeypatch.setattr(
        approval,
        "request_approval",
        lambda action, summary, payload: approval.ApprovalDecision(approved=False, feedback="no"),
    )
    tools = {
        t.name: t
        for t in build_repo_tools(workspace, SubprocessSandbox(workspace.root), approval_gate=True)
    }
    denied = tools["edit_file"].invoke(
        {"path": "hello.py", "old_str": "return 'hello'", "new_str": "return 'hi'"}
    )
    assert denied.startswith("DENIED")
    # A denied edit must NOT touch the file.
    assert "return 'hello'" in (workspace.root / "hello.py").read_text(encoding="utf-8")


# --- F27: an overwrite is shown as a diff against disk, not as a wall of text. ---
# Disk is the last APPROVED state (write_file only writes after the gate approves), so the
# diff answers "what does this change about what I already said yes to". A revert and a fix
# are indistinguishable without it — which is how a correction was silently lost mid-run.


def _capture_gate(monkeypatch: pytest.MonkeyPatch, workspace: Workspace, **kw):
    """Build the toolset with the gate ON, capturing (summary, payload) instead of pausing."""
    from mosaera_policies import approval

    seen: list[tuple[str, dict]] = []

    def _fake(action: str, summary: str, payload: dict):
        seen.append((summary, payload))
        return approval.ApprovalDecision(approved=True)

    monkeypatch.setattr(approval, "request_approval", _fake)
    tools = {
        t.name: t
        for t in build_repo_tools(
            workspace, SubprocessSandbox(workspace.root), approval_gate=True, **kw
        )
    }
    return tools, seen


def test_overwrite_shows_a_diff_against_disk(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools, seen = _capture_gate(monkeypatch, workspace)
    (workspace.root / "mod.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    tools["write_file"].invoke({"path": "mod.py", "content": "a = 1\nb = 99\nc = 3\n"})
    summary, payload = seen[-1]
    assert "diff" in payload
    assert payload["diff"].startswith("diff --git a/mod.py b/mod.py")  # DiffView parses this
    assert "-b = 2" in payload["diff"] and "+b = 99" in payload["diff"]
    assert "REWRITE" in summary and "+1 -1" in summary
    # The proposed content is still available; the diff is an addition, not a replacement.
    assert payload["content"] == "a = 1\nb = 99\nc = 3\n"


def test_overwrite_that_deletes_a_test_is_flagged(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The literal F27 case: a rewrite that reintroduces the `src.` prefix AND drops the only
    # test covering a charter constraint. Character count cannot distinguish this from progress;
    # the counts must.
    tools, seen = _capture_gate(monkeypatch, workspace)
    good = "from budget_tracker.storage import load\n\ndef test_quantization():\n    assert True\n"
    regressed = "from src.budget_tracker.storage import load\n"
    (workspace.root / "t.py").write_text(good, encoding="utf-8")
    tools["write_file"].invoke({"path": "t.py", "content": regressed})
    summary, payload = seen[-1]
    assert "-4" in summary  # four lines removed, and the operator sees it before approving
    assert "test_quantization" in payload["diff"]  # the deleted test appears as a - line


def test_append_only_overwrite_reports_no_removals(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools, seen = _capture_gate(monkeypatch, workspace)
    (workspace.root / "mod.py").write_text("a = 1\n", encoding="utf-8")
    tools["write_file"].invoke({"path": "mod.py", "content": "a = 1\nb = 2\n"})
    summary, _ = seen[-1]
    assert "+1 -0" in summary


def test_new_file_write_is_unchanged(workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    # Compatibility guarantee: a CREATE has nothing to diff against and keeps its old shape.
    tools, seen = _capture_gate(monkeypatch, workspace)
    tools["write_file"].invoke({"path": "brand_new.py", "content": "x = 1\n"})
    summary, payload = seen[-1]
    assert "diff" not in payload
    assert summary == "Coder wants to write brand_new.py (6 chars)"


def test_overwrite_diff_is_capped_but_counts_are_true(workspace: Workspace) -> None:
    # Counts come from the full diff, so a truncated preview still reports honest totals
    # rather than only what happened to fit.
    from mosaera_core.tools.repo._activity import overwrite_diff

    old = "".join(f"line{i}\n" for i in range(400))
    new = "".join(f"changed{i}\n" for i in range(400))
    body, added, removed = overwrite_diff("big.py", old, new, limit=500)
    assert len(body) <= 500 + 80
    assert "truncated" in body
    assert added == 400 and removed == 400  # not the ~20 lines that fit


def test_overwrite_diff_of_identical_content_is_empty(workspace: Workspace) -> None:
    from mosaera_core.tools.repo._activity import overwrite_diff

    assert overwrite_diff("m.py", "a = 1\n", "a = 1\n") == ("", 0, 0)


def test_noop_overwrite_never_reaches_the_gate(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The churn guard fires BEFORE the gate, so an identical rewrite neither diffs nor prompts.
    tools, seen = _capture_gate(monkeypatch, workspace)
    (workspace.root / "mod.py").write_text("a = 1\n", encoding="utf-8")
    out = tools["write_file"].invoke({"path": "mod.py", "content": "a = 1\n"})
    assert out.startswith("REFUSED")
    assert seen == []


def test_tester_scoped_writes_also_get_the_diff(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The Proctor shares this tool with write_prefix="tests/"; a future divergence would mean
    # the separation-of-duties toolset loses the regression warning the coder's has.
    tools, seen = _capture_gate(monkeypatch, workspace, write_prefix="tests/")
    (workspace.root / "tests").mkdir(exist_ok=True)
    (workspace.root / "tests" / "test_x.py").write_text(
        "def test_a():\n    pass\n", encoding="utf-8"
    )
    tools["write_file"].invoke(
        {"path": "tests/test_x.py", "content": "def test_a():\n    assert 1\n"}
    )
    summary, payload = seen[-1]
    assert "diff" in payload and "REWRITE" in summary


def test_read_search_list_tools(workspace: Workspace) -> None:
    tools = {
        t.name: t
        for t in build_repo_tools(workspace, SubprocessSandbox(workspace.root), approval_gate=False)
    }
    assert "def greet" in tools["read_file"].invoke({"path": "hello.py"})
    assert "hello.py:1" in tools["search"].invoke({"pattern": r"def\s+greet"})
    listing = tools["list_files"].invoke({})
    assert "hello.py" in listing
    assert ".git" not in listing


def test_read_file_caps_large_files(workspace: Workspace) -> None:
    # A single read must not dominate the coder's context window and truncate the
    # next tool call, so read_file caps at _MAX_READ_CHARS.
    from mosaera_core.tools.repo import _MAX_READ_CHARS

    (workspace.root / "big.py").write_text("x = 1  # pad\n" * 5000, encoding="utf-8")
    tools = {
        t.name: t
        for t in build_repo_tools(workspace, SubprocessSandbox(workspace.root), approval_gate=False)
    }
    out = tools["read_file"].invoke({"path": "big.py"})
    assert _MAX_READ_CHARS <= 16_000  # kept modest for context pressure
    assert "truncated" in out
    assert len(out) <= _MAX_READ_CHARS + 200  # cap + the truncation note
    # The moment the cap bites is exactly when the range is worth knowing about.
    assert "start=" in out and "limit=" in out


# --- Ranged reads: the cheap alternative to re-reading a whole file (F29 lever 1). ---
# The coder's trim middleware keeps the last 3 tool outputs and trips at ~60% of num_ctx,
# so three capped whole-file reads alone exceed the trigger. A window is how a read stops
# costing ~4k tokens. Omitting BOTH args must stay byte-identical: pm, reviewer, critic and
# tester share this tool and none of them was asked to change.


def _read_tool(workspace: Workspace):
    return {
        t.name: t
        for t in build_repo_tools(workspace, SubprocessSandbox(workspace.root), approval_gate=False)
    }["read_file"]


def test_read_file_without_a_range_is_unchanged(workspace: Workspace) -> None:
    raw = (workspace.root / "hello.py").read_text(encoding="utf-8")
    read = _read_tool(workspace)
    # Byte-identical to the file, and identical across all three "no range" spellings.
    assert read.invoke({"path": "hello.py"}) == raw
    assert read.invoke({"path": "hello.py", "start": None}) == raw
    assert read.invoke({"path": "hello.py", "start": None, "limit": None}) == raw


def test_read_file_range_returns_only_those_lines_numbered(workspace: Workspace) -> None:
    (workspace.root / "many.py").write_text(
        "\n".join(f"line{i}" for i in range(1, 21)) + "\n", encoding="utf-8"
    )
    out = _read_tool(workspace).invoke({"path": "many.py", "start": 5, "limit": 3})
    assert "many.py lines 5-7 of 20:" in out  # header names the file's TRUE length
    assert "5\tline5" in out and "7\tline7" in out
    assert "line4" not in out and "line8" not in out


def test_read_file_range_open_ended_and_clamped(workspace: Workspace) -> None:
    (workspace.root / "many.py").write_text(
        "\n".join(f"line{i}" for i in range(1, 11)) + "\n", encoding="utf-8"
    )
    read = _read_tool(workspace)
    # No limit -> start through EOF.
    assert "lines 8-10 of 10:" in read.invoke({"path": "many.py", "start": 8})
    # A limit running past EOF clamps instead of erroring.
    assert "lines 8-10 of 10:" in read.invoke({"path": "many.py", "start": 8, "limit": 999})
    # No start -> from line 1.
    assert "lines 1-2 of 10:" in read.invoke({"path": "many.py", "limit": 2})
    # start below 1 clamps to 1 rather than wrapping like a negative index.
    for bad_start in (0, -5):
        assert "lines 1-2 of 10:" in read.invoke(
            {"path": "many.py", "start": bad_start, "limit": 2}
        )


def test_read_file_range_out_of_bounds_says_what_is_true(workspace: Workspace) -> None:
    # A wrong guess should cost ONE corrective call, so the error carries the real length.
    read = _read_tool(workspace)
    out = read.invoke({"path": "hello.py", "start": 9999})
    assert out.startswith("ERROR:") and "line(s)" in out and "9999" in out
    assert read.invoke({"path": "hello.py", "start": 1, "limit": 0}).startswith("ERROR:")
    assert read.invoke({"path": "hello.py", "start": 1, "limit": -3}).startswith("ERROR:")


def test_read_file_range_still_caps_a_huge_window(workspace: Workspace) -> None:
    from mosaera_core.tools.repo import _MAX_READ_CHARS

    (workspace.root / "big.py").write_text("x = 1  # pad\n" * 5000, encoding="utf-8")
    out = _read_tool(workspace).invoke({"path": "big.py", "start": 1, "limit": 5000})
    assert "truncated" in out
    assert len(out) <= _MAX_READ_CHARS + 200


def test_read_file_range_never_precedes_the_path_guard(workspace: Workspace) -> None:
    # The escape check must win over any range handling — a bad path is refused, not windowed.
    out = _read_tool(workspace).invoke({"path": "../outside.py", "start": 1, "limit": 5})
    assert out.startswith("ERROR:")
    assert "lines" not in out


def test_run_tests_tool_uses_validation_plan(workspace: Workspace) -> None:
    # The hello.py fixture has no test suite → the planner picks py-compile.
    tools = {
        t.name: t
        for t in build_repo_tools(workspace, SubprocessSandbox(workspace.root), approval_gate=False)
    }
    out = tools["run_tests"].invoke({})
    assert out.startswith("[validation plan: python-scripts")
    assert "[step py-compile: exit code 0]" in out

    # A broken HTML page the coder just wrote flips the plan and fails it.
    (workspace.root / "index.html").write_text("<div><h1>hi</h1>", encoding="utf-8")
    out = tools["run_tests"].invoke({})
    assert "html-check" in out
    assert "unclosed <div>" in out


def test_run_tests_stops_repeated_identical_failures(workspace: Workspace) -> None:
    # Within-node token guard: re-running the SAME failing suite without a code
    # change is not converging. After test_repeat_limit identical failures, run_tests
    # hands the coder a STOP directive to yield instead of burning its step budget.
    tools = {
        t.name: t
        for t in build_repo_tools(
            workspace, SubprocessSandbox(workspace.root), approval_gate=False, test_repeat_limit=2
        )
    }
    run, write = tools["run_tests"], tools["write_file"]
    # A broken HTML page fails validation the same way each run (the write clears the
    # guard, so this first run is count=1).
    write.invoke({"path": "index.html", "content": "<div><h1>hi</h1>"})
    first = run.invoke({})
    assert "unclosed <div>" in first and "STOP —" not in first  # count=1, below limit
    second = run.invoke({})  # 2nd identical failure → limit=2 trips
    assert "STOP —" in second and "SUMMARY: blocked" in second and "SUMMARY: escalate" in second
    # A real edit resets the guard (accepted write → _record_write clears the counter).
    write.invoke({"path": "index.html", "content": "<div><h1>hi</h1></div>\n"})
    third = run.invoke({})
    assert "STOP —" not in third  # counter reset by the edit → count back to 1


def test_run_tests_dedup_disabled_when_limit_not_above_one(workspace: Workspace) -> None:
    # test_repeat_limit<=1 disables the guard (parity with bump_stall's limit semantics).
    tools = {
        t.name: t
        for t in build_repo_tools(
            workspace, SubprocessSandbox(workspace.root), approval_gate=False, test_repeat_limit=1
        )
    }
    run, write = tools["run_tests"], tools["write_file"]
    write.invoke({"path": "index.html", "content": "<div><h1>hi</h1>"})
    for _ in range(4):
        assert "STOP —" not in run.invoke({})


def test_write_prefix_confines_writes_to_one_directory(workspace: Workspace) -> None:
    # The tester's toolset may write ONLY under tests/ (strict separation, ADR-0013).
    tools = {
        t.name: t
        for t in build_repo_tools(
            workspace, SubprocessSandbox(workspace.root), approval_gate=False, write_prefix="tests/"
        )
    }
    write = tools["write_file"]
    assert write.invoke(
        {"path": "tests/test_greet.py", "content": "def test_x():\n    assert True\n"}
    ).startswith("Wrote")
    denied = write.invoke({"path": "hello.py", "content": "x = 1\n"})
    assert denied.startswith("REFUSED") and "only write under tests/" in denied
    assert "return 'hello'" in (workspace.root / "hello.py").read_text(
        encoding="utf-8"
    )  # untouched


def test_protected_paths_refuse_coder_write_edit_delete(workspace: Workspace) -> None:
    # The coder cannot modify or delete a tester-authored protected test (deterministic
    # tool-level refusal). Applies to write_file, edit_file, AND delete_file.
    (workspace.root / "tests").mkdir(exist_ok=True)
    (workspace.root / "tests" / "test_contract.py").write_text(
        "def test_contract():\n    assert True\n", encoding="utf-8"
    )
    tools = {
        t.name: t
        for t in build_repo_tools(
            workspace,
            SubprocessSandbox(workspace.root),
            approval_gate=False,
            allow_delete=True,
            protected_paths=frozenset({"tests/test_contract.py"}),
        )
    }
    p = "tests/test_contract.py"
    w = tools["write_file"].invoke({"path": p, "content": "def test_contract():\n    pass\n"})
    assert w.startswith("REFUSED") and "protected test file" in w and "escalate" in w
    e = tools["edit_file"].invoke({"path": p, "old_str": "assert True", "new_str": "assert 1"})
    assert e.startswith("REFUSED") and "protected test file" in e
    d = tools["delete_file"].invoke({"path": p})
    assert d.startswith("REFUSED") and "protected test file" in d
    assert (workspace.root / "tests" / "test_contract.py").read_text(
        encoding="utf-8"
    ) == "def test_contract():\n    assert True\n"  # byte-for-byte intact


def test_tamper_check_detects_edited_or_deleted_protected_test(workspace: Workspace) -> None:
    from mosaera_core.tools.repo import hash_files, tampered_files

    (workspace.root / "tests").mkdir(exist_ok=True)
    a = workspace.root / "tests" / "test_a.py"
    b = workspace.root / "tests" / "test_b.py"
    a.write_text("def test_a():\n    assert True\n", encoding="utf-8")
    b.write_text("def test_b():\n    assert True\n", encoding="utf-8")
    baseline = hash_files(workspace, ["tests/test_a.py", "tests/test_b.py"])
    assert tampered_files(workspace, baseline) == []  # unchanged
    a.write_text("def test_a():\n    assert False  # weakened\n", encoding="utf-8")
    b.unlink()
    assert tampered_files(workspace, baseline) == ["tests/test_a.py", "tests/test_b.py"]


def test_tamper_hash_is_newline_agnostic_but_content_sensitive(workspace: Workspace) -> None:
    # ADR-0068: the engine authors tests on the Windows host (CRLF) but the sandbox/git normalize to
    # LF, so a raw-byte hash false-flagged the engine's OWN test as tampered (the dominant thrash
    # cause). hash_files normalizes CRLF→LF: a CRLF↔LF flip must NOT trip, but a real content change
    # (an assertion weakening) STILL must — the guard is unweakened.
    from mosaera_core.tools.repo import hash_files, tampered_files

    (workspace.root / "tests").mkdir(exist_ok=True)
    t = workspace.root / "tests" / "test_x.py"
    t.write_bytes(b"def test_x():\n    assert total([1, 2]) == 3\n")  # LF, as git/sandbox leave it
    baseline = hash_files(workspace, ["tests/test_x.py"])
    t.write_bytes(b"def test_x():\r\n    assert total([1, 2]) == 3\r\n")  # CRLF — same content
    assert tampered_files(workspace, baseline) == []  # newline flip alone does NOT trip
    t.write_bytes(b"def test_x():\r\n    assert True  # weakened\r\n")  # a real weakening (CRLF)
    assert tampered_files(workspace, baseline) == ["tests/test_x.py"]  # content change STILL trips


def test_diff_and_source_untouched(workspace: Workspace, source_repo: Path) -> None:
    (workspace.root / "hello.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
    diff = workspace.diff_all()
    assert "return 'hi'" in diff

    # The source repository must be untouched by workspace edits.
    src_repo = Repo(source_repo)
    assert not src_repo.is_dirty(untracked_files=True)
    assert "return 'hello'" in (source_repo / "hello.py").read_text(encoding="utf-8")


def test_test_byproducts_excluded_from_diff(workspace: Workspace) -> None:
    cache = workspace.root / "__pycache__"
    cache.mkdir()
    (cache / "hello.cpython-312.pyc").write_bytes(b"\x00fake")
    (workspace.root / "hello.py").write_text("def greet():\n    return 'hey'\n", encoding="utf-8")
    diff = workspace.diff_all()
    assert "return 'hey'" in diff
    assert "pycache" not in diff
    assert ".pyc" not in diff


def test_commit_all_creates_commit(workspace: Workspace) -> None:
    before = workspace.repo.head.commit.hexsha
    (workspace.root / "new.txt").write_text("x\n", encoding="utf-8")
    sha = workspace.commit_all("mosaera: test commit")
    assert sha != before
    assert str(workspace.repo.head.commit.message).startswith("mosaera: test commit")
    # A no-op commit returns "" (NOT the prior HEAD sha — that would misreport an
    # unrelated commit as this run's).
    assert workspace.commit_all("mosaera: nothing to do") == ""


def test_capability_map_binds_to_the_live_tool_set(workspace: Workspace) -> None:
    # Anti-drift: the PM-facing capability descriptions must describe EXACTLY the
    # full tool set build_repo_tools can create — add/remove a tool and this fails
    # until the map is updated, so the PM is never told a stale capability.
    # delete_file and sandbox_exec are opt-in, so compare against the both-on set.
    tools = build_repo_tools(
        workspace, SubprocessSandbox(workspace.root), allow_delete=True, enable_exec=True
    )
    assert set(CODER_TOOL_CAPABILITIES) == {t.name for t in tools}
    default = {t.name for t in build_repo_tools(workspace, SubprocessSandbox(workspace.root))}
    assert "delete_file" not in default  # absent unless an admin enables it
    assert "sandbox_exec" not in default  # absent unless coder_repl_enabled


def test_describe_coder_capabilities_reflects_the_flags() -> None:
    # Every always-on tool is advertised; delete_file / sandbox_exec only when their flag is set.
    off = describe_coder_capabilities()
    on = describe_coder_capabilities(allow_delete=True, enable_exec=True)
    for name in ROLE_TOOL_ALLOWLIST["coder"]:
        if name not in ("delete_file", "sandbox_exec"):
            assert name in off and name in on
    assert "delete_file" not in off and "delete_file" in on
    assert "sandbox_exec" not in off  # not advertised to the PM when the probe is off
    assert "sandbox_exec" in describe_coder_capabilities(enable_exec=True)  # advertised when on
    assert "OUT OF CAPABILITY" in off


def test_delete_file_removes_when_enabled_and_guards(workspace: Workspace) -> None:
    tools = {
        t.name: t
        for t in build_repo_tools(
            workspace, SubprocessSandbox(workspace.root), approval_gate=False, allow_delete=True
        )
    }
    delete = tools["delete_file"]
    (workspace.root / "junk.txt").write_text("bye\n", encoding="utf-8")
    assert delete.invoke({"path": "junk.txt"}).startswith("Deleted")
    assert not (workspace.root / "junk.txt").exists()
    # guards: missing / path-escape / directory / .git are all refused
    assert delete.invoke({"path": "nope.txt"}).startswith("ERROR")
    assert delete.invoke({"path": "../evil.txt"}).startswith("ERROR")
    (workspace.root / "sub").mkdir(exist_ok=True)
    assert delete.invoke({"path": "sub"}).startswith("ERROR")
    assert delete.invoke({"path": ".git/config"}).startswith("REFUSED")


def test_delete_file_absent_by_default(workspace: Workspace) -> None:
    names = {t.name for t in build_repo_tools(workspace, SubprocessSandbox(workspace.root))}
    assert "delete_file" not in names  # off by default → the tool isn't even built


# --- sandbox_exec: the read-only probe (ADR-0059, #55) ---


class _FakeSandbox(SandboxWorker):
    """Records run() calls (incl. readonly_work) and returns a canned result — a stand-in for a
    backend that CAN enforce read-only isolation (Docker), used to test the tool wiring offline."""

    def __init__(self, stdout: str = "probe-output", exit_code: int = 0) -> None:
        self.calls: list[dict] = []
        self._stdout = stdout
        self._exit = exit_code

    def run(
        self,
        cmd: Sequence[str],
        cwd: Path | None = None,
        timeout: int | None = None,
        image: str | None = None,
        readonly_work: bool = False,
    ) -> SandboxResult:
        self.calls.append({"cmd": list(cmd), "readonly_work": readonly_work, "timeout": timeout})
        return SandboxResult(self._exit, self._stdout, "", 0.01, False, True)


def test_sandbox_exec_absent_unless_enabled(workspace: Workspace) -> None:
    default = {t.name for t in build_repo_tools(workspace, _FakeSandbox())}
    assert "sandbox_exec" not in default  # opt-in via coder_repl_enabled
    on = {t.name for t in build_repo_tools(workspace, _FakeSandbox(), enable_exec=True)}
    assert "sandbox_exec" in on


def test_sandbox_exec_runs_readonly_and_returns_output(workspace: Workspace) -> None:
    fake = _FakeSandbox(stdout="value=42")
    tools = {t.name: t for t in build_repo_tools(workspace, fake, enable_exec=True)}
    out = tools["sandbox_exec"].invoke({"code": "print('value=42')"})
    assert "value=42" in out
    # It ran the snippet READ-ONLY, as `python -B -c <code>` (no .pyc writes to the ro mount).
    assert fake.calls and fake.calls[0]["readonly_work"] is True
    assert "-B" in fake.calls[0]["cmd"] and "-c" in fake.calls[0]["cmd"]


def test_sandbox_exec_unavailable_on_a_backend_that_cannot_enforce_readonly(
    workspace: Workspace,
) -> None:
    # The subprocess backend raises on readonly_work=True (fail-closed) — the tool must catch it and
    # report unavailable, NEVER let it run writable or crash the coder.
    tools = {
        t.name: t
        for t in build_repo_tools(workspace, SubprocessSandbox(workspace.root), enable_exec=True)
    }
    out = tools["sandbox_exec"].invoke({"code": "print(1)"})
    assert "unavailable" in out.lower()


def test_sandbox_exec_repeat_cap(workspace: Workspace) -> None:
    tools = {t.name: t for t in build_repo_tools(workspace, _FakeSandbox(), enable_exec=True)}
    ex = tools["sandbox_exec"]
    for _ in range(_EXEC_REPEAT_LIMIT):
        assert not ex.invoke({"code": "print('x')"}).startswith("STOP")
    assert ex.invoke({"code": "print('x')"}).startswith("STOP")  # same probe re-run → capped
    assert not ex.invoke({"code": "print('different')"}).startswith("STOP")  # a new probe is fine


def test_sandbox_exec_rejects_empty(workspace: Workspace) -> None:
    tools = {t.name: t for t in build_repo_tools(workspace, _FakeSandbox(), enable_exec=True)}
    assert tools["sandbox_exec"].invoke({"code": "   "}).startswith("ERROR")


def test_sandbox_exec_total_session_cap(workspace: Workspace) -> None:
    # Red-team #55: the identical-snippet guard fingerprints with digits STRIPPED, so cosmetic
    # variation evades it — here we vary a LETTER (fingerprint-distinct, so the per-snippet guard
    # never trips) and confirm the hard TOTAL cap still bounds the container cost.
    tools = {t.name: t for t in build_repo_tools(workspace, _FakeSandbox(), enable_exec=True)}
    ex = tools["sandbox_exec"]
    for i in range(_EXEC_SESSION_LIMIT):
        code = f"x = '{chr(97 + i)}'"  # 'a', 'b', … — each fingerprints distinctly
        assert not ex.invoke({"code": code}).startswith("STOP")
    assert ex.invoke({"code": "x = 'zz'"}).startswith("STOP")  # total budget spent, still capped


# --- F34: edit_file must show what it changes, not just what it deletes. ---


def test_edit_file_carries_a_real_diff_and_counts(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools, seen = _capture_gate(monkeypatch, workspace)
    (workspace.root / "mod.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    tools["edit_file"].invoke({"path": "mod.py", "old_str": "b = 2", "new_str": "b = 99"})
    summary, payload = seen[-1]
    assert payload["diff"].startswith("diff --git a/mod.py b/mod.py")
    assert "-b = 2" in payload["diff"] and "+b = 99" in payload["diff"]
    assert "+1 -1" in summary


def test_edit_file_with_a_whole_file_anchor_is_no_longer_deletions_only(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The live F34 case: a near-whole-file anchor blew the `content` preview's cap before any
    # `+` line appeared, so the operator saw their file as deletions with no replacement.
    tools, seen = _capture_gate(monkeypatch, workspace)
    old = "".join(f"line{i}\n" for i in range(300))
    (workspace.root / "big.py").write_text(old, encoding="utf-8")
    tools["edit_file"].invoke({"path": "big.py", "old_str": old, "new_str": "line0\nreplaced\n"})
    _, payload = seen[-1]
    # The whole-file `content` preview is still deletions-first (that is what it is), but the
    # structured diff now carries BOTH sides, and DiffView renders that field.
    assert "+replaced" in payload["diff"]
    assert payload["diff"].count("\n-") > 0


def test_edit_file_path_guard_still_precedes_any_diff_work(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools, seen = _capture_gate(monkeypatch, workspace)
    out = tools["edit_file"].invoke({"path": "../evil.py", "old_str": "a", "new_str": "b"})
    assert out.startswith("ERROR:")
    assert seen == []  # never reached the gate, so nothing was diffed


# --- F40: the gate must not hide the artifact it is asking about. ---
# The payload used to carry `content[:4000]` while the summary reported the TRUE length, with no
# marker and no other copy anywhere — for a new file the content is not on disk yet and the
# transcript carries the same truncated value. Measured live 2026-08-06: two authored test files
# (5,530 and 4,443 chars) were cut, and BOTH tails held a defect that was then approved, while the
# byte-identical defect inside the visible window was caught and rejected.


def test_a_real_authored_file_is_shown_in_full(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The exact size that was silently truncated live.
    tools, seen = _capture_gate(monkeypatch, workspace)
    content = "# " + ("x" * 5_528)
    tools["write_file"].invoke({"path": "tests/test_big.py", "content": content})
    summary, payload = seen[-1]
    assert payload["content"] == content, "the operator must see the whole file"
    assert str(len(content)) in summary


def test_content_over_the_cap_says_so_and_never_disagrees_with_the_summary(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools, seen = _capture_gate(monkeypatch, workspace)
    content = "y" * 40_000
    tools["write_file"].invoke({"path": "tests/test_huge.py", "content": content})
    summary, payload = seen[-1]
    shown = payload["content"]
    assert len(shown) < len(content)
    # The cut is DECLARED, with the amount hidden — never a silent slice.
    assert "not shown" in shown
    assert str(len(content) - 32_000) in shown
    # The summary still reports the true length, so payload and summary tell the same story.
    assert str(len(content)) in summary


# --- the operator's approval becomes a fact the tamper guard reads (F63, #65) ---
#
# THE load-bearing constraint is the actor check. An autonomous auto-approve that could sanction
# its own writes would retire ADR-0036 in silence — the point is that a PERSON with standing said
# yes to THIS content. These two tests together are the whole change.


def _gate_with_actor(monkeypatch: pytest.MonkeyPatch, workspace: Workspace, actor: str):
    from mosaera_policies import approval

    sanctioned: dict[str, str] = {}
    monkeypatch.setattr(
        approval,
        "request_approval",
        lambda action, summary, payload: approval.ApprovalDecision(approved=True, actor=actor),
    )
    tools = {
        t.name: t
        for t in build_repo_tools(
            workspace,
            SubprocessSandbox(workspace.root),
            approval_gate=True,
            operator_sanctioned=sanctioned,
        )
    }
    return tools, sanctioned


def test_a_human_approved_write_is_recorded_as_sanctioned(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaera_core.testintegrity import integrity_hash

    tools, sanctioned = _gate_with_actor(monkeypatch, workspace, "human")
    tools["write_file"].invoke(
        {"path": "tests/test_a.py", "content": "def test_x():\n    assert f()\n"}
    )
    assert sanctioned == {"tests/test_a.py": integrity_hash(workspace, "tests/test_a.py")}


def test_an_autonomous_auto_approve_may_NOT_sanction(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If this ever passes an entry through, ADR-0036 is retired without anyone deciding to."""
    tools, sanctioned = _gate_with_actor(monkeypatch, workspace, "autonomous")
    tools["write_file"].invoke(
        {"path": "tests/test_a.py", "content": "def test_x():\n    assert f()\n"}
    )
    assert sanctioned == {}


def test_a_denied_write_sanctions_nothing(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaera_policies import approval

    sanctioned: dict[str, str] = {}
    monkeypatch.setattr(
        approval,
        "request_approval",
        lambda action, summary, payload: approval.ApprovalDecision(
            approved=False, feedback="no", actor="human"
        ),
    )
    tools = {
        t.name: t
        for t in build_repo_tools(
            workspace,
            SubprocessSandbox(workspace.root),
            approval_gate=True,
            operator_sanctioned=sanctioned,
        )
    }
    tools["write_file"].invoke({"path": "tests/test_a.py", "content": "x = 1\n"})
    assert sanctioned == {}


# --- the operator is TOLD when an approval lowers the bar (#66, ADR-0087 §6) -------------------
#
# ADR-0087's stated residual: a human MAY authorize a weakening — they own the requirements, and
# refusing them would rebuild the deadlock the ADR exists to dissolve. What they may not do is
# authorize one WITHOUT BEING TOLD. So the write gate ANNOUNCES it and still honours the decision;
# the unattended paths (the Proctor's repair, the escalation amendment) refuse instead.


_TWO = "def test_a():\n    assert f() == 2\n    assert f() > 0\n"


def test_a_write_that_removes_an_assertion_says_so_at_the_gate(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    (workspace.root / "tests").mkdir(exist_ok=True)
    (workspace.root / "tests" / "test_a.py").write_text(_TWO, encoding="utf-8")
    tools, seen = _capture_gate(monkeypatch, workspace)
    tools["write_file"].invoke(
        {"path": "tests/test_a.py", "content": "def test_a():\n    assert f() == 2\n"}
    )
    summary, payload = seen[-1]
    assert "WEAKENS THE TEST BAR" in summary
    assert "test_a (2 -> 1 assertions)" in payload["weakening"]
    # And the approval is still HONOURED — informed, not blocked.
    assert (workspace.root / "tests" / "test_a.py").read_text() == (
        "def test_a():\n    assert f() == 2\n"
    )


def test_an_edit_that_removes_a_whole_test_says_so_at_the_gate(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    (workspace.root / "tests").mkdir(exist_ok=True)
    (workspace.root / "tests" / "test_a.py").write_text(
        _TWO + "\ndef test_b():\n    assert g() == 3\n", encoding="utf-8"
    )
    tools, seen = _capture_gate(monkeypatch, workspace)
    tools["edit_file"].invoke(
        {
            "path": "tests/test_a.py",
            "old_str": "\ndef test_b():\n    assert g() == 3\n",
            "new_str": "",
        }
    )
    assert "test_b (removed)" in seen[-1][1]["weakening"]


def test_a_strengthening_write_carries_no_warning(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The false-alarm direction. A gate that cries wolf on every test edit gets clicked through."""
    (workspace.root / "tests").mkdir(exist_ok=True)
    (workspace.root / "tests" / "test_a.py").write_text(_TWO, encoding="utf-8")
    tools, seen = _capture_gate(monkeypatch, workspace)
    tools["write_file"].invoke({"path": "tests/test_a.py", "content": _TWO + "    assert f()\n"})
    summary, payload = seen[-1]
    assert "WEAKENS" not in summary
    assert "weakening" not in payload


def test_a_new_test_file_carries_no_warning(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools, seen = _capture_gate(monkeypatch, workspace)
    tools["write_file"].invoke({"path": "tests/test_new.py", "content": _TWO})
    assert "weakening" not in seen[-1][1]


def test_a_non_test_file_carries_no_warning(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Source code is not a bar. `def test_helper` in app code must not trip this."""
    (workspace.root / "app.py").write_text("def test_helper():\n    assert f() == 1\n", "utf-8")
    tools, seen = _capture_gate(monkeypatch, workspace)
    tools["write_file"].invoke({"path": "app.py", "content": "def test_helper():\n    pass\n"})
    assert "weakening" not in seen[-1][1]


def test_tool_caches_never_reach_the_listing(source_repo: Path, tmp_path: Path) -> None:
    """Live validation 2026-08-19: the PM's repo overview is a SORTED listing capped at 160 paths,
    so dot-directories spend the budget first. On the LedgerCLI clone the first twelve paths were
    all cache — and `.ruff_cache` holds one entry per cached source file, so a large repo can push
    every real file out of the window. Asked what it could see, the PM said it had no visibility
    into the repository; it was reading a real listing that contained nothing about the project.

    Asserted through `build_overview`, the consumer that actually broke, rather than through the
    skip set — the set is the mechanism, the overview is the promise.
    """
    projects = tmp_path / "projects"
    ws = clone_project(str(source_repo), projects, "proj-cache")
    for rel in (
        ".pytest_cache/v/cache/nodeids",
        ".ruff_cache/0.15.20/1398130799826342069",
        ".mypy_cache/3.12/builtins.data.json",
        "htmlcov/index.html",
    ):
        p = Path(ws.root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")

    overview = build_overview(ws)

    for noise in (".pytest_cache", ".ruff_cache", ".mypy_cache", "htmlcov"):
        assert noise not in overview, f"{noise} is spending the PM's listing budget"
    assert "hello.py" in overview, "the real source file must still be there"


def test_tracked_build_output_is_still_visible(source_repo: Path, tmp_path: Path) -> None:
    """The other half of the same decision. `dist/`, `build/` and `*.egg-info/` are sometimes
    TRACKED — a built site can be the deliverable — and on the LedgerCLI project a tracked
    `src/budget_tracker.egg-info/` is the subject of three backlog items. Hiding it would hide
    the thing the work is about."""
    projects = tmp_path / "projects"
    ws = clone_project(str(source_repo), projects, "proj-dist")
    for rel in ("dist/app.js", "src/pkg.egg-info/PKG-INFO"):
        p = Path(ws.root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")

    overview = build_overview(ws)

    assert "dist/app.js" in overview
    assert "src/pkg.egg-info/PKG-INFO" in overview


def test_the_gate_names_the_agent_that_actually_asked(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A test-file gate raised by the Proctor read "Coder wants to write ...".

    That misattributes the one separation ADR-0013 exists to enforce — the coder may not author
    its own bar — at the exact moment the operator is deciding whether to allow a test write.
    Observed live 2026-08-20 on a `tests/test_cli_version.py` approval.
    """
    from mosaera_policies import approval

    seen: list[str] = []

    def _capture(action: str, summary: str, payload: dict) -> object:
        seen.append(summary)
        return approval.ApprovalDecision(approved=False, feedback="no")

    monkeypatch.setattr(approval, "request_approval", _capture)

    proctor = {
        t.name: t
        for t in build_repo_tools(
            workspace,
            SubprocessSandbox(workspace.root),
            approval_gate=True,
            write_prefix="tests/",
            actor="Proctor",
        )
    }
    proctor["write_file"].invoke({"path": "tests/test_new.py", "content": "def test_x(): pass\n"})
    assert seen and seen[0].startswith("Proctor wants to write")
    assert "Coder" not in seen[0]

    # …and the default is unchanged, so every existing coder gate reads exactly as before.
    seen.clear()
    coder = {
        t.name: t
        for t in build_repo_tools(workspace, SubprocessSandbox(workspace.root), approval_gate=True)
    }
    coder["write_file"].invoke({"path": "sub/new.txt", "content": "x"})
    assert seen and seen[0].startswith("Coder wants to write")


# --- F87: the probe must use the PROJECT's interpreter, not the engine's ---------------------
#
# Live 2026-08-21 (run 20260821-023819-4ad38a): `sandbox_exec` hardcoded `sys.executable`, which
# cannot import a `pip install -e .` package — that lives in the validation venv. So the coder's
# probes raised ModuleNotFoundError while validation's pytest imported the same package fine, and
# it spent 291,846 tokens concluding "network issues installing dependencies". Its code was correct
# and the suite passed 79/79. Same defect and fix as ADR-0049's B3 false-park.


def _venv(workspace: Workspace) -> Path:
    """Create a stub `.venv/bin/python` — a real FILE, which is what `--copies` guarantees and what
    the host-side check relies on."""
    p = workspace.root / ".venv" / "bin" / "python"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/bin/sh\n", encoding="utf-8")
    return p


def test_probe_uses_the_project_venv_when_it_exists(workspace: Workspace) -> None:
    _venv(workspace)
    fake = _FakeSandbox(stdout="ok")
    tools = {t.name: t for t in build_repo_tools(workspace, fake, enable_exec=True)}
    tools["sandbox_exec"].invoke({"code": "import budget_tracker"})
    # Relative, because every sandbox call runs with cwd=workspace.root.
    assert fake.calls[0]["cmd"][0] == ".venv/bin/python"


def test_probe_falls_back_to_the_engine_interpreter_with_no_venv(workspace: Workspace) -> None:
    fake = _FakeSandbox(stdout="ok")
    tools = {t.name: t for t in build_repo_tools(workspace, fake, enable_exec=True)}
    tools["sandbox_exec"].invoke({"code": "print(1)"})
    assert fake.calls[0]["cmd"][0] == sys.executable


def test_probe_falls_back_when_the_venv_python_is_not_a_real_file(workspace: Workspace) -> None:
    # A directory (or a dangling symlink, the cross-platform hazard `--copies` exists to avoid)
    # must NOT be treated as an interpreter — falling back is the safe direction.
    (workspace.root / ".venv" / "bin" / "python").mkdir(parents=True)
    fake = _FakeSandbox(stdout="ok")
    tools = {t.name: t for t in build_repo_tools(workspace, fake, enable_exec=True)}
    tools["sandbox_exec"].invoke({"code": "print(1)"})
    assert fake.calls[0]["cmd"][0] == sys.executable


def test_probe_explains_an_import_failure_before_the_venv_exists(workspace: Workspace) -> None:
    """The fresh-clone window the interpreter fix cannot reach: the package really IS uninstalled.
    ADR-0110 slice 1 moved the WORDING into the general fact block; the guarantee is unchanged."""
    fake = _FakeSandbox(stdout="ModuleNotFoundError: No module named 'budget_tracker'", exit_code=1)
    tools = {t.name: t for t in build_repo_tools(workspace, fake, enable_exec=True)}
    out = tools["sandbox_exec"].invoke({"code": "import budget_tracker"})
    assert "the install step has not run" in out
    assert "regardless of your code" in out
    assert "run_tests" in out
    assert "ModuleNotFoundError" in out  # the real output is still shown, never replaced


def test_probe_stays_silent_about_install_when_the_venv_is_warm(workspace: Workspace) -> None:
    # An import error WITH a venv present is a real defect in the coder's code — saying "maybe it
    # just isn't installed" there would excuse a genuine failure.
    _venv(workspace)
    fake = _FakeSandbox(stdout="ModuleNotFoundError: No module named 'typo'", exit_code=1)
    tools = {t.name: t for t in build_repo_tools(workspace, fake, enable_exec=True)}
    out = tools["sandbox_exec"].invoke({"code": "import typo"})
    assert "the install step has not run" not in out
    assert "regardless of your code" not in out


def test_the_fact_block_never_asserts_a_cause_for_the_failure(workspace: Workspace) -> None:
    """Facts now accompany EVERY failing probe (ADR-0110 slice 1 replaced the symptom-matched note
    with a general block). Safe only because the block reports state and never adjudicates — a block
    that offered causes would be the invented-cause defect wearing the uniform of the fix."""
    _venv(workspace)
    fake = _FakeSandbox(stdout="AssertionError: 3 != 4", exit_code=1)
    tools = {t.name: t for t in build_repo_tools(workspace, fake, enable_exec=True)}
    out = tools["sandbox_exec"].invoke({"code": "assert 3 == 4"})
    assert "AssertionError: 3 != 4" in out
    assert "the install step has not run" not in out
    for verdict in ("because", "caused by", "the reason", "due to"):
        assert verdict not in out.lower(), f"the block must not offer a cause ({verdict!r})"
