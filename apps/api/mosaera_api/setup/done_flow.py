"""The last screen: bring the instance up, then hand over an address that works.

Its own module for the same reason `uninstall_flow` is — `app.py` sits against the 500-line
ceiling — and for a better one: finishing is not a step of configuring. Everything before this
decides what the machine should be; this is the only part that starts anything.

The countdown is the piece to be careful with. A timer that closes the application is fine on this
screen and catastrophic one screen later, so it is cancelled on leaving rather than merely ignored.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mosaera_api.setup import enter_steps, launch, resume, screens
from mosaera_api.setup.env_file import effective_env, port_from
from mosaera_api.setup.explain import explain
from mosaera_api.setup.steps import lan_address, run_streaming
from mosaera_api.setup.ui import failure_reason

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mosaera_api.setup.app import SetupApp

#: How long the finished screen waits before closing itself. Long enough to read the address and
#: write it down; short enough that a machine left alone does not sit in an installer forever.
COUNTDOWN_SECONDS = 60


def bind(app: SetupApp) -> tuple[str, int]:
    env = effective_env(app.repo_root / ".env")
    return env.get("MOSAERA_API_HOST") or "127.0.0.1", port_from(env, "MOSAERA_API_PORT", 8000)


async def enter(app: SetupApp) -> None:
    """Setup is done. Bring the instance up unless it is already up."""
    resume.clear(app.settings.home)
    # The server about to be started INHERITS `.env`, so whatever database this run proved works has
    # to be written there first. Recorded here rather than only in the database step because the
    # configured screen reaches this without walking that step at all — and the result was an
    # instance served at the advertised address with no store, `auth_required: false` and a login
    # page that could not log anybody in.
    enter_steps.remember_database(app)
    host, port = bind(app)
    if launch.already_serving(host, port):
        # Running it again changes nothing — the rule the whole wizard keeps. A second server on a
        # taken port either dies on bind or, worse, quietly answers somewhere else. THAT decision
        # is the port's to make; what we then TELL the operator is the server's, and answering the
        # second question with the first is how this screen came to advertise a 500.
        app._serving = launch.responds_ok(host, port)
        paint(app)
        return
    app._begin("Starting Mosaera", "Building the dashboard and starting the server. Esc cancels.")
    app._launch_worker()


def bring_up(app: SetupApp) -> None:
    """The slow half, called ON A WORKER THREAD by `app._launch_worker`.

    Never raises: every failure becomes a screen that names the log, because the alternative is a
    traceback over the top of a wizard the operator has just spent ten minutes in.
    """
    host, port = bind(app)
    built = True
    if not launch.dashboard_built(app.repo_root):
        for argv in launch.dashboard_argv():
            code = run_streaming(
                argv,
                lambda line: app.call_from_thread(app._say, line[-90:]),
                app.repo_root,
                should_cancel=lambda: app._cancel,
            )
            if code != 0:
                app.call_from_thread(
                    app._note, f"Could not build the dashboard — {failure_reason(code)}", error=True
                )
                built = False
                break
    # A server with no dashboard serves a 404 at the address this screen is about to print, which is
    # the exact outcome `dashboard_built` exists to prevent. Failing to build is failing to start.
    serving = False
    if built and not app._cancel and not launch.already_serving(host, port):
        # Re-probed here, not only on entry. Between the entry check and this line a dashboard build
        # can take minutes — long enough for a second wizard, or the operator's own `make up`, to
        # take the port. The loser's uvicorn dies on bind and both write `api.pid`.
        try:
            launch.start_detached(
                app.repo_root, app.settings.home, effective_env(app.repo_root / ".env")
            )
        except OSError as exc:
            app.call_from_thread(
                app._note, f"Could not start the server — {explain(str(exc)).summary}", error=True
            )
        else:
            app.call_from_thread(app._say, "Waiting for it to answer…")
            serving = launch.wait_until_serving(host, port, should_cancel=lambda: app._cancel)
    elif built and not app._cancel:
        # Something holds the port, so we must not start a second one — but "holds the port" and
        # "works" are different facts, and this branch used to assert the second from the first.
        serving = launch.responds_ok(host, port)
    app.call_from_thread(_landed, app, serving, app._cancel, built)


def failed(app: SetupApp) -> None:
    """A worker died. Show the screen; do NOT re-enter the step, which would start it again."""
    _landed(app, serving=False, cancelled=False, attempted=False)


def _landed(app: SetupApp, serving: bool, cancelled: bool = False, attempted: bool = True) -> None:
    app._busy = False
    # The spinner is stopped HERE, not by `_finish_action` — this path does not go through it, so
    # the 0.12s interval kept rewriting a status line the repaint had just cleared.
    app.stop_spinner()
    app._cancel = False
    app._serving = serving
    app._cancelled_launch = cancelled and not serving
    app._attempted_launch = attempted
    paint(app)


def paint(app: SetupApp) -> None:
    """Draw the finished screen and start the clock."""
    host, port = bind(app)
    app._remaining = COUNTDOWN_SECONDS
    app._paint(
        screens.done(
            launch.address(host, port, lan_address()),
            app._username,
            serving=app._serving,
            log=str(app.settings.home / launch.LOG_NAME),
            seconds=app._remaining,
            cancelled=app._cancelled_launch,
            attempted=app._attempted_launch,
            access=app._access_note,
        )
    )
    app.start_countdown()


def tick(app: SetupApp) -> None:
    """One second gone. Only the hint is rewritten — repainting the screen each second would reset
    the operator's place in the choice list under their fingers."""
    app._remaining -= 1
    if app._remaining <= 0:
        app.exit(0)
        return
    host, port = bind(app)
    app._paint_hint(
        screens.done(
            launch.address(host, port, lan_address()),
            app._username,
            serving=app._serving,
            log=str(app.settings.home / launch.LOG_NAME),
            seconds=app._remaining,
            cancelled=app._cancelled_launch,
            attempted=app._attempted_launch,
        ).hint
    )


async def chose(app: SetupApp, index: int) -> None:
    if index == 0:
        app.exit(0)
        return
    await app._goto("uninstall")
