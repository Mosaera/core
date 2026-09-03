"""Movement: what each key does, and which way the wizard is travelling.

Together in one file because the interesting part is the INTERACTION between them. Every defect this
module has produced came from two of these functions disagreeing:

  - auto-skip only knew "forward", so Esc onto a satisfied step bounced straight back off it;
  - a repair left `_going_back` set, so installing the last missing prerequisite congratulated the
    operator by returning them to the welcome screen;
  - `_advance` indexed `STEPS` unconditionally, and every screen off the spine (`configured`,
    `uninstall`, `removed`) raised on it;
  - Esc out of the confirm screen took a different path from the Cancel row on the same screen, and
    discarded the selection the Cancel row was written to preserve.

Spread across the application body, none of those pairs were ever read together.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.events import Key

from mosaera_api.setup import enter_steps, uninstall_flow

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mosaera_api.setup.app import SetupApp


async def pressed(app: SetupApp, event: Key) -> None:
    """Keys handled explicitly.

    ENTER BELONGS TO A FOCUSED FIELD, and this docstring used to claim it already did — that a
    focused `Input` consumes Enter and posts `Submitted`, so this handler never sees it. Measured,
    both happen: this runs FIRST and the queued `Submitted` arrives after it. So one Enter on the
    username submitted the username, moved on to ask for the password, and then submitted the
    password too — an empty one — which is why arriving at that prompt greeted the operator with
    "password must be at least 8 characters" before they had typed anything.
    """

    if app._busy:
        if event.key == "escape":
            event.stop()
            if not app._cancel_allowed:
                # The removal cannot be interrupted, and its hint says so. Printing "Cancelling…"
                # and then not cancelling is worse than ignoring the key.
                return
            app._cancel = True
            app._say("Cancelling — waiting for the command to stop…")
        return
        event.stop()
        return
    if event.key in ("pageup", "pagedown"):
        # The ONLY keys that scroll. `up`/`down` move the selection, so a screen taller than the
        # terminal had no way to reach its own bottom — the operator saw a wordmark and nothing
        # they could act on.
        app.query_one("#scroll").scroll_page_down() if event.key == "pagedown" else app.query_one(
            "#scroll"
        ).scroll_page_up()
        event.stop()
        return
    if event.key in ("up", "down") and app._options:
        delta = 1 if event.key == "down" else -1
        app._selected = (app._selected + delta) % len(app._options)
        app._paint_choices()
        event.stop()
    elif event.key == "escape":
        event.stop()
        if app._field_for == "db_url":
            # The prompt is a sub-screen of the database step. `back` walks the SPINE, so Esc here
            # skipped past the options screen the prompt was opened from.
            await enter_steps.database(app)
            return
        await back(app)
    elif event.key == "enter":
        if app._field_for:
            # NOT stopped and NOT handled: the field's own `Submitted` is the single path to
            # `_submit_field`, and taking it here as well submits twice.
            return
        event.stop()
        await confirm(app)


async def abandon(app: SetupApp) -> None:
    if app._busy:
        # A worker finishing would call `_finish_action` and repaint over the picker, throwing away
        # a selection the operator was in the middle of making.
        app._note("Wait for the current step to finish.", error=True)
        return
    await uninstall_flow.abandon(app)


def leave(app: SetupApp) -> None:
    """Exit status. Non-zero unless the instance got an account, OR the operator deliberately
    removed it — Ctrl-Q on the "Removed" screen used to report FAILURE for a removal that
    succeeded, while Enter on the same screen reported success."""
    from mosaera_api.setup.app import CONFIGURED_STEP, REMOVED_STEP

    done = "admin" in app.completed or app.step in (REMOVED_STEP, CONFIGURED_STEP)
    app.exit(0 if done else 1)


async def back(app: SetupApp) -> None:
    from mosaera_api.setup.app import CONFIGURED_STEP, REMOVED_STEP, STEPS, UNINSTALL_STEP

    if app.step in (CONFIGURED_STEP, REMOVED_STEP):
        return  # nothing behind "already done" or "already removed"
    if app.step == UNINSTALL_STEP:
        await app._goto(app._returns_to)
        return
    if app.step == "uninstall_confirm":
        # Through the same path as the Cancel row, which was written specifically to preserve the
        # selection. Esc was still routing through `_goto` and clearing it.
        await uninstall_flow.confirmed(app, 0)
        return
    index = STEPS.index(app.step)
    if index == 0:
        app._going_back = False
        return
    app.step = STEPS[index - 1]
    app.completed.discard(app.step)
    app._going_back = True
    await app._enter(app.step)


async def confirm(app: SetupApp) -> None:
    if app._field_for:
        await app._submit_field()
    elif app._options:
        await app._choose(app._selected)
    else:
        await app._advance()


async def advance(app: SetupApp) -> None:
    from mosaera_api.setup.app import STEPS

    app._going_back = False
    app.completed.add(app.step)
    if app.step == "done":
        app.exit(0)  # the advertised way to finish now finishes
        return
    if app.step not in STEPS:
        # Every screen off the spine. `STEPS.index` raised for all of them, so a stray advance from
        # one crashed the wizard.
        return
    app.step = STEPS[STEPS.index(app.step) + 1]
    await app._enter(app.step)
