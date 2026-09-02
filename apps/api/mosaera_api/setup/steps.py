"""What the wizard has to do, as data and pure functions — no terminal involved.

The screens render this; they do not decide it. Keeping the decisions here is what lets the whole
flow be tested without a tty, and it is the same reasoning that made the web flow's step machine a
pure module: a step's state is a question about the machine, not about the widget showing it.

EVERY STEP IS SKIPPED WHEN ALREADY SATISFIED, and every action is idempotent — `mosaera-setup` is
re-runnable by design, so running it on a configured box repairs rather than duplicates.
"""

from __future__ import annotations

import hashlib
import os
import select
import socket
import subprocess
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from mosaera_core.config import Settings
from mosaera_core.preflight_host import _image_tags, _run
from mosaera_memory import MemoryStore

from mosaera_api.setup.env_file import read_env_file

#: The bind that means "anything on the network". Named so ruff's S104 is answered once, at the
#: place where exposing the instance is the deliberate choice being offered.
_ALL_INTERFACES = "0.0.0.0"  # noqa: S104


@dataclass(frozen=True)
class Image:
    """A sandbox/scanner image and the Dockerfile that builds it."""

    tag: str
    dockerfile: str
    present: bool


def survey_images(settings: Settings) -> list[Image]:
    """Which of the four images exist. Uses the same `tag -> Dockerfile` map the readiness check
    reads, so the wizard cannot build a different set from the one `doctor` reports on."""
    out: list[Image] = []
    for tag, dockerfile in _image_tags(settings).items():
        code, _ = _run([settings.docker_bin, "image", "inspect", tag])
        out.append(Image(tag=tag, dockerfile=dockerfile, present=code == 0))
    return out


def build_image_argv(settings: Settings, image: Image) -> list[str]:
    """The build, as argv — never a shell string. The repo root is the context, exactly as
    `dev-up.sh` does it."""
    return [settings.docker_bin, "build", "-f", image.dockerfile, "-t", image.tag, "."]


def compose_project(repo_root: Path) -> str:
    """The Compose project THIS install owns.

    Read from the install's own `.env`, never from the ambient environment. `COMPOSE_PROJECT_NAME`
    exported in a shell outranks everything Compose reads from a file, so a leftover export — mine
    was `mosaera-stress` for an hour — silently retargets `down --volumes` at somebody else's
    project. Demonstrated: with it set, `config` reports that other project as the one a teardown
    would act on. Passing `-p` explicitly is the only precedence level above it.

    The derived name carries a digest of the install's real path, so two checkouts that happen to
    share a directory basename still own different containers, networks and volumes.
    """
    root = repo_root.resolve()
    stored = read_env_file(root / ".env").get("COMPOSE_PROJECT_NAME", "").strip()
    if stored:
        return stored
    base = "".join(c if c.isalnum() else "-" for c in root.name.lower()).strip("-") or "mosaera"
    digest = hashlib.sha256(str(root).encode()).hexdigest()[:6]
    return f"{base}-{digest}"


def ensure_compose_project(repo_root: Path) -> str:
    """Write this install's project name into its own `.env`, once.

    Recorded rather than only derived so that `make down` and `dev-up.sh` — which cannot compute the
    digest — act on the same project the wizard does, and so the identity is visible to whoever
    reads the file. An existing value is never overwritten.
    """
    from mosaera_api.setup.env_file import write_env_file

    name = compose_project(repo_root)
    if not read_env_file(repo_root / ".env").get("COMPOSE_PROJECT_NAME", "").strip():
        with suppress(OSError):  # a read-only .env is reported by the caller that writes settings
            write_env_file(repo_root / ".env", {"COMPOSE_PROJECT_NAME": name})
    return name


def compose_argv(
    docker_bin: str, repo_root: Path, *rest: str, project: str | None = None
) -> list[str]:
    """A compose invocation pinned to this install, in both axes.

    `-p` fixes WHICH project is acted on — above any ambient `COMPOSE_PROJECT_NAME`.
    `--project-directory` fixes where relative paths resolve, and is what `.env` is read from.
    """
    return [
        docker_bin,
        "compose",
        "-p",
        project or compose_project(repo_root),
        "--project-directory",
        str(repo_root),
        "-f",
        "infra/docker/compose.yaml",
        *rest,
    ]


def compose_down_argv(
    settings: Settings, repo_root: Path | None = None, *, volumes: bool = False
) -> list[str]:
    """Tear this install's Postgres down, optionally taking its data volume with it.

    Scoped through the same `--project-directory` rule as everything else here: without it Compose
    derives the project from the compose file's parent, and `down --volumes` from any checkout
    erases whichever database answers to the shared name.
    """
    from mosaera_api.setup._uninstall_probe import _compose_argv

    root = repo_root or Path.cwd()
    return _compose_argv(settings, root, compose_project(root), volumes=volumes)


