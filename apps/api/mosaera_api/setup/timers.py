"""The wizard's three clocks, and the one rule they all keep.

A countdown that closes the application, a toast that clears itself, a spinner that turns. Each is
harmless on the screen that started it and wrong on the next one, so **every one of them is stopped
on the way out** — the countdown by leaving the finished screen, the toast by the next notice or the
next step, the spinner by the action ending.

They live together because that rule is the interesting part. Spread across the application body
they read as three unrelated conveniences, and the third one to be written would have forgotten it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mosaera_api.setup.ui import spinner_line, task_list

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mosaera_api.setup.app import SetupApp

#: How fast the spinner turns. Fast enough to read as motion, slow enough not to strobe.
SPIN_SECONDS = 0.12


def stop(app: SetupApp, attr: str) -> None:
    """Cancel whichever timer `attr` names, if it is running. Idempotent by construction."""
    timer = getattr(app, attr, None)
    if timer is not None:
        timer.stop()
        setattr(app, attr, None)


def paint_status(app: SetupApp) -> None:
    """The command's last line, with a spinner frame in front of it while an action is running.

    ONE widget for both. Two would repaint independently and the eye reads the drift between them
    as stutter.

    A timer tick can land while the application is tearing down — the countdown calls `app.exit`
    while this interval is still scheduled — and the widget is then already gone. `NoMatches` out
    of a timer callback is fatal in Textual, so a tick arriving after the tree came down turned a
    clean exit into a traceback and a non-zero status.
    """
    from textual.css.query import NoMatches
    from textual.widgets import Static

    try:
        # ONE spinner on screen. While a task list is up, the running row's own marker is already
        # turning in the marker column — a second spinner three columns to its right, on the log
        # line, turns in step with it but does not line up with it, and reads as the two being out
        # of alignment. With no task list (starting the server, checking this machine) the log line
        # keeps its spinner, because then it is the only thing moving.
        spinning = app._busy and not app._tasks
        app.query_one("#status", Static).update(
            spinner_line(app._tick, app._status_line) if spinning else app._status_line
        )
        # The task list turns on the SAME tick. It is only rewritten when a task changes state, and
        # a state change is exactly what is not happening while one is running — so its spinner sat
        # frozen on one frame and its elapsed time read 0.0s for the whole of a thirty-second
        # container start, which is the stillness the old bar was drawn to hide.
        if app._tasks:
            app.query_one("#progress", Static).update(task_list(app._tasks, app._tick, app.measure))
        app._blanks()
    except NoMatches:
        stop(app, "_spinner")


def start_spinner(app: SetupApp) -> None:
    stop(app, "_spinner")
    app._tick = 0
    # Painted immediately, so the row exists from the first frame. A status line that appears when
    # the first output arrives is itself a jump.
    paint_status(app)
    app._spinner = app.set_interval(SPIN_SECONDS, lambda: _spin(app))


def _spin(app: SetupApp) -> None:
    app._tick += 1
    paint_status(app)
