import shutil
import subprocess
from pathlib import Path

import pytest
from mosaera_connectors import github as gh_mod
from mosaera_connectors.github import (
    assemble_pull_request,
    open_pull_request,
    push_branch,
    push_url,
)
from mosaera_connectors.redact import scrub_credentials


def test_assemble_pull_request_title_and_body() -> None:
    plan = assemble_pull_request(
        task="Fix the failing add() test",
        run_id="20260702-1",
        branch="mosaera/20260702-1",
        report_text="## Diff\n```diff\n- a - b\n+ a + b\n```",
    )
    assert plan.title == "mosaera: Fix the failing add() test"
    assert plan.branch == "mosaera/20260702-1"
    assert plan.base == "main"
    assert plan.draft is True
    assert "run `20260702-1`" in plan.body
    assert "do not self-merge" in plan.body
    assert "a + b" in plan.body  # report embedded


def test_long_title_is_truncated() -> None:
    plan = assemble_pull_request(task="x" * 200, run_id="r", branch="b", report_text="")
    assert len(plan.title) <= 72
    assert plan.title.endswith("…")


def test_open_pull_request_dry_run_builds_commands(tmp_path: Path) -> None:
    plan = assemble_pull_request(
        task="do a thing", run_id="r1", branch="mosaera/r1", report_text="body", base="develop"
    )
    result = open_pull_request(tmp_path, plan, dry_run=True)
    assert result.dry_run is True
    assert result.opened is False
    push, gh = result.commands
    assert push == ["git", "push", "-u", "origin", "mosaera/r1"]
    assert gh[:3] == ["gh", "pr", "create"]
    assert "--draft" in gh
    assert "--base" in gh and gh[gh.index("--base") + 1] == "develop"
    assert "--head" in gh and gh[gh.index("--head") + 1] == "mosaera/r1"


def test_open_pull_request_missing_gh(tmp_path: Path) -> None:
    plan = assemble_pull_request(task="t", run_id="r", branch="b", report_text="")
    result = open_pull_request(tmp_path, plan, gh_bin="definitely-not-gh-binary")
    assert not result.opened
    assert "not found" in result.error


# --- the SERVER path: token-authenticated push (ADR-0114) ------------------------
#
# `open_pull_request` above is the CLI path and is unchanged. These cover `push_branch`,
# the analogue of gitlab's `open_merge_request(push_only=True)`, and in particular the
# property test_gitlab.py pins for GitLab: the token must never reach a returned object.


def test_push_branch_dry_run_shows_a_TOKENLESS_remote(tmp_path: Path) -> None:
    result = push_branch(
        tmp_path,
        owner_repo="acme/widget",
        branch="mosaera/x",
        base="main",
        token="ghs_supersecret",
        dry_run=True,
    )
    assert result.dry_run is True and result.pushed is False
    assert result.push_cmd == ["git", "push", "https://github.com/acme/widget.git", "mosaera/x"]
    # The credential must not survive into anything a caller can read, log or serialize.
    assert "ghs_supersecret" not in " ".join(result.push_cmd)
    assert "x-access-token" not in " ".join(result.push_cmd)


def test_push_branch_ensure_base_is_visible_in_the_display_command(tmp_path: Path) -> None:
    result = push_branch(
        tmp_path,
        owner_repo="acme/widget",
        branch="mosaera/x",
        base="trunk",
        token="t",
        ensure_base=True,
        dry_run=True,
    )
    assert "trunk:trunk (if missing)" in result.push_cmd


def test_push_url_is_the_shape_github_requires_and_redact_already_strips() -> None:
    url = push_url("acme/widget", "ghs_tok")
    assert url == "https://x-access-token:ghs_tok@github.com/acme/widget.git"
    assert scrub_credentials(url) == "https://***@github.com/acme/widget.git"