def published_ports(settings: Settings, repo_root: Path) -> str:
    """What Docker says it PUBLISHED — the half the container's own log cannot show.

    Postgres logging "listening on 0.0.0.0:5432" is about the inside of the container. Whether that
    port reached the host is a different fact, held by Docker, and it is the one that decides
    whether a client here can connect. Showing only the server's log left an operator and me
    looking at proof the database was fine while the actual question went unasked.
    """
    argv = compose_argv(settings.docker_bin, repo_root, "ps", "--format", "{{.Name}}  {{.Ports}}")
    try:
        done = subprocess.run(  # noqa: S603 — argv built here, never from operator text
            argv, cwd=repo_root, capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return "\n".join(line.rstrip() for line in done.stdout.splitlines() if line.strip())


def postgres_log_tail(settings: Settings, repo_root: Path, lines: int = 12) -> str:
    """What the bundled Postgres itself said, as evidence rather than inference.

    The wizard has twice now reported a CAUSE it had not established — first the password, then the
    data volume — because a credential refusal looks identical whatever is behind it. Postgres,
    however, says which it is on startup: "Database directory appears to contain a database;
    Skipping initialization" is a pre-existing volume, while "database system is ready to accept
    connections" after an init means the container is fresh and something else explains the refusal.

    So the wizard shows the log instead of guessing at it. "" when there is nothing to show.
    """
    argv = compose_argv(settings.docker_bin, repo_root, "logs", "--no-color", "--tail", str(lines))
    try:
        done = subprocess.run(  # noqa: S603 — argv built here, never from operator text
            [*argv, "postgres"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return "\n".join(line.rstrip() for line in done.stdout.splitlines() if line.strip())


def reset_bundled_volume(settings: Settings, repo_root: Path) -> str:
    """Remove the bundled database's data, and PROVE it is gone. "" when it is.

    The first cut of this fired `down --volumes` and moved on without looking. When the teardown
    did not take, setup walked straight back into the same refusal and told the operator their data
    predated the install a second time — a repair that reports success by not checking is worse
    than no repair, because it spends the operator's trust as well as their time.

    Two attempts and then an honest answer: Compose first, because it is scoped to this project and
    stops the container that holds the volume; then the volume by name, because a container left
    behind by an interrupted run can keep Compose from reaching it. Whatever happens, the last word
    comes from asking whether the volume still exists.
    """
    from mosaera_api.setup._uninstall_probe import data_volume

    def _run(argv: list[str]) -> int:
        try:
            return subprocess.run(  # noqa: S603 — argv built here, never from operator text
                argv, cwd=repo_root, capture_output=True, text=True, timeout=120, check=False
            ).returncode
        except (OSError, subprocess.SubprocessError):
            return -1

    name = data_volume(settings.docker_bin, repo_root)
    _run(compose_down_argv(settings, repo_root, volumes=True))

    def _still_there() -> bool:
        return name != "" and _run([settings.docker_bin, "volume", "inspect", name]) == 0

    if _still_there():
        _run([settings.docker_bin, "volume", "rm", "-f", name])
    if _still_there():
        return (
            f"the volume {name} is still there. Something outside this install may be using it — "
            f"`{settings.docker_bin} ps -a --filter volume={name}` names what."
        )
    return ""


def compose_up_argv(settings: Settings, repo_root: Path | None = None) -> list[str]:
    """Bring up Postgres and WAIT for it.

    `--wait` blocks until the healthcheck `compose.yaml` already defines passes. Without it `up -d`
    returns as soon as the container is created, so the very next connection attempt is refused and
    a perfectly good install reports a database failure on its first run.
    """
    return compose_argv(settings.docker_bin, repo_root or Path.cwd(), "up", "-d", "--wait")


def port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    """Can we publish on this port, or is something already there?

    A bind test, not a connect test. Connecting only finds a server that ANSWERS; binding finds
    anything holding the port at all, which is the actual question when the next thing we do is ask
    Docker to publish on it.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
        return True


def next_free_port(start: int, span: int = 64) -> int:
    """The first free port at or after `start`. 0 when the whole span is taken.

    Suggested, never imposed: the operator types the number, and this only spares them from
    guessing. Postgres convention is 5432, so 5433 is the first thing anybody would try anyway.
    """
    for candidate in range(max(start, 1), min(start + span, 65536)):
        if port_is_free(candidate):
            return candidate
    return 0


def database_port(env: Mapping[str, str] | None = None) -> int:
    """The host port the bundled Postgres publishes on.

    `MOSAERA_DB_PORT` drives BOTH the published port and the DSN — `.env.example` says so and
    `compose.yaml` reads it. The wizard used to hardcode 5432 on both sides, so an operator who
    moved the port got Postgres on one number and a wizard watching another, forever.
    """
    # `env` is injectable so the port rule can be tested without touching the process environment.
    raw = (env if env is not None else os.environ).get("MOSAERA_DB_PORT", "").strip()
    try:
        return int(raw) if raw else 5432
    except ValueError:
        return 5432


def database_url(port: int | None = None) -> str:
    """The bundled Postgres DSN, on whichever port this deployment publishes."""
    return f"postgresql://mosaera:mosaera@localhost:{port or database_port()}/mosaera"


#: How long a PROBE may take. The engine is built with no connect timeout, so against a host that
#: black-holes packets — a firewall DROP, a dead VPN — the connect blocks for the kernel's TCP
#: timeout. Two of these probes run on the UI thread, including the very first frame of the wizard,
#: so that is the whole application frozen with no spinner, no keys and no Esc.
PROBE_TIMEOUT_SECONDS = 5


def with_timeout(url: str, seconds: int = PROBE_TIMEOUT_SECONDS) -> str:
    """The same URL, bounded. libpq reads `connect_timeout` from the query string."""
    if "connect_timeout=" in url:
        return url
    return f"{url}{'&' if '?' in url else '?'}connect_timeout={seconds}"


def access_env(
    *, public: bool, port: int, current: Mapping[str, str], make_token: Callable[[], str]
) -> dict[str, str]:
    """What the access answer means in `.env` terms — computed against what is ALREADY there.

    Idempotence lives here. The first version minted a fresh `MOSAERA_API_TOKEN` on every run and
    rewrote the live one, silently invalidating every credential already issued to a client, while
    the screen reported success. So: an existing token is KEPT, a new one is minted only when there
    is none, and a value that already matches is not rewritten at all.

    Going the other way matters too. Choosing "this machine only" used to leave the old token active
    in `.env` while the screen said the instance was private; an empty value now clears it.
    """
    host = "127.0.0.1" if not public else _ALL_INTERFACES
    out: dict[str, str] = {}
    if current.get("MOSAERA_API_HOST") != host:
        out["MOSAERA_API_HOST"] = host
    if current.get("MOSAERA_API_PORT") != str(port):
        out["MOSAERA_API_PORT"] = str(port)
    if public:
        # `guard_bind` refuses a public bind with no token, so the two are written together or
        # not at all.
        if not current.get("MOSAERA_API_TOKEN"):
            out["MOSAERA_API_TOKEN"] = make_token()
    elif current.get("MOSAERA_API_TOKEN"):
        out["MOSAERA_API_TOKEN"] = ""
    return out


def public_bind_blocked_by(settings: Settings) -> str:
    """Why this instance may NOT be exposed, or "".

    `guard_bind` refuses a public bind on the subprocess sandbox as well as on a missing token —
    it runs the target repository's test code on the HOST. Offering the choice without checking
    both halves means writing a configuration the server then refuses to boot on.
    """
    if settings.sandbox_backend.strip().lower() == "subprocess":
        return "the subprocess sandbox runs repository code on this host, so it may not be exposed"
    return ""


#: A ceiling on the slow steps. An image build is minutes, not hours; a command still running after
#: this is wedged, and a wizard with no bound waits for it forever.
ACTION_TIMEOUT = 30 * 60

#: How often the runner comes up for air to check the deadline and the cancel flag.
_POLL_SECONDS = 0.4

#: What a negative status means, in words a screen can show.
FAILURE_REASON = {
    -1: "could not start — is it installed?",
    -2: "timed out",
    -3: "cancelled",
}


def run_streaming(
    argv: list[str],
    on_line: Callable[[str], None],
    cwd: Path | None = None,
    *,
    timeout: float = ACTION_TIMEOUT,
    should_cancel: Callable[[], bool] | None = None,
) -> int:
    """Run `argv`, handing each output line to `on_line` as it arrives. NEVER raises.

    Streaming rather than capturing because these are the slow steps — a multi-gigabyte image build
    with no output is indistinguishable from a hang.

    Three things the first version got wrong. A missing binary raised `FileNotFoundError` straight
    out of a UI handler and killed the wizard mid-flow. There was no timeout, so a build wedged on
    an unreachable registry hung forever. And there was no way to cancel — `should_cancel` is polled
    between lines so a worker can be stopped.

    `stdin` is closed deliberately: inherited, a `sudo` password prompt would block on a terminal
    Textual owns in raw mode, invisible and unanswerable. Privileged commands are run through
    `App.suspend()` instead, where the operator has their real terminal back.

    Returns the exit status, or negative: -1 could not start, -2 timed out, -3 cancelled.
    """
    try:
        proc = subprocess.Popen(  # noqa: S603 — argv is built here, never from operator text
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        on_line(str(exc))
        return -1

    deadline = time.monotonic() + timeout
    stream = proc.stdout
    try:
        # SELECT rather than `for line in stream`. Iterating a pipe blocks until the next newline,
        # so a command that prints nothing — an apt lock wait, a quiet pull — would never reach the
        # deadline check and the wizard would hang exactly where it promised not to. Polling lets a
        # silent process time out and a cancel land within the poll interval.
        while stream is not None:
            ready, _, _ = select.select([stream], [], [], _POLL_SECONDS)
            if ready:
                line = stream.readline()
                if not line:
                    break  # EOF: the process is done
                on_line(line.rstrip("\n"))
            if should_cancel is not None and should_cancel():
                proc.terminate()
                return -3
            if time.monotonic() > deadline:
                proc.terminate()
                on_line(f"gave up after {int(timeout / 60)} minutes")
                return -2
        return proc.wait(timeout=max(1.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        proc.terminate()
        on_line(f"gave up after {int(timeout / 60)} minutes")
        return -2
    except OSError as exc:  # the process died in a way we cannot read
        on_line(str(exc))
        return -1


def lan_address() -> str:
    """The address another machine on this network would reach us on.

    A UDP socket is "connected" to an unroutable address and the local end read back — no packet is
    sent, and the kernel picks the interface it would actually route from, which is more honest than
    `gethostbyname(gethostname())` (that answers 127.0.0.1 on most Linux boxes).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return str(sock.getsockname()[0])
    except OSError:
        return "this machine's address"  # no route at all; say so rather than invent one
    finally:
        sock.close()


@dataclass(frozen=True)
class DatabaseState:
    """Why the database cannot be opened — which decides what the screen may offer.

    Without this the step offered "Start the bundled Postgres" for every failure, so a running
    server with a missing database led to starting a container that was already up and retrying the
    identical URL. That screen had no way forward at all.
    """

    reachable: bool
    #: The named database is absent, but the SERVER answered — the one case we can fix outright.
    missing_database: bool
    #: The URL came from MOSAERA_DB_URL rather than the bundled default.
    declared: bool
    reason: str
    #: The database the URL names. Taken from the URL, never scraped out of the error text — the
    #: first quoted string in a psycopg failure is the HOST, not the database.
    name: str = ""
    #: The URL that was tried, so the screen can say which one it means. Password-stripped: this is
    #: rendered, and a DSN on screen is a credential on screen.
    url: str = ""


def database_state(settings: Settings) -> DatabaseState:
    """Open the database, or work out precisely why not."""
    declared = bool(settings.db_url)
    url = settings.db_url or database_url()
    name = url.rsplit("/", 1)[-1].split("?")[0]
    # Bounded: this runs on the UI thread, and an unbounded connect freezes the whole wizard.
    store, reason = MemoryStore.open_or_reason(with_timeout(url))
    if store is not None:
        return DatabaseState(True, False, declared, "", name, redact(url))
    missing = f'database "{name}" does not exist' in reason
    return DatabaseState(False, missing, declared, reason, name, redact(url))


def redact(url: str) -> str:
    """A DSN safe to render. The password is the only part that must never reach a screen."""
    if "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    creds, host = rest.rsplit("@", 1)
    user = creds.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}" if ":" in creds else f"{scheme}://{creds}@{host}"


def create_database(settings: Settings) -> str:
    """Create the named database on its own server. Returns "" on success, else why not.

    Connects to the server's own `postgres` database, because you cannot create a database from
    inside the one that does not exist. Deliberately narrow: it creates exactly the name in the URL
    and does nothing else.
    """
    from sqlalchemy import create_engine, text

    url = settings.db_url or database_url()
    name = url.rsplit("/", 1)[-1].split("?")[0]
    if not name or not name.replace("_", "").replace("-", "").isalnum():
        return f"{name!r} is not a database name this can create"
    admin_url = url.rsplit("/", 1)[0] + "/postgres"
    try:
        engine = create_engine(admin_url.replace("postgresql://", "postgresql+psycopg://"))
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except Exception as exc:
        return str(exc)
    return ""
