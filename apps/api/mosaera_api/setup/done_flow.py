"""The last screen: bring the instance up, then hand over an address that works.

Its own module for the same reason `uninstall_flow` is — `app.py` sits against the 500-line
ceiling — and for a better one: finishing is not a step of configuring. Everything before this
decides what the machine should be; this is the only part that starts anything.

The countdown is the piece to be careful with. A timer that closes the application is fine on this
screen and catastrophic one screen later, so it is cancelled on leaving rather than merely ignored.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mosaera_api.setup import build_flow, enter_steps, launch, resume, screens
from mosaera_api.setup.env_file import effective_env, port_from
from mosaera_api.setup.explain import explain
from mosaera_api.setup.steps import lan_address, run_streaming
from mosaera_api.setup.ui import failure_reason

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mosaera_api.setup.app import SetupApp

#: How long the finished screen waits before closing itself. Long enough to read the address;
#: short enough that a machine left alone does not sit in an installer forever. Closing is safe
#: because nothing is lost with the alternate screen any more: `__main__._print_outcome` writes
#: the address, the account and the log path into the scrollback after `app.run()` returns.
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
    # Every install gets a key, not only an exposed one (ADR-0126). The exposed case is a REFUSAL
    # in `guard_bind`; this is the default that makes the refusal rare.
    minted = enter_steps.ensure_secret_key(app)
    if app._needs_restart:
        # MIGRATE, do not add. Deliberately NOT conditioned on anything answering at the new
        # address: the old server is on the PREVIOUS one, so a changed port meant this branch was
        # skipped, the old instance was never stopped, and starting the new one left the operator
        # with two dashboards on two ports (reported 2026-09-01). `stop` asks the PID FILE, which
        # names our server wherever it is listening, rather than the address we are moving to.
        problem = launch.stop(app.settings.home, app.repo_root)
        app._needs_restart = False
        if problem:
            old_host, old_port = bind(app)
            app._access_note = (
                f"Settings were saved but the running server could not be stopped ({problem}), so "
                "it is still serving the previous ones. Stop it and run setup again — starting a "
                "second instance instead would leave two."
            )
            app._serving = launch.responds_ok(old_host, old_port)
            paint(app)
            return
        app._access_note = "Settings changed, so the instance was moved to the new address."

    host, port = bind(app)
    # "Something answers on this port" is NOT "our instance is up". An orphaned server from a
    # previous install answers /healthz perfectly, and taking that as our own is how a fresh
    # install skipped its dashboard build AND its launch and still reported success (macOS,
    # 2026-08-31). `our_pid` is the only thing that ties a listener to THIS installation.
    if launch.already_serving(host, port) and not launch.our_pid(app.settings.home, app.repo_root):
        # SOMEONE ELSE HOLDS IT. We must still not start a second server — that rule is the port's
        # and is unchanged — but we may not report their instance as ours either. Saying nothing
        # is how a fresh install skipped its build AND its launch and still showed a live address.
        # STRAIGHT TO THE FIX, not a note naming one. Telling the operator to go and run `lsof`
        # and edit `.env` is a diagnosis by a tool that is holding the repair — the same thing
        # `database_port_prompt` was built to stop doing, and reported as reading the same way.
        # The prompt does not speculate about WHO holds the port: an uninstall leaves nothing
        # behind, so "probably an old Mosaera" is a sentence this product must not need.
        from mosaera_api.setup import choices

        app._serving = False
        app._api_port_conflict = True
        choices.ask_for_api_port(app)
        return
    if launch.already_serving(host, port):
        # Running it again changes nothing — the rule the whole wizard keeps. A second server on a
        # taken port either dies on bind or, worse, quietly answers somewhere else. THAT decision
        # is the port's to make; what we then TELL the operator is the server's, and answering the
        # second question with the first is how this screen came to advertise a 500.
        app._serving = launch.responds_ok(host, port)
        # Red-team round 2. A server started BEFORE the key was minted does not have it in its
        # environment, and `encrypt_secret` with no key is the IDENTITY function — it stores the
        # credential in plaintext and only warns. So this path would paint a success screen over
        # an instance still writing plaintext, with ADR-0126 claiming otherwise. That is the
        # invisible-control shape, and the upgrade path of every install that predates the ADR.
        if minted:
            app._access_note = (
                "Encryption at rest was switched on, but the server already running was started "
                "before it and still stores credentials in plaintext. Restart it to apply."
            )
        paint(app)
        return
    app._begin(
        "Starting Mosaera",
        "Building the sandbox images and the dashboard, then starting the server. Esc cancels.",
    )
    app._launch_worker()


def bring_up(app: SetupApp) -> None:
    """The slow half, called ON A WORKER THREAD by `app._launch_worker`.

    Never raises: every failure becomes a screen that names the log, because the alternative is a
    traceback over the top of a wizard the operator has just spent ten minutes in.
    """
    host, port = bind(app)
    # The sandbox images, first and in the same step. A failure here does NOT stop the server: the
    # images are what RUNS work, not what serves the dashboard, so an instance without them signs
    # in perfectly well and simply cannot run anything yet — which `_outstanding` already reports
    # on the configured screen. Refusing to start would take away the operator's ability to reach
    # the settings page and fix it.
    image_failures = build_flow.build_missing_images(app)
    if image_failures and not app._cancel:
        app.call_from_thread(
            app._say, f"{len(image_failures)} sandbox image(s) still to build — see Settings"
        )
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
    if index == 1:
        # Back to the start of the walk. Every step self-skips when it is already satisfied, so
        # this is a re-run rather than a redo — the same thing the configured screen offers, from
        # the screen an operator is actually looking at when they decide to change an answer.
        app.stop_countdown()
        await app._goto("welcome")
        return
    await app._goto("uninstall")
