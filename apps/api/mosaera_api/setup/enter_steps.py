"""What each step FINDS when it is entered — the probe, and the screen that describes the result.

Split from `app.py` along a real seam rather than only for the line ceiling: every function here
answers "what is the state of this machine, and what does that mean for this step", and none of them
render anything themselves. That is why they can auto-skip — a step with nothing to show is not a
step, in either direction of travel.
"""

from __future__ import annotations

import textwrap
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mosaera_core.prereqs import missing, survey
from mosaera_memory import MemoryStore

from mosaera_api.setup import launch, password_reset, screens
from mosaera_api.setup.admin import admin_exists
from mosaera_api.setup.env_file import (
    effective_env,
    port_from,
    read_env_file,
    shadowed_by_env,
    write_env_file,
)
from mosaera_api.setup.explain import explain
from mosaera_api.setup.steps import (
    database_port,
    database_state,
    database_url,
    lan_address,
    public_bind_blocked_by,
    survey_images,
    with_timeout,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mosaera_api.setup.app import SetupApp

#: The bind that means "anything on the network", as it appears in `.env`.
_ALL_INTERFACES = "0.0.0.0"  # noqa: S104


@dataclass(frozen=True)
class Ready:
    """A finished instance, and the facts the screen needs to describe it."""

    url: str
    accounts: int
    serving: bool
    #: Whether the gap this screen can close by itself is present.
    images_to_build: bool = False
    #: What is still missing — absent images, uninstalled prerequisites. NOT a reason to call the
    #: instance unconfigured; a reason to say so on the screen.
    gaps: tuple[str, ...] = ()


def configured(app: SetupApp) -> Ready | None:
    """Whether this box is set up, and nothing MUST be done. `None` otherwise.

    Configured means the database opens and an account exists. That pair is exactly what makes an
    instance something you can sign into, and it is what the whole flow exists to produce.

    It used to also demand every prerequisite and every sandbox image — MORE than the walk itself
    demands, because the walk offers "Skip — install these manually" and "Skip". So the wizard could
    print "Mosaera is configured", and on the next run walk the operator through setup from the top,
    not recognising the instance it had just finished. Two definitions of done, disagreeing.

    Images and prerequisites are "can this box run agents", which is a different question — the
    application already answers it by refusing runs. They are reported as GAPS on the screen rather
    than used to deny that setup happened.
    """
    # Bounded: this is the FIRST frame of the wizard, and an unbounded connect against a host that
    # drops packets froze the application before it had drawn anything.
    store, _reason = MemoryStore.open_or_reason(with_timeout(app.settings.db_url or database_url()))
    if store is None:
        return None
    try:
        accounts = int(store.count_users())
    except Exception:
        return None  # a store we cannot read is not one we may call configured
    if accounts < 1:
        return None
    env = effective_env(app.repo_root / ".env")
    host = env.get("MOSAERA_API_HOST") or "127.0.0.1"
    port = port_from(env, "MOSAERA_API_PORT", 8000)
    return Ready(
        url=launch.address(host, port, lan_address()),
        accounts=accounts,
        # `responds_ok`, NOT `already_serving`: this is a CLAIM MADE TO THE OPERATOR, and this
        # screen said "Running at http://127.0.0.1:8000" over an instance that answered every
        # request with a 500 (live macOS run, 2026-08-30). An open port is not a working instance.
        serving=launch.responds_ok(host, port),
        gaps=_outstanding(app),
        images_to_build=images_outstanding(app),
    )


def _outstanding(app: SetupApp) -> tuple[str, ...]:
    """What a configured instance still lacks, in words for the screen.

    Named rather than hidden: an instance with no sandbox images signs in perfectly well and cannot
    run anything, and the operator deserves to be told which of the two they have.
    """
    gaps = [f.prereq.label for f in missing(survey(app.settings.docker_bin, app.platform))]
    absent = sum(1 for i in survey_images(app.settings) if not i.present)
    if absent:
        gaps.append(f"{absent} sandbox image{'s' if absent != 1 else ''} to build")
    return tuple(gaps)


def images_outstanding(app: SetupApp) -> bool:
    return any(not i.present for i in survey_images(app.settings))


def reprobe(app: SetupApp) -> None:
    """Redraw the configured screen from the MACHINE, not from what a handler just attempted."""
    probed(app, configured(app))


def probed(app: SetupApp, ready: Ready | None) -> None:
    """The readiness probe landed. `None` means there is still setup to do.

    It runs on a worker because it is four `docker` calls, four `docker image inspect`s and a
    database connect — up to forty seconds on a cold or wedged daemon, and it used to run inline on
    the very first frame with the loop blocked: no repaint, no key, not even Ctrl-Q.
    """
    from mosaera_api.setup.app import CONFIGURED_STEP

    app._busy = False
    app._probed = True
    app.stop_spinner()
    if ready is None:
        welcome(app)
        return
    app.step = CONFIGURED_STEP
    app._paint(
        screens.configured(
            ready.url,
            ready.accounts,
            str((app.repo_root / ".env").resolve()),
            serving=ready.serving,
            gaps=ready.gaps,
            images_to_build=ready.images_to_build,
        )
    )


def welcome(app: SetupApp) -> None:
    """The first screen, and the acknowledgement if a previous run stopped part-way.

    `step` is ASSIGNED, not assumed. The configured branch sets it and this one did not — so a
    re-probe that flipped to "not configured" painted this screen while `step` was still
    "configured", where Enter fell through to an off-spine advance that returns early and Esc
    returned early too: a screen saying "Enter to continue" on which no key did anything.
    """
    from textual.widgets import Static

    from mosaera_api.setup import resume
    from mosaera_api.setup.paint import keys_hint

    app.step = "welcome"
    said = "" if app._greeted else resume.sentence(resume.read(app.settings.home))
    app._greeted = True
    app._paint(screens.welcome(said))
    app.query_one("#hint", Static).update(keys_hint(app, first=True))


async def machine(app: SetupApp) -> None:
    from mosaera_api.setup.prereq_bridge import actionable

    found = survey(app.settings.docker_bin, app.platform)
    gaps = missing(found)
    if not gaps:
        await app._skip()
        return
    # The ROWS are the actions, and they must be the same list the choice handler re-derives — it
    # indexes into its own survey, so a screen numbering its rows differently would install the
    # wrong tool. Emptiness is still judged on the raw gaps: collapsing two rows into one action
    # never means there is nothing to do.
    app._paint(screens.machine(found, actionable(gaps), app.platform, app.measure))


async def database(app: SetupApp) -> None:
    state = database_state(app.settings)
    if state.reachable:
        # RECORD THE URL THAT WORKED. This step used to skip silently when the database was already
        # up, so `.env` never learned which database the wizard had just validated — and the server
        # the finished screen starts inherits `.env`. The result was an instance served at the
        # advertised address with no store at all: `auth_required: false`, no accounts, and a login
        # page that could not log anybody in, while the database sat right there holding the admin
        # account the wizard had created.
        remember_database(app)
        await app._skip()
        return
    if app._port_conflict:
        # STRAIGHT TO THE FIX, not back to the menu. Offering a third row here put "(recommended)"
        # on the option that had just failed and made the actual repair look like a departure from
        # it — reported as reading exactly that way. Choosing the bundled database is still the
        # recommended path; a port already taken is a step WITHIN it, not a different route.
        #
        # Consumed as it is used: Esc from the prompt re-enters this step, and a flag that stayed
        # set would put the operator straight back on the prompt they just declined.
        from mosaera_api.setup import choices  # local: `choices` imports this module

        app._port_conflict = False
        choices.ask_for_port(app)
        return
    if app._db_unreachable:
        app._db_unreachable = False
        from mosaera_api.setup.steps import postgres_log_tail, published_ports

        ports = published_ports(app.settings, app.repo_root)
        log = postgres_log_tail(app.settings, app.repo_root, lines=4)
        # WRAPPED INTO THE EVIDENCE BLOCK, not left to `#detail`. That widget is nowrap+ellipsis,
        # which is right for a one-line cause and wrong here: the driver's message is the only
        # thing that says WHY the socket failed, and it was being cut off mid-sentence — the same
        # truncation that hid the Homebrew guidance, in the one place it matters most.
        why = textwrap.fill(
            " ".join((app._db_reason or "").split()), app.measure, subsequent_indent="  "
        )
        app._paint(
            screens.database_unreachable(
                database_port(),
                evidence="\n".join(x for x in (ports, log, why) if x),
            )
        )
        return
    if app._db_stale:
        # Same shape as the port repair: consumed as it is used, so Esc reaches the ordinary menu
        # instead of putting the operator back on the screen they just declined.
        app._db_stale = False
        from mosaera_api.setup.steps import postgres_log_tail

        # WRAPPED, like the other one. `#detail` is nowrap+ellipsis, and the driver's message is
        # the only text that says why — truncating it here is what turned an authentication
        # failure into four evenings of network theories.
        why = textwrap.fill(
            " ".join((app._db_reason or "").split()), app.measure, subsequent_indent="  "
        )
        log = postgres_log_tail(app.settings, app.repo_root, lines=6)
        app._paint(
            screens.database_reset(
                database_port(),
                evidence="\n".join(x for x in (log, why) if x),
            )
        )
        return
    app._paint(screens.database(state, database_port()))


def remember_database(app: SetupApp) -> str:
    """Write the working database URL into this install's `.env`, once.

    Only the bundled-database action used to do this, so every instance whose database was already
    reachable — the common case on a re-run, and on any machine with Postgres already up — finished
    setup without it. An existing value is never overwritten: the operator's own URL is theirs.
    """
    url = app.settings.db_url or database_url()
    env_path = app.repo_root / ".env"
    if not read_env_file(env_path).get("MOSAERA_DB_URL", "").strip():
        with suppress(OSError):  # a read-only `.env` is reported where it is written deliberately
            write_env_file(env_path, {"MOSAERA_DB_URL": url})
    return url


def new_secret_key() -> str:
    """A Fernet key for encryption at rest (ADR-0039).

    Imported lazily: `cryptography` is a `mosaera-memory` runtime dependency, and the setup
    wizard must keep starting on a machine whose environment is still being built.
    """
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


def ensure_secret_key(app: SetupApp) -> bool:
    """Give this install a key to encrypt its credentials with. Returns whether one was minted.

    ADR-0039 made encryption at rest OPT-IN and rejected a mandatory key, on two grounds: it
    "breaks every existing keyless install" and "forces key management on users who don't need
    it". Both are about an operator who must produce and hold a key. Neither survives a wizard
    that mints one for them (ADR-0126): nothing existing breaks, because an install that already
    has a key or has none is left exactly as it is and ADR-0039's lazy migration is untouched,
    and nobody manages anything.

    What changed underneath ADR-0039 is the population. Its reasoning is explicitly about "the
    trusted single-tenant box" — correct for the author's laptop, and no longer a description of
    who installs this now that a public one-liner exists.

    NEVER overwrites: a key already there encrypts secrets already stored, and replacing it would
    strand them. Same rule as `remember_database` one function up, for the same reason.
    """
    env_path = app.repo_root / ".env"
    if read_env_file(env_path).get("MOSAERA_SECRET_KEY", "").strip():
        return False  # already has one — nothing minted, nothing stale
    try:
        write_env_file(env_path, {"MOSAERA_SECRET_KEY": new_secret_key()})
    except OSError as exc:
        # NOT the same as "already had one", though the first cut of this returned False for both.
        # A read-only `.env` would then leave the instance storing credentials in plaintext while
        # ADR-0126 states every install encrypts at rest, and nothing on screen would differ.
        app._access_note = (
            "Credentials could not be encrypted at rest: writing MOSAERA_SECRET_KEY to .env "
            f"failed ({exc.strerror or exc}). They are stored in plaintext until this is fixed."
        )
        return False
    return True


async def access(app: SetupApp) -> None:
    env_path = app.repo_root / ".env"
    current = effective_env(env_path)
    app._paint(
        screens.access(
            shadowed=shadowed_by_env(env_path, "MOSAERA_API_HOST", "MOSAERA_API_PORT"),
            public_now=current.get("MOSAERA_API_HOST") == _ALL_INTERFACES,
            blocked=public_bind_blocked_by(app.settings, current),
            port=port_from(current, "MOSAERA_API_PORT", 8000),
            lan=lan_address(),
            width=app.measure,
        )
    )


async def admin(app: SetupApp) -> None:
    store, reason = MemoryStore.open_or_reason(with_timeout(app.settings.db_url or database_url()))
    if store is None:
        # There is no account-less route. The database step cannot be passed without a store that
        # opens, so reaching here without one means it died in between — which is a reason to go
        # back and fix it, not to create an instance nobody can sign into.
        app._note(f"The database is no longer reachable — {explain(reason).summary}", error=True)
        await app._goto("database")
        return
    if admin_exists(store):
        await app._skip()
        return
    app._paint(screens.admin())
    app._ask(
        "Username",
        secret=False,
        for_field="username",
        hint="Letters, digits, dot, dash or underscore, 3-64 characters.",
    )


async def dispatch(app: SetupApp, step: str) -> None:
    """What entering each step DOES — the one table that says so.

    Moved off `SetupApp` at the god-file ceiling, and it belongs here on its own merits: this module
    already owns what every step does on entry, and the mapping from a step name to that work is the
    same question. `app.py` keeps the bookkeeping around a transition (the clock, the toast, the
    spinner, the resume record); this is the transition itself.
    """
    from mosaera_api.setup import uninstall_flow

    await {
        "welcome": app._enter_welcome,
        "configured": app._enter_welcome,
        "machine": lambda: machine(app),
        "database": lambda: database(app),
        "access": lambda: access(app),
        "admin": lambda: admin(app),
        "done": app._enter_done,
        "reset": lambda: password_reset.enter(app),
        "uninstall": lambda: uninstall_flow.enter(app),
        "uninstall_confirm": lambda: uninstall_flow.enter(app),
        "removed": app._enter_removed,
    }[step]()
