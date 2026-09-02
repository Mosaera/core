"""The two slow build steps, off the UI loop.

Bodies rather than workers: `@work(thread=True)` has to decorate a method of the application, so
`app.py` keeps a two-line stub and the work itself lives here. That is not only a line-count move —
what these do (drive `docker build`, bring compose up, migrate) is the same kind of thing
`uninstall.perform` and `launch.bring_up` do, and none of it is rendering.

Everything here runs ON A WORKER THREAD. Touching a widget directly from one is a race, so every
update goes back through `call_from_thread`.
"""

from __future__ import annotations

import dataclasses
import time
from typing import TYPE_CHECKING

from mosaera_memory import MemoryStore

from mosaera_api.setup.env_file import write_env_file
from mosaera_api.setup.explain import explain
from mosaera_api.setup.steps import (
    DatabaseState,
    build_image_argv,
    compose_up_argv,
    create_database,
    database_port,
    database_state,
    database_url,
    ensure_compose_project,
    published_ports,
    reset_bundled_volume,
    run_streaming,
    survey_images,
)
from mosaera_api.setup.ui import DONE, FAILED, RUNNING, WAITING, Row, failure_reason
from mosaera_api.setup.uninstall import record_install

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mosaera_api.setup.app import SetupApp


def build_images(app: SetupApp) -> None:
    """Build whatever is missing, one row at a time, cancellable throughout.

    A FAILURE MUST LEAVE A MESSAGE. It used to write the reason into a progress row and then call
    `_finish_action`, which re-enters the step and blanks the progress table — so a build that
    failed for any reason at all (no daemon, no disk, no network) repainted the identical "4 of 4
    still to build" screen with nothing said. Pressing Enter again did the same nothing. The only
    way out was Skip, and nothing on screen suggested why.
    """
    images = survey_images(app.settings)
    rows = [
        Row(i.tag, DONE if i.present else WAITING, "present" if i.present else "") for i in images
    ]
    app.call_from_thread(app._rows, list(rows))
    failed: list[str] = []
    last = _Tail()
    for n, image in enumerate(images):
        if image.present or app._cancel:
            continue
        started = time.monotonic()
        rows[n] = Row(image.tag, RUNNING, "building", started=started)
        app.call_from_thread(app._rows, list(rows))
        code = run_streaming(
            build_image_argv(app.settings, image),
            lambda line: _watch(app, last, line),
            app.repo_root,
            should_cancel=lambda: app._cancel,
        )
        ok = code == 0
        if not ok:
            failed.append(f"{image.tag} — {failure_reason(code)}")
        rows[n] = Row(
            image.tag,
            DONE if ok else FAILED,
            "built" if ok else failure_reason(code),
            time.monotonic() - started,
        )
        app.call_from_thread(app._rows, list(rows))
    if not failed and not app._cancel and any(not i.present for i in images):
        # Recorded so uninstall may offer them back — and never offers images someone else built.
        record_install(app.settings.home, "images")
    if failed and not app._cancel:
        # The command's own last line, explained — `exit 1` alone names no cause, and the line that
        # did name one was streamed to a widget the repaint then cleared.
        why = explain(last.line, app.platform).summary if last.line else failed[0]
        app.call_from_thread(
            app._note, f"Could not build {len(failed)} image(s) — {why}", error=True
        )
    app.call_from_thread(app._finish_action, "images")


class _Tail:
    """The last line a command printed. Kept because the widget it was streamed to is cleared by
    the repaint that follows the failure, taking the only statement of the cause with it."""

    line = ""


def _watch(app: SetupApp, tail: _Tail, line: str) -> None:
    if line.strip():
        tail.line = line
    app.call_from_thread(app._say, line[-90:])


#: The three phases of getting a bundled database, in order. They were always all happening; the
#: old screen exposed them as three competing CHOICES and made the operator pick which one their
#: failure needed.
_PHASES = ("Container", "Database", "Schema")

#: What the container row says when something already holds the port. NOT "already running": whether
#: it is the container we would have started is not knowable from a successful connection, and a
#: system Postgres on 5432 was being adopted under a row claiming our container was up — then
#: migrated into, and written to `.env`.
ANSWERING = "a server is answering on the port"


