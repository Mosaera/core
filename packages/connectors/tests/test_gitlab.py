from pathlib import Path

from mosaera_connectors.gitlab import (
    _MR_URL_RE,
    _auth_source_url,
    assemble_merge_request,
    check_repo_access,
    is_gitlab_source,
    open_merge_request,
    project_from_source,
)


def test_project_from_source() -> None:
    assert project_from_source("https://gitlab.rengifo.me/mosaera/core.git") == "mosaera/core"
    assert project_from_source("git@gitlab.rengifo.me:mosaera/core.git") == "mosaera/core"
    assert project_from_source("https://gitlab.rengifo.me/g/sub/proj") == "g/sub/proj"


def test_is_gitlab_source() -> None:
    gl = "https://gitlab.rengifo.me"
    assert is_gitlab_source("https://gitlab.rengifo.me/mosaera/core.git", gl)
    assert not is_gitlab_source("https://github.com/x/y.git", gl)


def test_is_gitlab_source_rejects_look_alike_hosts() -> None:
    # The substring bug (host in source_url) matched all of these, so check_repo_access would
    # have injected the scoped PAT into an attacker-chosen host and ls-remote'd it.
    gl = "https://gitlab.rengifo.me"
    assert not is_gitlab_source("https://gitlab.rengifo.me.evil.io/x/y.git", gl)  # suffix
    assert not is_gitlab_source("https://evil.io/gitlab.rengifo.me/x/y.git", gl)  # in the path
    assert not is_gitlab_source("https://notgitlab.rengifo.me/x/y.git", gl)  # prefix
    assert not is_gitlab_source("https://gitlab.rengifo.me@evil.io/x/y.git", gl)  # userinfo trick


def test_is_gitlab_source_handles_scp_ssh_and_ports() -> None:
    # A host-equality fix must NOT break the legitimate non-https shapes, or it silently
    # disables pushes for them (is_gitlab_source gates delivery, not just the PAT check).
    gl = "https://gitlab.rengifo.me"
    assert is_gitlab_source("git@gitlab.rengifo.me:mosaera/core.git", gl)  # scp-style
    assert is_gitlab_source("ssh://git@gitlab.rengifo.me/mosaera/core.git", gl)  # ssh://
    assert is_gitlab_source("https://GITLAB.rengifo.me/x/y.git", gl)  # case-insensitive
    # A self-hosted GitLab on a non-default port, configured with the same port.
    assert is_gitlab_source(
        "https://gitlab.rengifo.me:8443/x/y.git", "https://gitlab.rengifo.me:8443"
    )


def test_assemble_merge_request() -> None:
    plan = assemble_merge_request(
        task="Add a REPO_OVERVIEW.md",
        run_id="r1",
        branch="mosaera/r1",
        report_text="### Reviewer\nVERDICT: APPROVE",
        base="main",
    )
    assert plan.title == "mosaera: Add a REPO_OVERVIEW.md"
    assert plan.branch == "mosaera/r1"
    assert plan.base == "main"
    assert "run `r1`" in plan.body
    assert "do not self-merge" in plan.body


def test_open_merge_request_dry_run_hides_token(tmp_path: Path) -> None:
    plan = assemble_merge_request("do a thing", "r1", "mosaera/r1", "body")
    result = open_merge_request(
        tmp_path,
        plan,
        project="mosaera/core",
        gitlab_url="https://gitlab.rengifo.me",
        token="SECRET-TOKEN",
        dry_run=True,
    )
    assert result.dry_run and not result.opened
    joined = " ".join(result.push_cmd)
    # The token must never appear in the display command.
    assert "SECRET-TOKEN" not in joined
    assert result.push_cmd[:2] == ["git", "push"]
    # MR is created via push-options (write_repository only) — no REST/api endpoint.
    assert "merge_request.create" in joined
    assert "merge_request.target=main" in joined
    assert result.mr_endpoint == "(push-options)"


def test_stacked_mr_omits_remove_source_branch_and_targets_predecessor(tmp_path: Path) -> None:
    # Per-item stacked MRs (ADR-0021): the source branch must NOT be auto-deleted on
    # merge (it's a later item's target) and the target is the predecessor's branch,
    # not the base. Both are just push-options the caller controls.
    plan = assemble_merge_request(
        "item B", "run-b", "mosaera/item-2", "body", base="mosaera/item-1"
    )
    result = open_merge_request(
        tmp_path,
        plan,
        project="mosaera/core",
        gitlab_url="https://gitlab.rengifo.me",
        token="SECRET-TOKEN",
        remove_source_branch=False,
        dry_run=True,
    )
    joined = " ".join(result.push_cmd)
    assert "merge_request.remove_source_branch" not in joined  # would orphan item-3's target
    assert "merge_request.target=mosaera/item-1" in joined  # stacked on the predecessor
    # The default (whole-project MR) still requests source-branch cleanup.
    project_plan = assemble_merge_request("proj", "p1", "mosaera/project-p1", "body")
    project_result = open_merge_request(
        tmp_path,
        project_plan,
        project="mosaera/core",
        gitlab_url="https://gitlab.rengifo.me",
        token="SECRET-TOKEN",
        dry_run=True,
    )
    assert "merge_request.remove_source_branch" in " ".join(project_result.push_cmd)


def test_mr_url_parsed_from_push_stderr() -> None:
    stderr = (
        "remote: \n"
        "remote: View merge request for mosaera/project-x:\n"
        "remote:   https://gitlab.rengifo.me/mosaera/site/-/merge_requests/7\n"
        "To https://gitlab.rengifo.me/mosaera/site.git\n"
    )
    match = _MR_URL_RE.search(stderr)
    assert match is not None
    assert match.group(0) == "https://gitlab.rengifo.me/mosaera/site/-/merge_requests/7"


def test_auth_source_url_and_check_repo_access() -> None:
    assert _auth_source_url("https://gitlab.rengifo.me/g/r.git", "tok") == (
        "https://oauth2:tok@gitlab.rengifo.me/g/r.git"
    )
    assert _auth_source_url("git@host:g/r.git", "tok") == "git@host:g/r.git"  # ssh untouched
    # Finding M-1: the ls-remote path now shares the scheme-safe injector, so it must NOT put the
    # PAT on cleartext http to a NETWORKED host (the exact guard the clone path already had) —
    # while http to a loopback dev host is still injected.
    assert _auth_source_url("http://gitlab.rengifo.me/g/r.git", "tok") == (
        "http://gitlab.rengifo.me/g/r.git"  # networked http → token withheld
    )
    assert _auth_source_url("http://localhost/g/r.git", "tok") == (
        "http://oauth2:tok@localhost/g/r.git"  # loopback http → injected
    )
    # A nonexistent local repo → ls-remote fails → an error string (never raises).
    assert check_repo_access("/nonexistent/repo/path", "") is not None


def test_open_merge_request_ensure_base_dry_run(tmp_path: Path) -> None:
    plan = assemble_merge_request("do a thing", "r1", "mosaera/project-r1", "body")
    result = open_merge_request(
        tmp_path,
        plan,
        project="mosaera/site",
        gitlab_url="https://gitlab.rengifo.me",
        token="SECRET-TOKEN",
        ensure_base=True,
        dry_run=True,
    )
    joined = " ".join(result.push_cmd)
    assert "main:main" in joined  # base push is part of the plan
    assert "SECRET-TOKEN" not in joined
