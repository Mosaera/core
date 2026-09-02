"""The uninstall flow: choosing what to give back, confirming it, and doing it.

Its own module because uninstalling is not a step of installing — it is reached on request and never
walked into — and because `app.py` is at the 500-line ceiling.

The two rules it exists to keep are in `uninstall.py`: never remove what we did not install, and
never let a tick-box alone authorise something irreversible.

THE RULE THIS FILE LEARNED THE HARD WAY: **a removal never leads to a step.** `run` used to end by
returning to `_returns_to`, which defaults to `done` — so finishing an uninstall walked into the
completion step, which built the dashboard and started the server that had just been removed, then
sat on "waiting for it to answer" for the full ninety-second timeout. A removal ends in a result.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from mosaera_api.setup import screens
from mosaera_api.setup.steps import run_streaming
from mosaera_api.setup.ui import RUNNING, Row, uninstall_labels
from mosaera_api.setup.uninstall import perform, plan, summary, survives

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mosaera_api.setup.app import SetupApp

#: A ceiling per removal command. Removal cannot be cancelled by design, so the bound is the only
#: thing standing between a hung daemon and an unusable terminal.
_COMMAND_TIMEOUT = 180.0

#: The two screens Ctrl-X must not re-enter: it is already where it would take you.
_UNINSTALL = ("uninstall", "uninstall_confirm", "removed")

_PICK = "Select what to remove. Nothing is selected until you choose it."


async def enter(app: SetupApp, lead: str = _PICK) -> None:
    """Arriving at the picker. Starts EMPTY.

    Cancelling must return where the operator came FROM. `_returns_to` was set only by Ctrl-X, so
    reaching this screen any other way left a stale value — choosing "Uninstall Mosaera" on the
    finished screen and then cancelling dropped the operator back into the middle of setup.
    """
    if app.step not in _UNINSTALL:
        app._returns_to = app.step
    app._chosen = set()
    _repaint(app, lead)


def _repaint(app: SetupApp, lead: str = "") -> None:
    """Draw the picker from whatever is currently ticked, WITHOUT clearing it.

    Returning to this screen is not arriving at it. The clearing used to live in `enter`, which a
    re-entry also calls — so the "Nothing is selected" bounce and the confirm screen's Cancel both
    had to route around it, and the Cancel row already did exactly that by hand.

    One rule instead: arriving starts empty, returning keeps your ticks.
    """
    app._removable = plan(app.settings, app.settings.home, app.repo_root)
    app._paint(screens.uninstall(uninstall_labels(app._removable, app._chosen, app.measure), lead))


async def abandon(app: SetupApp) -> None:
    """Ctrl-X from anywhere: stop, and give the machine back.

    Reachable from EVERY step, because the alternative was requiring an operator to finish a setup
    they had decided against in order to be allowed to undo it.

    NOTHING ARRIVES PRE-SELECTED. It used to tick the reversible rows here and nowhere else, so the
    same screen with the same words started armed or empty depending on which of three doors you
    came through. Every other screen in this wizard rests on the option that changes nothing, and a
    destructive checklist that arrives pre-armed is the opposite instinct.
    """
    if app.step in _UNINSTALL:
        return
    app.stop_countdown()
    app._notice = ""
    saved, app.step = app.step, "uninstall"
    await enter(app)
    app._returns_to = saved


def toggle(app: SetupApp, index: int) -> None:
    """Space on a row. The two trailing rows are ACTIONS and are not toggleable — an action that
    could be armed like an item is how a list becomes ambiguous."""
    if not 0 <= index < len(app._removable):
        return
    app._chosen.symmetric_difference_update({index})
    _repaint(app)
    app._selected = index
    app._paint_choices()


async def choose(app: SetupApp, index: int) -> None:
    """Enter. On an item it toggles, on the last two rows it acts."""
    count = len(app._removable)
    if index == count:  # "Remove the N selected"
        if not app._chosen:
            app._note("Nothing is selected.", error=True)
            return
        await app._goto("uninstall_confirm")
        return
    if index == count + 1:  # "Cancel"
        await app._goto(app._returns_to)
        return
    toggle(app, index)


async def confirm(app: SetupApp) -> None:
    """The last beat. Two rows, CURSOR ON CANCEL — Enter alone cancels, and removing takes a
    deliberate move first. It replaces a typed word, which stopped nothing an arrow key does not."""
    selected = [app._removable[i] for i in sorted(app._chosen)]
    app._paint(
        screens.uninstall_confirm(
            summary(selected), len(selected), survives(selected, app._removable)
        )
    )


async def confirmed(app: SetupApp, index: int) -> None:
    if index == 0:  # Cancel — the row the cursor starts on
        # Back to the picker WITH the selection intact. Routing through `_goto` re-entered the step
        # and cleared it, so cancelling once cost the operator everything they had ticked.
        app.step = "uninstall"
        _repaint(app, _PICK)
        return
    await run(app)


async def run(app: SetupApp) -> None:
    """Start the removal. The work itself goes to a thread — see `work`."""
    selected = [app._removable[i] for i in sorted(app._chosen)]
    if not selected:
        app.step = "uninstall"
        _repaint(app, _PICK)  # a re-entry: whatever was ticked stays ticked
        return
    # No Esc here. Every other long action is cancellable; a half-finished removal is a state
    # nothing can describe, so this one runs to the end.
    app._begin("Removing", "Working through the selection.", hint="This cannot be interrupted")
    app._cancel_allowed = False
    # The step moves WITH the screen. `run` used to leave it at "uninstall_confirm", so a worker
    # failure repainted the picker with `step` still wrong — and `space`, which is gated on the
    # step, silently did nothing on a screen whose hint says "Space to toggle".
    app.step = _UNINSTALL[0]
    app._rows([Row(r.label) for r in selected])
    app._uninstall_worker()


def work(app: SetupApp) -> None:
    """The removal itself, ON A WORKER THREAD.

    It has to be. `perform` shells out to `docker compose down` and friends, and run inline it held
    the UI loop for the whole removal — so the progress bars this exists to drive would have
    repainted exactly once, at the end, which is a picture of a bar rather than a bar.
    """
    selected = [app._removable[i] for i in sorted(app._chosen)]
    rows = [Row(r.label) for r in selected]
    started = [0.0] * len(selected)

    def _progress(index: int, state: str, note: str) -> None:
        if state == RUNNING:
            started[index] = time.monotonic()
        took = time.monotonic() - started[index] if started[index] else 0.0
        rows[index] = Row(
            selected[index].label,
            state,
            note,
            0.0 if state == RUNNING else took,
            started=started[index] if state == RUNNING else 0.0,
        )
        app.call_from_thread(app._rows, list(rows))

    # Recorded BEFORE the removal runs, so an operator who asked for it still gets it even if an
    # earlier item fails — a half-removed install that leaves the tree behind is the worst outcome
    # available, and this is the item they most clearly asked for.
    if any(r.key == "install" for r in selected):
        app._remove_install = app.repo_root

    results = perform(
        selected,
        app.settings,
        app.settings.home,
        app.repo_root,
        lambda line: app.call_from_thread(app._say, line[-90:]),
        # `cwd` matters and was missing. `_compose_argv` names the compose file RELATIVELY, so
        # without the repo root every `docker compose down` failed with "no configuration file
        # provided" and the screen reported "did not fully succeed" — an uninstall that removed
        # nothing whenever the operator was not standing in the checkout.
        # BOUNDED. `run_streaming` defaults to a 30-minute ceiling, and a removal runs up to six
        # commands with the keyboard deliberately dead — so a wedged `docker compose down`, which is
        # the very condition that makes people uninstall, parked the operator for hours.
        lambda argv, on_line: run_streaming(argv, on_line, app.repo_root, timeout=_COMMAND_TIMEOUT),
        _progress,
    )
    app.call_from_thread(landed, app, results)


def landed(app: SetupApp, results: list[str]) -> None:
    """Where a removal ends: a result, NOT `_returns_to` and never `done`. Starting an instance is
    the one thing that must not follow removing one."""
    app._busy = False
    app._cancel_allowed = True
    # Nothing else stops it on this path, and nothing ever re-enters this step — so the spinner ran
    # on the finished screen until the process exited.
    app.stop_spinner()
    app.stop_countdown()
    app.step = "removed"
    app._notice = ""
    app._paint(screens.removed(results))