def bundled_database(app: SetupApp) -> None:
    """Start it, create it, migrate it — skipping whichever parts are already true.

    Each phase is skipped on its own evidence rather than on a guess about the failure, so running
    this against a half-built database finishes the half that is missing. That is the same
    idempotence every other step keeps, applied to the one step that used to ask the operator to
    supply it by choosing correctly.
    """
    # Recorded before the first compose call, so the shell paths (`make down`, `dev-up.sh`) act on
    # the same project this does.
    ensure_compose_project(app.repo_root)
    url = database_url()
    rows = [Row(name) for name in _PHASES]
    started = [0.0, 0.0, 0.0]

    def _row(index: int, state: str, note: str) -> None:
        if state == RUNNING:
            started[index] = time.monotonic()
        took = time.monotonic() - started[index] if started[index] else 0.0
        rows[index] = Row(
            _PHASES[index],
            state,
            note,
            0.0 if state == RUNNING else took,
            started=started[index] if state == RUNNING else 0.0,
        )
        app.call_from_thread(app._rows, list(rows))

    def _fail(index: int, line: str) -> None:
        _row(index, FAILED, "failed")
        app.call_from_thread(app._note, line, error=True)
        app.call_from_thread(app._finish_action, "database")

    if app._db_reset:
        # BEFORE anything looks at the port. The volume is what refuses us, and Postgres applies
        # POSTGRES_PASSWORD only when it initialises an EMPTY data directory — so it cannot be
        # re-keyed, only recreated. `--volumes`, scoped to THIS install's compose project.
        app._db_reset = False
        _row(0, RUNNING, "clearing old data")
        problem = reset_bundled_volume(app.settings, app.repo_root)
        if problem:
            # SAID, not sailed past. Continuing here walks into the same refusal and reports the
            # operator's data as predating the install a second time, having just told them it was
            # being removed.
            _fail(0, f"Could not clear the old database data — {problem}")
            return

    _row(0, RUNNING, "checking")
    state = database_state(dataclasses.replace(app.settings, db_url=url))
    # WE DID NOT START IT. This decides what every later failure MEANS, and it was decided on the
    # wrong evidence: a FULLY SUCCESSFUL connection. A server answers by accepting a connection OR
    # by refusing our credentials — both mean something already holds that port — so a foreign
    # Postgres that enforces auth failed this test in exactly the way our own stale volume does,
    # and got routed to "reset your database" instead of "pick another port". That is the bug that
    # cost an operator a database, every volume, and two whole evenings.
    #
    # The two are told apart by asking whether OUR compose project has anything up. Nothing of
    # ours running plus a refusal means the refusal came from somebody else's server.
    adopted = state.reachable or (
        _is_auth_failure(getattr(state, "reason", ""))
        and not published_ports(app.settings, app.repo_root).strip()
    )
    if adopted and not state.reachable:
        # DO NOT START OURS ON TOP OF IT. Bringing the bundled container up against a port another
        # server already holds is how a freshly initialised database still reported a rejected
        # password: the container was healthy and simply never in the path.
        app._port_conflict = True
        _fail(0, _credentials_note(database_port(), adopted=True))
        return
    if state.reachable:
        # "answering", NOT "already running". Something is listening on the port; whether it is the
        # container we would have started is not knowable from a successful connection, and a
        # system Postgres on 5432 was being adopted, migrated into, and written to `.env` under a
        # row that said the bundled container was up.
        _row(0, DONE, ANSWERING)
    else:
        last = _Tail()
        code = run_streaming(
            compose_up_argv(app.settings, app.repo_root),
            lambda line: _watch(app, last, line),
            app.repo_root,
            should_cancel=lambda: app._cancel,
        )
        if code != 0:
            # The command's own last line, explained. `exit 1` alone sent the operator looking for a
            # database problem when the cause was a stopped daemon, a taken port, or a missing
            # compose file — all of which that line names and `explain` already knows.
            why = explain(last.line, app.platform).summary if last.line else failure_reason(code)
            _fail(0, f"Could not start Postgres — {why}")
            return
        _row(0, DONE, "running")
        state = _wait_reachable(app, url)
        if not state.reachable and _is_auth_failure(getattr(state, "reason", "")):
            # REACHED, AND REFUSED. `database_state` reports `reachable=False` for every failure,
            # including one where the server answered and rejected the credentials — and this
            # branch used to sit below the unreachable check, so an auth refusal was reported as
            # "running, but not reachable from here". psycopg prefixes it with "connection
            # failed:", the screen truncated the line before "FATAL: password authentication
            # failed", and three fixes were built on top of that misreading.
            _blame_credentials(app, adopted=adopted, reason=state.reason)
            _fail(0, _credentials_note(database_port(), adopted=adopted))
            return
        if not state.reachable:
            # NOT A GUESS. `compose up --wait` returns only once the healthcheck passes, so the
            # container is running and answering inside the VM; if the client still cannot open a
            # socket, the port is published at an address this host does not share. Every earlier
            # version of this code walked on from here and reported the credential failure that
            # followed, which is how "rejected the password" came to be blamed three times over.
            app._db_unreachable = True
            app._db_reason = getattr(state, "reason", "") or ""
            _fail(
                0,
                f"Postgres is running, but nothing here can reach it on port {database_port()}.",
            )
            return

    _row(1, RUNNING, "checking")
    if state.missing_database:
        problem = create_database(dataclasses.replace(app.settings, db_url=url))
        if problem:
            if _is_auth_failure(problem):
                _blame_credentials(app, adopted, problem)
                _fail(1, _credentials_note(database_port(), adopted))
                return
            _fail(1, f"Could not create the database — {explain(problem, app.platform).summary}")
            return
        _row(1, DONE, "created")
    else:
        _row(1, DONE, "present")

    _row(2, RUNNING, "migrating")
    store, reason = MemoryStore.open_or_reason(url)
    if store is None:
        # THROUGH `explain`. Interpolated raw, this put ten centred lines of psycopg internals on
        # screen, with the one sentence that mattered buried in the middle of them.
        if _is_auth_failure(reason):
            _blame_credentials(app, adopted, reason)
            _fail(2, _credentials_note(database_port(), adopted))
            return
        _fail(
            2, f"Postgres started, but the schema failed — {explain(reason, app.platform).summary}"
        )
        return
    _row(2, DONE, "ready")
    write_env_file(app.repo_root / ".env", {"MOSAERA_DB_URL": url})
    app.call_from_thread(_adopt, app, url)


