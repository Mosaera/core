"""How to make a prerequisite usable HERE — or why we will not try.

Split out of `prereqs.py` at the god-file ceiling, on the seam the file already had: what this
machine HAS is a survey, and what to DO about a gap is a plan. `prereqs` answers the first and
re-exports this module whole, so `from mosaera_core.prereqs import plan_for` keeps working — the
split is a shape change, not an interface one.

One cohesive question: given a prerequisite, a platform and a REASON it is unusable, what is the
command we stand behind? "Install it" is only one of the answers — a stopped Docker needs starting,
a permission problem needs a group and a re-login, and macOS needs a runtime whose licence we are
allowed to accept (ADR-0118).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mosaera_core.prereqs import Platform, Prereq

DOCKER_SCRIPT = "curl -fsSL https://get.docker.com | sudo sh"

DOCKER_DOCS = "https://docs.docker.com/engine/install/"
DOCKER_DESKTOP = "https://docs.docker.com/desktop/install/mac-install/"
#: WSL has its own page because it has its own two routes — Desktop integration, or systemd plus
#: the engine inside the distro — and the mac page describes neither.
DOCKER_DESKTOP_WSL = "https://docs.docker.com/desktop/wsl/"
COLIMA_DOCS = "https://colima.run"
NODE_DOCS = "https://nodejs.org/"
HOMEBREW = "https://brew.sh"

#: The after-the-fact truth for a `usermod`, and it differs by kind of Linux. Under WSL the shell
#: you log back into is the same distro instance, so the group never takes effect until the whole
#: distro is stopped from the Windows side.
_RELOGIN = "Log out and back in before Docker works without sudo."
_RELOGIN_WSL = (
    "Run `wsl --shutdown` from PowerShell and reopen this distro before Docker works without sudo."
)

#: `package -> command`, per family. The package NAME is supplied by each prerequisite, because the
#: same tool is named differently in different repositories and only the prerequisite knows which.
_INSTALL: dict[str, str] = {
    "debian": "sudo apt-get update && sudo apt-get install -y {pkg}",
    "fedora": "sudo dnf install -y {pkg}",
    "arch": "sudo pacman -S --needed --noconfirm {pkg}",
    "suse": "sudo zypper install -y {pkg}",
    "alpine": "sudo apk add --no-cache {pkg}",
}


def package_command(plat: Platform, packages: dict[str, str]) -> str:
    """The install command for this platform, or "" when we cannot name one.

    `packages` is keyed by family plus an optional "darwin". A family absent from the mapping means
    this tool is not packaged there under a name we have verified — and we say nothing rather than
    invent one.
    """
    if plat.is_macos:
        # No Homebrew, no command. `brew install git` on a Mac that has no brew is a command that
        # cannot run, and the wizard reported its failure as git's rather than Homebrew's.
        pkg = packages.get("darwin")
        if not (pkg and plat.brew):
            return ""
        # The RESOLVED binary. `brew` may be installed and not on this process's PATH (see
        # `prereqs.brew_bin`), and a command that says `brew` would then fail for the one operator
        # the detection just went out of its way to include.
        from mosaera_core.prereqs import brew_bin

        return f"{brew_bin() or 'brew'} install {pkg}"
    template = _INSTALL.get(plat.family, "")
    pkg = packages.get(plat.family)
    return template.format(pkg=pkg) if template and pkg else ""


@dataclass(frozen=True)
class Step:
    """One command in an install plan, and whether it needs root."""

    command: str
    privileged: bool = False


@dataclass(frozen=True)
class Plan:
    """How to install one prerequisite here — or why we will not try."""

    steps: tuple[Step, ...] = ()
    #: Something true the operator must know AFTER it runs (a re-login, a manual step).
    note: str = ""
    #: Where to read when we cannot do it for them.
    docs: str = ""
    #: What this plan DOES, for the row that offers it. "Install" is wrong for a Docker that is
    #: already installed and merely stopped — the wizard was telling operators to re-download and
    #: re-run the vendor script in order to start a service.
    verb: str = "Install"
    #: What to CALL this action when its name is not the prerequisite's name. Empty means they are
    #: the same thing and the row says so. macOS closes the Docker gap by installing Colima, and a
    #: row reading "Install Docker   brew install colima …" would be naming one product and running
    #: another.
    offer: str = ""

    @property
    def runnable(self) -> bool:
        return bool(self.steps)


#: Why a prerequisite is not usable. The distinction matters because the FIX differs: a missing
#: Docker needs installing, a stopped one needs starting, and a permission problem needs a group and
#: a re-login. All three used to be offered the same three-step vendor install.
ABSENT, DAEMON_DOWN, NO_PERMISSION = "absent", "daemon_down", "no_permission"


def plan_for(prereq: Prereq, plat: Platform, reason: str = ABSENT) -> Plan:
    """How to make `prereq` usable on `plat` — which is not always "install it".

    A Docker that is installed but stopped needs starting, not re-downloading — which is what the
    wizard used to tell an operator to do.
    """
    if prereq.key in ("docker", "compose"):
        return _docker_plan(plat, reason)

    command = package_command(plat, prereq.packages)
    if not command:
        if plat.is_macos and not plat.brew and prereq.packages.get("darwin"):
            # Name the actual blocker. NOT runnable: brew's installer is interactive and wants
            # sudo, the invisible deadlock under Textual's raw mode that ADR-0116 engineered around.
            return Plan(
                docs=HOMEBREW,
                note="Homebrew is not installed. Install it from https://brew.sh, then re-run.",
            )
        return Plan(docs=prereq.docs)
    return Plan(steps=(Step(command, privileged=not plat.is_macos),), docs=prereq.docs)


def _brew() -> str:
    """`brew`, spelled the way this machine can actually run it."""
    from mosaera_core.prereqs import brew_bin

    return brew_bin() or "brew"


def _docker_plan(plat: Platform, reason: str) -> Plan:
    """Docker and Compose, dispatched REASON-first and platform-second.

    It used to be platform-first, gated on `is_linux`, and both halves were wrong: WSL reports
    Linux and was told to `systemctl`, while macOS never reached the reason branch at all — so a
    Docker Desktop that was merely *stopped* got the link for installing it.
    """
    # macOS folds NO_PERMISSION into DAEMON_DOWN: on Desktop the socket is owned by the user, so a
    # denial there almost always means the VM is not up rather than a group.
    if reason == DAEMON_DOWN or (reason == NO_PERMISSION and plat.is_macos):
        if plat.is_macos:
            return Plan(
                steps=(Step("open -a Docker", privileged=False),),
                docs=DOCKER_DESKTOP,
                verb="Start",
            )
        if plat.wsl:
            return Plan(
                docs=DOCKER_DESKTOP_WSL,
                note="Start Docker Desktop on Windows, or start the engine inside this distro.",
                verb="Start",
            )
        if plat.is_linux:
            return Plan(
                steps=(Step("sudo systemctl enable --now docker", privileged=True),),
                docs=DOCKER_DOCS,
                verb="Start",
            )
        return Plan(docs=DOCKER_DOCS, verb="Start")

    if reason == NO_PERMISSION and plat.is_linux:
        return Plan(
            steps=(Step("sudo usermod -aG docker $USER", privileged=True),),
            note=_RELOGIN_WSL if plat.wsl else _RELOGIN,
            docs=DOCKER_DESKTOP_WSL if plat.wsl else DOCKER_DOCS,
            verb="Grant this user access to",
        )

    if plat.is_macos:
        # DOCKER DESKTOP IS NOT OURS TO ACCEPT. Its installer does support `--accept-license`, so
        # the automation is possible — but the licence it accepts is a commercial subscription
        # agreement (free under 250 employees AND $10M revenue; paid above either, and paid for
        # government), and agreeing to that on an operator's behalf is not a thing a setup wizard
        # may do. `open -a Docker --args --accept-license` is also inert, so the Homebrew cask
        # route dead-ends at a GUI licence screen no wizard can drive (docker/for-mac#6979).
        #
        # Colima is the route we can own end to end: no sudo, no agreement, open source, and the
        # sandbox never notices — it shells out to the `docker` CLI and probes `docker info`, so a
        # Colima context satisfies it unmodified.
        if plat.brew:
            return Plan(
                steps=(
                    Step(f"{_brew()} install colima docker docker-compose", privileged=False),
                    # `brew install docker-compose` alone does NOT make `docker compose` work, and
                    # `docker compose version` is exactly what the compose probe runs. Homebrew
                    # ships it as a binary and leaves the plugin link to you; `brew --prefix`
                    # rather than a literal path because it is /opt/homebrew on Apple Silicon and
                    # /usr/local on Intel.
                    Step(
                        "mkdir -p ~/.docker/cli-plugins && ln -sfn "
                        f'"$({_brew()} --prefix)/opt/docker-compose/bin/docker-compose" '
                        "~/.docker/cli-plugins/docker-compose",
                        privileged=False,
                    ),
                    Step("colima start", privileged=False),
                ),
                offer="Colima (a Docker-compatible runtime)",
                note=(
                    "Colima runs the containers; the `docker` command works as usual. It starts "
                    "with modest defaults — if an image build runs out of room, `colima stop` then "
                    "`colima start --cpu 4 --memory 8`. Prefer Docker Desktop instead? Install it "
                    f"yourself from {DOCKER_DESKTOP}: it carries a subscription agreement, and "
                    "accepting one on your behalf is not something this wizard will do."
                ),
                docs=COLIMA_DOCS,
            )
        return Plan(
            docs=DOCKER_DESKTOP,
            note=(
                # "which needs neither" was read as "Colima needs neither route", which is
                # nonsense — Colima needs Homebrew, one of the two. Say what each route costs
                # instead of trailing a pronoun with nothing clear to attach to.
                "Two ways forward. Install Docker Desktop yourself: it includes Compose, and "
                "carries a subscription agreement this wizard will not accept on your behalf. "
                f"Or install Homebrew ({HOMEBREW}) and run this again — the wizard can then set "
                "up Colima for you, which is open source and has no agreement to accept."
            ),
        )
    if plat.wsl:
        # Two legitimate routes and no way to tell which is wanted — name both, install neither.
        return Plan(
            docs=DOCKER_DESKTOP_WSL,
            note=(
                "Either install Docker Desktop on Windows and enable WSL integration for this "
                "distro (Settings → Resources → WSL Integration), or enable systemd in "
                "/etc/wsl.conf and install Docker Engine here."
            ),
        )
    if not plat.is_linux:
        return Plan(docs=DOCKER_DOCS)
    return Plan(
        steps=(
            Step(DOCKER_SCRIPT, privileged=True),
            Step("sudo systemctl enable --now docker", privileged=True),
            Step("sudo usermod -aG docker $USER", privileged=True),
        ),
        note=_RELOGIN,
        docs=DOCKER_DOCS,
    )
