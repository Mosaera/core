"""The prerequisite table — the thing that was wrong in a way that would break a machine.

Every branch here was previously unreachable on any single developer's box, which is exactly how
`apt-get install -y node` shipped: the Debian path could only be exercised on Debian. Platform and
`/etc/os-release` are both injectable so all of them run everywhere.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from mosaera_core._prereq_plans import _INSTALL
from mosaera_core.prereqs import (
    ABSENT,
    DAEMON_DOWN,
    DOCKER_DESKTOP,
    DOCKER_SCRIPT,
    HOMEBREW,
    NO_PERMISSION,
    PREREQS,
    Found,
    Platform,
    classify_docker_failure,
    detect_platform,
    package_command,
    plan_for,
)

_RELEASES = {
    "debian": 'ID=ubuntu\nID_LIKE=debian\nPRETTY_NAME="Ubuntu 24.04 LTS"',
    "fedora": 'ID="rocky"\nID_LIKE="rhel centos fedora"',
    "arch": "ID=arch",
    "suse": 'ID=opensuse-tumbleweed\nID_LIKE="opensuse suse"',
    "alpine": "ID=alpine",
}


@pytest.mark.parametrize(("family", "release"), sorted(_RELEASES.items()))
def test_each_family_is_recognised_from_its_os_release(family: str, release: str) -> None:
    # ID_LIKE first, so derivatives (Ubuntu, Rocky, Manjaro) work without an entry each.
    assert detect_platform(os_release=release, system="Linux").family == family


def test_an_unrecognised_distribution_is_admitted_rather_than_guessed() -> None:
    plat = detect_platform(os_release="ID=nixos", system="Linux")
    assert plat.family == "" and plat.known is False


def test_macos_is_detected_without_reading_os_release() -> None:
    # It used to reach the /etc/os-release branch, throw OSError, and fall through to a LINUX
    # installer offered to a Mac.
    plat = detect_platform(system="Darwin")
    assert plat.is_macos and plat.pretty == "macOS"


def test_node_is_never_the_package_called_node() -> None:
    """The defect that made this file exist.

    On Debian and Ubuntu the package `node` is an amateur packet radio program. Passing the BINARY
    name to a package manager installed it, and the wizard ran the command rather than printing it.
    """
    node = next(p for p in PREREQS if p.key == "node")
    for family, release in _RELEASES.items():
        plat = detect_platform(os_release=release, system="Linux")
        command = package_command(plat, node.packages)
        assert "nodejs" in command, (family, command)
        assert not command.split()[-1] == "node", (family, command)


def test_no_platform_is_offered_another_tools_command() -> None:
    """The second defect: an unmatched distribution returned the Docker installer for EVERY tool, so
    choosing "install git" installed Docker."""
    for release in [*_RELEASES.values(), "ID=nixos"]:
        plat = detect_platform(os_release=release, system="Linux")
        for prereq in PREREQS:
            plan = plan_for(prereq, plat)
            if prereq.key in ("docker", "compose") or not plan.runnable:
                continue
            joined = " ".join(s.command for s in plan.steps)
            assert "get.docker.com" not in joined, (prereq.key, joined)


def test_docker_brings_compose_and_a_usable_daemon() -> None:
    """Installing the engine alone is not enough, and this is the case that proves it: on Fedora
    `docker` resolves to moby-engine and `docker compose` is a SEPARATE package. Docker's own script
    installs the compose plugin; the daemon still has to be enabled and the user added to the
    group."""
    plat = detect_platform(os_release=_RELEASES["fedora"], system="Linux")
    plan = plan_for(next(p for p in PREREQS if p.key == "docker"), plat)
    commands = [s.command for s in plan.steps]
    assert commands[0] == DOCKER_SCRIPT
    assert any("enable --now docker" in c for c in commands)
    assert any("usermod -aG docker" in c for c in commands)
    assert plan.note  # the re-login, which is otherwise a mystery
    assert all(s.privileged for s in plan.steps)


def test_macos_is_told_about_docker_desktop_not_handed_a_linux_installer() -> None:
    plan = plan_for(next(p for p in PREREQS if p.key == "docker"), Platform("darwin", "", "macOS"))
    assert not plan.runnable  # a signed application is not ours to install for someone
    assert "desktop" in plan.docs


def test_every_prereq_can_always_say_something_useful() -> None:
    # Either a command we stand behind, or where to read. Never silence, and never a guess.
    for release in [*_RELEASES.values(), "ID=nixos"]:
        plat = detect_platform(os_release=release, system="Linux")
        for prereq in PREREQS:
            plan = plan_for(prereq, plat)
            assert plan.runnable or plan.docs, (prereq.key, plat.family)


def test_every_prereq_states_what_it_is_for() -> None:
    # A newcomer asked to install Docker deserves to know what it is used for, not just a name.
    for prereq in PREREQS:
        assert prereq.purpose and not prereq.purpose.endswith(".")


# --- the package matrix, on every family rather than only the one I run --------------------------
#
# Every test in this file used to pass `Platform("linux", "fedora", …)`. That table is where the
# original defect lived: derived from binary names, it put `apt-get install -y node` — an amateur
# packet-radio program — and `install -y docker` — not the engine — in front of operators. A
# matrix that only Fedora exercises is a matrix nobody checks.

_LINUX_FAMILIES = ("debian", "fedora", "arch", "suse", "alpine")


def _plat(family: str) -> Platform:
    return Platform("linux", family, family.title())


@pytest.mark.parametrize("family", _LINUX_FAMILIES)
@pytest.mark.parametrize("key", ("git", "node"))
def test_every_family_names_a_real_command_for_every_packaged_prereq(family: str, key: str) -> None:
    """Silence is a failure mode too: a family with no template and no package produced "", and the
    row then offered nothing at all."""
    prereq = next(p for p in PREREQS if p.key == key)
    command = package_command(_plat(family), prereq.packages)
    assert command, f"{key} on {family} resolves no command"
    assert "{pkg}" not in command, "the template was not filled"
    assert command.startswith("sudo "), f"{family} install is not privileged: {command}"


@pytest.mark.parametrize("family", _LINUX_FAMILIES)
def test_node_is_installed_by_its_package_name_not_its_binary_name(family: str) -> None:
    """`apt-get install -y node` installs `node` — the Amateur Packet Radio Node program. The
    package is `nodejs`. This is the exact bug that moved setup into the terminal."""
    node = next(p for p in PREREQS if p.key == "node")
    command = package_command(_plat(family), node.packages)
    assert "nodejs" in command
    assert not re.search(r"(?<![a-z])node(?![a-z])", command.replace("nodejs", "")), command


@pytest.mark.parametrize("family", _LINUX_FAMILIES)
def test_docker_never_comes_from_a_distribution_package(family: str) -> None:
    """`docker` is not the engine on several distributions (Fedora's is moby-engine), and the distro
    packages omit the compose v2 plugin the database step depends on. Docker's own script is the one
    method that brings both."""
    for key in ("docker", "compose"):
        prereq = next(p for p in PREREQS if p.key == key)
        assert package_command(_plat(family), prereq.packages) == ""
        plan = plan_for(prereq, _plat(family))
        assert "get.docker.com" in plan.steps[0].command


@pytest.mark.parametrize("family", (*_LINUX_FAMILIES, "darwin"))
@pytest.mark.parametrize("reason", (DAEMON_DOWN, NO_PERMISSION))
def test_the_repair_plans_apply_on_every_linux_family(family: str, reason: str) -> None:
    """They were only ever exercised on Fedora — and macOS never reached the reason branch at all,
    so a Docker Desktop that was merely stopped was handed the page for installing one."""
    docker = next(p for p in PREREQS if p.key == "docker")
    plan = plan_for(docker, _mac() if family == "darwin" else _plat(family), reason)
    assert plan.runnable
    assert "get.docker.com" not in plan.steps[0].command, "a repair is not a reinstall"
    assert plan.verb != "Install"


def test_macos_with_homebrew_is_offered_colima_rather_than_a_dead_end() -> None:
    """The decision CHANGED, and this test changed with it — see ADR-0118.

    It used to assert that macOS gets a documentation link and nothing else, on the reasoning that
    Docker Desktop is a signed application we may not install for someone. That reasoning still
    holds for Docker Desktop, and the licence is the sharper half of it. It does not hold for the
    machine: Colima closes the same gap with no sudo, no subscription agreement, and no product
    change, so a Mac with Homebrew was being handed a dead end for a reason that only ever applied
    to one of the two available routes.
    """
    mac = _mac()  # a Mac WITH Homebrew: the brew-less one is its own test below
    for key in ("docker", "compose"):
        prereq = next(p for p in PREREQS if p.key == key)
        plan = plan_for(prereq, mac)
        assert plan.runnable, "a Mac with Homebrew can be helped"
        assert "colima" in plan.steps[0].command
        # NEVER sudo. brew's own installer is interactive and wants root, which is the invisible
        # deadlock under Textual's raw mode that ADR-0116 engineered around; Colima needs neither.
        assert not any(step.privileged for step in plan.steps)
        # The row must name what it runs. "Install Docker  brew install colima …" names one
        # product and runs another.
        assert "Colima" in plan.offer
        # Docker Desktop stays offered — by hand, with the reason it is not automated.
        assert DOCKER_DESKTOP in plan.note

    # The ones brew genuinely packages still get a command — and node is `node` on brew, not nodejs.
    node = next(p for p in PREREQS if p.key == "node")
    assert package_command(mac, node.packages) == "brew install node"


def test_colima_plan_makes_the_compose_probe_actually_pass() -> None:
    """`brew install docker-compose` alone does NOT satisfy `docker compose version`.

    Homebrew installs Compose as a binary and leaves the CLI-plugin link to you, while
    `_probe_compose` runs `docker compose version` — the plugin form. Without the symlink the
    wizard would install Compose, report success, and then still show Compose as missing.
    """
    plan = plan_for(next(p for p in PREREQS if p.key == "compose"), _mac())
    commands = " ".join(step.command for step in plan.steps)
    assert "cli-plugins" in commands, "the plugin link is what the probe actually needs"
    # `brew --prefix`, never a literal: /opt/homebrew on Apple Silicon, /usr/local on Intel.
    assert "brew --prefix" in commands
    assert "/opt/homebrew" not in commands


def test_macos_without_homebrew_names_both_routes_and_installs_neither() -> None:
    plan = plan_for(next(p for p in PREREQS if p.key == "docker"), _mac(brew=False))
    assert not plan.runnable, "no brew, no command we can stand behind"
    assert DOCKER_DESKTOP in plan.docs
    assert HOMEBREW in plan.note, "the route that would let us help is named, not hidden"


def test_an_unmatched_platform_never_gets_another_tools_installer() -> None:
    """The regression this whole table replaced: every unmatched platform fell through to the Docker
    script, so "install git" ran `curl get.docker.com | sh`."""
    for plat in (Platform("linux", "", "Something"), Platform("freebsd", "", "FreeBSD")):
        for prereq in PREREQS:
            plan = plan_for(prereq, plat)
            for step in plan.steps:
                if prereq.key in ("docker", "compose"):
                    continue
                assert "get.docker.com" not in step.command, f"{prereq.key} on {plat.pretty}"
            assert plan.docs or plan.runnable, f"{prereq.key} on {plat.pretty} says nothing"


@pytest.mark.parametrize("family", _LINUX_FAMILIES)
def test_every_declared_family_has_an_install_template(family: str) -> None:
    """A family listed in `_FAMILIES` with no row in `_INSTALL` resolves to silence for every
    package — the two tables have to agree, and nothing else checks that they do."""
    assert family in _INSTALL


# --- the two platforms nobody here can run ------------------------------------------------------
#
# WSL reports `platform.system() == "Linux"` and carries Ubuntu's `/etc/os-release`, so every
# native-Linux command was aimed at it: `systemctl` on a distro with no systemd, and "log out and
# back in" for a group that only takes effect after `wsl --shutdown`. macOS was offered
# `brew install git` without Homebrew's presence ever being checked. Neither branch can be reached
# on this dev box, which is precisely why they are injected.


def _wsl(family: str = "debian") -> Platform:
    return Platform("linux", family, f"{family.title()} (WSL)", wsl=True)


def _mac(*, brew: bool = True) -> Platform:
    return Platform("darwin", "", "macOS", brew=brew)


def test_wsl_is_detected_from_proc_version() -> None:
    plat = detect_platform(
        os_release=_RELEASES["debian"],
        system="Linux",
        proc_version="Linux version 5.15.167.4-microsoft-standard-WSL2",
        env={},
    )
    assert plat.wsl and plat.is_linux and plat.family == "debian"


def test_wsl_is_detected_from_the_environment_when_proc_version_is_silent() -> None:
    """A process started by a service or `wsl -e` may see one tell and not the other."""
    plat = detect_platform(
        os_release=_RELEASES["debian"],
        system="Linux",
        proc_version="Linux version 6.1.0-generic",
        env={"WSL_DISTRO_NAME": "Ubuntu"},
    )
    assert plat.wsl


def test_native_linux_is_not_mistaken_for_wsl() -> None:
    """The negative twin, and the one that matters: a predicate that over-fires here tells a Fedora
    operator to run `wsl --shutdown`, which is nonsense on their machine."""
    for family, release in _RELEASES.items():
        plat = detect_platform(
            os_release=release,
            system="Linux",
            proc_version=f"Linux version 6.14.0-{family} (gcc 14) #1 SMP",
            env={},
        )
        assert not plat.wsl, family
        assert "(WSL)" not in plat.pretty


def test_pretty_says_wsl_so_every_screen_reports_it_without_a_branch() -> None:
    plat = detect_platform(
        os_release=_RELEASES["debian"], system="Linux", proc_version="microsoft", env={}
    )
    assert plat.pretty.endswith("(WSL)")


@pytest.mark.parametrize("family", _LINUX_FAMILIES)
@pytest.mark.parametrize("reason", (DAEMON_DOWN, NO_PERMISSION, "absent"))
def test_wsl_is_never_told_to_systemctl(family: str, reason: str) -> None:
    """There is no systemd in a WSL distro unless `/etc/wsl.conf` turns it on, and the common case
    is a Docker Desktop backend where the engine is not in the distro at all."""
    for key in ("docker", "compose"):
        prereq = next(p for p in PREREQS if p.key == key)
        plan = plan_for(prereq, _wsl(family), reason)
        assert all("systemctl" not in step.command for step in plan.steps), plan
        assert plan.docs or plan.runnable


def test_wsl_names_both_routes_rather_than_guessing_between_them() -> None:
    """Desktop integration and a native engine are both legitimate, and nothing here can tell which
    the operator wants — so it names both and installs neither."""
    docker = next(p for p in PREREQS if p.key == "docker")
    plan = plan_for(docker, _wsl())
    assert not plan.runnable
    assert "WSL Integration" in plan.note and "wsl.conf" in plan.note


def test_the_wsl_relogin_note_names_wsl_shutdown() -> None:
    """ "Log out and back in" is false there: the group takes effect when the DISTRO restarts."""
    docker = next(p for p in PREREQS if p.key == "docker")
    plan = plan_for(docker, _wsl(), NO_PERMISSION)
    assert "wsl --shutdown" in plan.note
    assert "Log out" not in plan.note


def test_a_stopped_docker_desktop_is_started_not_reinstalled() -> None:
    docker = next(p for p in PREREQS if p.key == "docker")
    plan = plan_for(docker, _mac(), DAEMON_DOWN)
    assert plan.steps == (plan.steps[0],) and plan.steps[0].command == "open -a Docker"
    assert not plan.steps[0].privileged  # nothing on macOS needs root here
    assert plan.verb == "Start"


def test_macos_without_homebrew_is_told_about_homebrew() -> None:
    """It used to emit `brew install git` unconditionally, run it, and report "`brew install git`
    did not succeed" — naming the command rather than the missing tool it needs."""
    for key in ("git", "node"):
        prereq = next(p for p in PREREQS if p.key == key)
        plan = plan_for(prereq, _mac(brew=False))
        assert not plan.runnable
        assert "brew.sh" in plan.docs and "Homebrew" in plan.note
        # And the positive twin, so the fix cannot be "never offer brew".
        assert plan_for(prereq, _mac(brew=True)).steps[0].command.startswith("brew install ")


@pytest.mark.parametrize("plat_name", ("wsl", "mac-brew", "mac-no-brew"))
def test_every_prereq_still_says_something_useful_off_linux(plat_name: str) -> None:
    """The `brew`-less Mac is a NEW silence risk: `package_command` returns "" there."""
    plat = {"wsl": _wsl(), "mac-brew": _mac(), "mac-no-brew": _mac(brew=False)}[plat_name]
    for prereq in PREREQS:
        plan = plan_for(prereq, plat)
        assert plan.runnable or plan.docs, (prereq.key, plat_name)


def test_git_is_the_same_package_name_everywhere() -> None:
    """`scripts/install.sh` depends on this. It needs its advice before a clone and before uv
    exists, so it cannot read this table — and the one fact it still states by hand is that the git
    package is called `git`. If a distribution ever disagrees, this fails and names the script."""
    git = next(p for p in PREREQS if p.key == "git")
    assert set(git.packages.values()) == {"git"}, git.packages


def test_docker_failure_is_classified_in_one_place() -> None:
    assert classify_docker_failure("Got permission denied while trying to connect") == NO_PERMISSION
    assert classify_docker_failure("Cannot connect to the Docker daemon") == DAEMON_DOWN
    assert classify_docker_failure("") == DAEMON_DOWN


# --- one origin, enforced -----------------------------------------------------------------------


def _live_strings(path: Path) -> list[str]:
    """Every string this module actually USES — docstrings excluded.

    Prose about a command is not a second origin for it; a string literal that reaches a screen is.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_a_host_command_has_exactly_one_origin() -> None:
    """`systemctl` lived in three modules: this table, `preflight_host`'s hardcoded repair, and
    `explain`'s action strings. Each was Linux-only wording emitted on every platform, and each was
    a place the others could drift away from. The table owns it; nothing else may hold a copy.

    This is the guard, not the fix — it is what would have caught the drift in the first place.

    The owner is `_prereq_plans.py` since the god-file split (ADR-0118): the table moved, the
    invariant did not. This test caught that move, which is the whole point of it.
    """
    root = Path(__file__).resolve().parents[3]
    owner = root / "packages" / "core" / "mosaera_core" / "_prereq_plans.py"
    holders = set()
    for base in (root / "packages", root / "apps"):
        for path in base.rglob("*.py"):
            if "/tests/" in path.as_posix() or "/.venv/" in path.as_posix():
                continue
            if any("systemctl" in s for s in _live_strings(path)):
                holders.add(path)
    assert holders == {owner}, f"systemctl is stated outside the table: {sorted(holders)}"


def test_a_plan_we_cannot_run_still_says_what_the_operator_can_do() -> None:
    """The guidance has to reach the SCREEN, not just the object.

    A Mac without Homebrew got "Docker — read <the Docker Desktop page>" and nothing else, because
    `screens.machine` never passed the plan's note to anything that renders. The advice that would
    have unblocked them — install Homebrew and this wizard can set up Colima — existed in the plan
    and was invisible (ADR-0118).
    """
    from mosaera_api.setup import screens

    plat = _mac(brew=False)
    found = [
        Found(
            prereq=p,
            present=p.key not in ("docker", "compose"),
            detail="not installed",
            reason=ABSENT,
            plan=plan_for(p, plat),
        )
        for p in PREREQS
    ]
    screen = screens.machine(found, [f for f in found if not f.present], plat)
    # In the BODY, which wraps. `#detail` is nowrap+ellipsis and truncated this to
    # "…(it includes C…", hiding the half that matters.
    assert HOMEBREW in screen.body, "the route that would let us help must be on screen"
    # The Desktop link is in the ROW; the note says "the page above" rather than repeating a
    # 50-character URL two lines below itself. Assert what the operator SEES, not one field of it.
    assert DOCKER_DESKTOP in " ".join(screen.choices), "and so must the one that needs no wizard"

    # A runnable plan has nothing to explain — the row IS the explanation.
    plat = _mac(brew=True)
    found = [
        Found(
            prereq=p,
            present=p.key not in ("docker", "compose"),
            detail="not installed",
            reason=ABSENT,
            plan=plan_for(p, plat),
        )
        for p in PREREQS
    ]
    plain = screens.machine(found, [f for f in found if not f.present], plat).body
    assert plain.strip() == "Required software, and the purpose of each."


def test_homebrew_off_the_path_is_still_homebrew(tmp_path: Path) -> None:
    """`shutil.which` alone was wrong on the machine it mattered on.

    Homebrew installs to `/opt/homebrew` (Apple Silicon) or `/usr/local` (Intel), and it is
    `~/.zprofile` running `brew shellenv` that puts either on PATH. A wizard launched from a shell
    that has not sourced that profile asks a machine WITH Homebrew whether it has Homebrew and is
    told no — and on macOS that answer decides whether the Docker gap can be closed at all
    (ADR-0118), so the mis-detection turns an installable machine into a dead end.
    """
    import mosaera_core.prereqs as prereqs_module

    fake = tmp_path / "opt" / "homebrew" / "bin" / "brew"
    fake.parent.mkdir(parents=True)
    fake.write_text("#!/bin/sh\n", encoding="utf-8")

    with (
        patch.object(prereqs_module.shutil, "which", lambda _n: None),
        patch.object(prereqs_module, "_BREW_CANDIDATES", (str(fake),)),
    ):
        assert prereqs_module.brew_bin() == str(fake)
        plat = detect_platform(system="Darwin")
        assert plat.brew, "a Mac with Homebrew off PATH is a Mac with Homebrew"

    # And with neither on PATH nor in a canonical place, it is honestly absent.
    with (
        patch.object(prereqs_module.shutil, "which", lambda _n: None),
        patch.object(prereqs_module, "_BREW_CANDIDATES", ()),
    ):
        assert prereqs_module.brew_bin() == ""
        assert not detect_platform(system="Darwin").brew


def test_node_without_npm_is_not_a_satisfied_prerequisite(monkeypatch) -> None:
    """The dashboard build runs `npm --prefix apps/web install` and `npm run build`. `node` alone
    is not that, and this file's own install plans spell the package as "nodejs npm" because the
    two are separable — so a row reading "Node 22 ✓" promised a build that died on
    `npm: command not found`."""
    from mosaera_core import prereqs

    monkeypatch.setattr(prereqs, "_run", lambda *_a, **_k: (0, "v22.3.0"))
    monkeypatch.setattr(
        prereqs.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None
    )
    ok, detail, _reason = prereqs._probe_node(None)
    assert ok is False
    assert "npm" in detail

    monkeypatch.setattr(prereqs.shutil, "which", lambda name: f"/usr/bin/{name}")
    ok, detail, _reason = prereqs._probe_node(None)
    assert ok is True