def _is_auth_failure(reason: str) -> bool:
    """Did the server refuse our CREDENTIALS, as opposed to being absent, down or unreachable?

    Matched on Postgres's own wording rather than an exception type: the reason arrives here as the
    string `explain` is given, and it is the same string `explain` already keys on for the
    "rejected the password" sentence.
    """
    lowered = (reason or "").lower()
    return "password authentication failed" in lowered or (
        "role" in lowered and "does not exist" in lowered
    )


#: How long to keep asking after Compose says the container is healthy. Measured against the case
#: that produced it: `docker compose ps` showed `0.0.0.0:5432->5432/tcp (healthy)` and `nc` to the
#: host succeeded — minutes later. At the moment of the single probe, neither did.
_FORWARD_GRACE = 20.0
_FORWARD_POLL = 1.0


def _wait_reachable(app: SetupApp, url: str, grace: float = _FORWARD_GRACE) -> DatabaseState:
    """Keep asking until the port answers, or the grace runs out.

    `compose up --wait` returns when the CONTAINER's healthcheck passes, and that healthcheck runs
    inside the VM. On Colima and Lima the host-side port forward is established separately and
    afterwards, so there is a window in which the container is genuinely healthy and the host
    genuinely cannot connect — and a single probe taken in that window reports a broken install.

    Evidence for the window, from the machine that hit it: `docker compose ps` showed
    `0.0.0.0:5432->5432/tcp   Up 5 minutes (healthy)` and `nc -vz 127.0.0.1 5432` succeeded, while
    the wizard — probing the instant Compose returned — had failed on both `::1` and `127.0.0.1`.

    One probe was never enough. It just used to be a credential message that got the blame.
    """
    deadline = time.monotonic() + grace
    state = database_state(dataclasses.replace(app.settings, db_url=url))
    # A refusal is an ANSWER. Waiting for a forward that is demonstrably already carrying traffic
    # just makes the operator watch a spinner before reading the wrong diagnosis.
    while (
        not state.reachable
        and not _is_auth_failure(getattr(state, "reason", ""))
        and time.monotonic() < deadline
        and not app._cancel
    ):
        _row_note = "waiting for the port"
        app.call_from_thread(app._say, _row_note)
        time.sleep(_FORWARD_POLL)
        state = database_state(dataclasses.replace(app.settings, db_url=url))
    return state


def _blame_credentials(app: SetupApp, adopted: bool, reason: str = "") -> None:
    """Route a credential refusal, WITHOUT claiming to know why it happened.

    One fact is established: whether a server was already answering before setup touched anything.
    That one is safe to act on — it is somebody else's server, and the repair is to move off its
    port.

    The other branch is NOT a diagnosis. "We started the container and it still refuses us" is
    consistent with a volume that predates the install, and with several other things, and this
    code asserted the volume twice — sending an operator to delete data that did not exist. It now
    carries the raw reason forward so the screen can show Postgres's own log and let the operator
    see which it is.
    """
    if adopted:
        app._port_conflict = True
        return
    app._db_stale = True
    app._db_reason = reason


def _credentials_note(port: int, adopted: bool) -> str:
    """The line that reports it. The repair is the screen that comes next, either way."""
    if adopted:
        return (
            f"Port {port} is held by another server, which refused these credentials — so it is "
            f"not the bundled database."
        )
    # NO CAUSE NAMED. The screen that follows shows Postgres's own log and offers both repairs;
    # asserting one here is what produced two confidently wrong diagnoses.
    return f"The database on port {port} refused the credentials this install uses."


def _adopt(app: SetupApp, url: str) -> None:
    """Take the bundled URL for the rest of this run, then move on.

    On the UI thread: replacing `app.settings` from the worker would race every read of it.
    """
    app.settings = dataclasses.replace(app.settings, db_url=url)
    app._note("Database ready and migrated")
    app._finish_action()
