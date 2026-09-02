"""Delivery-provider detection (ADR-0112) — host EQUALITY, and honest ignorance.

The look-alike cases below are the point of the file. Detection decides which credential
a later slice spends and against which host, so a substring match here would recreate
the exact defect ``is_gitlab_source`` records having been fixed.
"""

from __future__ import annotations

from mosaera_connectors import detect_delivery_provider

GL = "https://gitlab.example.com"


def test_configured_gitlab_host_is_gitlab() -> None:
    assert detect_delivery_provider("https://gitlab.example.com/g/r.git", GL) == "gitlab"


def test_github_dot_com_is_github() -> None:
    assert detect_delivery_provider("https://github.com/owner/repo.git", GL) == "github"
    assert detect_delivery_provider("https://www.github.com/owner/repo", GL) == "github"


def test_scp_style_urls_resolve_for_both_providers() -> None:
    assert detect_delivery_provider("git@github.com:owner/repo.git", GL) == "github"
    assert detect_delivery_provider("git@gitlab.example.com:g/r.git", GL) == "gitlab"


def test_case_and_port_and_userinfo_do_not_change_the_answer() -> None:
    assert detect_delivery_provider("https://GitHub.COM/owner/repo.git", GL) == "github"
    assert detect_delivery_provider("https://user@github.com:443/o/r.git", GL) == "github"


def test_a_lookalike_host_is_not_github() -> None:
    """The substring trap: every one of these contains 'github.com'."""
    assert detect_delivery_provider("https://github.com.evil.io/o/r.git", GL) == "unknown"
    assert detect_delivery_provider("https://evil.io/github.com/o/r.git", GL) == "unknown"
    assert detect_delivery_provider("git@github.com.evil.io:o/r.git", GL) == "unknown"


def test_a_lookalike_gitlab_host_is_not_gitlab() -> None:
    assert detect_delivery_provider("https://gitlab.example.com.evil.io/g/r.git", GL) == "unknown"


def test_github_enterprise_is_unknown_not_github() -> None:
    """GHES is indistinguishable from any other self-hosted forge by URL alone; saying
    'unknown' is the honest answer, and it fails closed rather than at the finish line."""
    assert detect_delivery_provider("https://github.acme-corp.com/o/r.git", GL) == "unknown"


def test_a_local_path_is_unknown() -> None:
    assert detect_delivery_provider("/home/me/projects/thing", GL) == "unknown"
    assert detect_delivery_provider("", GL) == "unknown"


def test_the_configured_gitlab_wins_over_the_github_default() -> None:
    """A deployment that self-hosts GitLab *at* github.com is absurd, but the precedence
    must still be decidable and must favour the operator's own configuration."""
    assert detect_delivery_provider("https://github.com/o/r.git", "https://github.com") == "gitlab"


def test_an_unset_gitlab_url_does_not_swallow_every_source() -> None:
    """``is_gitlab_source`` requires a non-empty configured host; with none, a GitHub
    source must still resolve to github rather than to a vacuous gitlab match."""
    assert detect_delivery_provider("https://github.com/o/r.git", "") == "github"
    assert detect_delivery_provider("https://elsewhere.io/o/r.git", "") == "unknown"
