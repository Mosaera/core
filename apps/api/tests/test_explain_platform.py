"""The sentence in an error message is the command the install plan would run.

`explain` used to carry its own literals for the three Docker failures — `sudo systemctl start
docker`, a `usermod` with "then log out and back in", and `docker-compose-plugin`, which is
Debian's name for it. Every one was wrong somewhere: no systemd under WSL, no `systemctl` at all on
macOS, and a package name that only exists on one family. They are now resolved through
`mosaera_core.prereqs`, so a screen and an install row cannot say different things about the same
machine.

These live in their own file rather than in `test_setup_flow.py`, which is already past 900 lines.
"""

from __future__ import annotations

import pytest
from mosaera_api.setup.explain import explain
from mosaera_core.prereqs import DAEMON_DOWN, NO_PERMISSION, PREREQS, Platform, plan_for

_DAEMON_DOWN_RAW = "Cannot connect to the Docker daemon at unix:///var/run/docker.sock"
_DENIED_RAW = "permission denied while trying to connect to the Docker daemon socket"

_FEDORA = Platform("linux", "fedora", "Fedora")
_WSL = Platform("linux", "debian", "Ubuntu (WSL)", wsl=True)
_MAC = Platform("darwin", "", "macOS", brew=True)


def _docker():
    return next(p for p in PREREQS if p.key == "docker")


@pytest.mark.parametrize("plat", (_FEDORA, _WSL, _MAC), ids=("fedora", "wsl", "macos"))
@pytest.mark.parametrize(
    ("raw", "reason"), ((_DAEMON_DOWN_RAW, DAEMON_DOWN), (_DENIED_RAW, NO_PERMISSION))
)
def test_the_action_is_what_the_table_would_run(plat: Platform, raw: str, reason: str) -> None:
    action = explain(raw, plat).action
    plan = plan_for(_docker(), plat, reason)
    for step in plan.steps:
        assert step.command in action, (plat.pretty, reason)
    if plan.note:
        assert plan.note in action
    assert action, "an explained failure with no action is the silence this module exists to fix"


@pytest.mark.parametrize("raw", (_DAEMON_DOWN_RAW, _DENIED_RAW))
@pytest.mark.parametrize("plat", (_WSL, _MAC), ids=("wsl", "macos"))
def test_no_systemctl_where_there_is_no_systemd(plat: Platform, raw: str) -> None:
    """The defect this file exists for: both wordings were emitted verbatim on every platform."""
    assert "systemctl" not in explain(raw, plat).action


def test_the_wsl_relogin_advice_is_the_one_that_works_there() -> None:
    assert "wsl --shutdown" in explain(_DENIED_RAW, _WSL).action
    assert "Log out and back in" in explain(_DENIED_RAW, _FEDORA).action


def test_a_missing_compose_plugin_is_not_answered_with_a_debian_package_name() -> None:
    raw = "docker: 'compose' is not a docker command."
    assert "docker-compose-plugin" not in explain(raw, _FEDORA).action
    assert "get.docker.com" in explain(raw, _FEDORA).action  # the one method that brings the plugin
    # macOS: Homebrew puts the Compose binary on PATH and leaves the CLI-plugin link to you, so
    # `docker compose version` — what the probe runs — fails while `docker-compose` works. The
    # answer is the link, not a reinstall of the runtime (ADR-0118).
    mac_action = explain(raw, _MAC).action
    assert "cli-plugins" in mac_action
    assert "brew install" not in mac_action, "a missing link is not a missing package"


def test_the_platform_is_optional_and_defaults_to_this_machine() -> None:
    """Every caller that has no `SetupApp` in scope relies on this."""
    assert explain(_DAEMON_DOWN_RAW).recognised