def test_push_url_percent_encodes_the_token() -> None:
    """An unescaped '/' or '@' in userinfo silently retargets the push at another host."""
    url = push_url("acme/widget", "tok/with@slash")
    assert url == "https://x-access-token:tok%2Fwith%40slash@github.com/acme/widget.git"
    assert url.count("@") == 1


def test_a_failed_push_scrubs_and_caps_the_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Done:
        returncode = 1
        stdout = ""
        stderr = "fatal: https://x-access-token:ghs_leak@github.com/a/b.git rejected " + "y" * 500

    monkeypatch.setattr(gh_mod.subprocess, "run", lambda *a, **k: _Done())
    result = push_branch(tmp_path, owner_repo="a/b", branch="x", base="main", token="ghs_leak")
    assert result.pushed is False
    assert "ghs_leak" not in result.error, "a push error must never carry the credential"
    assert len(result.error) <= 200, "error strings are capped like every GitLab counterpart"


def test_a_hung_push_times_out_rather_than_holding_the_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _hang(*a: object, **k: object) -> object:
        raise gh_mod.subprocess.TimeoutExpired(cmd="git", timeout=120)

    monkeypatch.setattr(gh_mod.subprocess, "run", _hang)
    result = push_branch(tmp_path, owner_repo="a/b", branch="x", base="main", token="t")
    assert result.pushed is False and "timed out" in result.error


def test_a_missing_git_binary_is_an_error_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*a: object, **k: object) -> object:
        raise OSError("No such file or directory: 'git'")

    monkeypatch.setattr(gh_mod.subprocess, "run", _boom)
    result = push_branch(tmp_path, owner_repo="a/b", branch="x", base="main", token="t")
    assert result.pushed is False and "git" in result.error


# --- the initial push into a freshly created repository (ADR-0120 A1) -----------------


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Test-local git. Same argv-list, resolved-binary shape the production callers use, so the
    lint rules that protect those are satisfied here rather than suppressed."""
    git = shutil.which("git") or "git"
    return subprocess.run(  # noqa: S603 — argv list, no shell, fixed test inputs
        [git, *args], cwd=cwd, capture_output=True, text=True, check=False
    )


def _seed_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", "-b", "work", cwd=path)
    _git("config", "user.email", "t@example.com", cwd=path)
    _git("config", "user.name", "T", cwd=path)
    (path / "file.txt").write_text("hello\n")
    _git("add", "-A", cwd=path)
    _git("commit", "-qm", "initial", cwd=path)


def test_the_initial_push_sends_the_history_and_leaves_the_source_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real thing, against a real bare remote — the behaviour that decides whether a
    project ends up pointing at a repository with its code in it or an empty one.

    It also pins the isolation rule: `source_path` is a directory of the operator's, not a
    throwaway workspace, so the push must add no remote and leave `.git/config` as it found it.
    """
    source = tmp_path / "project"
    _seed_repo(source)
    remote = tmp_path / "remote.git"
    _git("init", "-q", "--bare", str(remote), cwd=tmp_path)
    before = (source / ".git" / "config").read_text()

    # Only the URL construction is stubbed — the push itself is a real `git push` at a real
    # bare repository, which is the part worth proving.
    monkeypatch.setattr(gh_mod, "push_url", lambda owner_repo, token, host="": str(remote))
    branch, err = gh_mod.push_existing_repository(source, owner_repo="o/r", token="unused")

    assert err is None, err
    assert branch == "work"
    listed = _git("ls-remote", "--heads", str(remote), cwd=tmp_path).stdout
    assert "refs/heads/work" in listed, "the project's branch must exist on the remote"
    assert (source / ".git" / "config").read_text() == before, (
        "the push must not modify the operator's own repository config"
    )


def test_a_source_that_is_not_a_repository_is_refused_rather_than_pushed_empty(
    tmp_path: Path,
) -> None:
    """Pushing nothing and calling it a sync is the failure this guards."""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    branch, err = gh_mod.push_existing_repository(plain, owner_repo="o/r", token="t")
    assert branch is None
    assert err is not None and "not a git repository" in err
