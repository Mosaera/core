"""Putting a `Screen` on the terminal.

Split from `app.py` along the seam between DECIDING what a step says and DRAWING it. Every function
here takes the application and touches widgets; none of them decide anything, which is why the copy
in `screens.py` and the probes in `enter_steps.py` can be tested without a terminal at all.

One shape draws every step. That is deliberate and load-bearing: a step with its own paint routine
drifts away from the others, and this wizard has already paid for that once — the credential Input
kept focus while hidden, so Enter on the welcome screen reached the account path with empty
credentials.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import Input, Static

from mosaera_api.setup import screens
from mosaera_api.setup.ui import (
    choice_list,
    compact,
    header_rows,
    mark_for,
    show_tagline,
    step_ribbon,
    toast,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mosaera_api.setup.app import SetupApp

#: The keys line, in two lengths. A hint naming a key the screen does not handle is the cheapest
#: way to teach an operator that the interface does not mean what it says — hence the separate
#: first-screen form, which has nothing behind it to go back to. The long line is 87 columns and
#: wrapped to two rows at 80, orphaning its last word exactly where the screen has no rows spare.
ENTER_HINT = (
    "Enter to continue  ·  Esc to go back  ·  Ctrl-X to stop and remove  ·  Ctrl-Q to leave"
)
FIRST_HINT = "Enter to continue  ·  Ctrl-X to stop and remove  ·  Ctrl-Q to leave"
NARROW_HINT = "Enter  ·  Esc back  ·  Ctrl-X remove  ·  Ctrl-Q quit"
NARROW_FIRST_HINT = "Enter  ·  Ctrl-X remove  ·  Ctrl-Q quit"
UNINSTALL_HINT = "Space to toggle  ·  Enter to continue  ·  Esc to go back"

#: Below this many columns the long forms do not fit on one row.
NARROW_COLUMNS = 92


def keys_hint(app: SetupApp, *, first: bool = False) -> str:
    if first:
        return NARROW_FIRST_HINT if app._narrow else FIRST_HINT
    return NARROW_HINT if app._narrow else ENTER_HINT


#: Widgets that cost their padding even when empty — collapsed rather than merely blanked, or a
#: screen with no table, choices or progress reserves a hand's width of nothing.
MAYBE_EMPTY = (
    "#table",
    "#choices",
    "#status",
    "#progress",
    "#detail",
    "#notice",
    "#field-note",
)


def blank_screen(app: SetupApp, title: str, body: str, choices: list[str], hint: str) -> None:
    """Reset every region, then write the four things every screen has."""
    app._options = choices
    app._selected = 0
    app._field_for = ""
    app.query_one("#title", Static).update(title)
    app.query_one("#body", Static).update(body)
    for empty in ("#table", "#detail", "#status", "#progress", "#field-note"):
        app.query_one(empty, Static).update("")
    # The state behind `#progress`, not only the widget: the spinner tick repaints the list from
    # `_tasks`, so a list left there outlives the screen it belongs to by exactly one tick.
    app._tasks = []
    app._status_line = ""
    app.query_one("#hint", Static).update(hint or keys_hint(app))
    # The notice is NOT cleared here — a failure has to outlive the repaint that follows it.
    app.query_one("#notice", Static).update(
        toast(app._notice, error=app._notice_error) if app._notice else ""
    )
    header(app, title)
    choices_list(app)
    field = app.query_one("#field-input", Input)
    field.add_class("hidden")
    # Disabled, not merely hidden: hidden kept focus, so Enter reached it and the submit handler
    # walked into the account path with empty credentials.
    field.disabled = True
    field.value = ""


def screen(app: SetupApp, spec: screens.Screen) -> None:
    blank_screen(app, spec.title, spec.body, spec.choices, spec.hint)
    # After the reset, which clears them: a table belongs to one step, never to the next.
    app.query_one("#table", Static).update(spec.table)
    app.query_one("#detail", Static).update(spec.detail)
    app.query_one("#field-note", Static).update(spec.note)
    # A screen carrying a raw cause is reporting a failure: left-align its prose.
    app.query_one("#body", Static).set_class(bool(spec.detail), "error")
    collapse_empty(app)


def header(app: SetupApp, _step_name: str = "") -> None:
    """The wordmark, the strapline, and the ribbon — on every screen.

    It briefly did not: the working steps wore a one-line `MOSAERA  ▰▰▰▱▱  Database` bar, to buy
    back the twelve rows the art costs. The rows were not the problem — the problem was that the
    content floated in the space they left, which the box's own height now settles. So the mark is
    back everywhere, and it is the one thing on screen that never moves.

    The ribbon carries NO label. It sits directly above a heading naming the same step, and the
    heading says it better (`Database — port 5432`, not `Database`).
    """
    from mosaera_api.setup.app import RIBBON, STEPS
    from mosaera_api.setup.ui import header_rows

    index = {n: i for i, n in enumerate(STEPS[1:-1])}.get(app.step, -1)
    # Set here, not left to the stylesheet: `fit` writes inline height and display on a resize, and
    # an inline style beats a class every time.
    app.query_one("#header").styles.height = header_rows(app.size.height)
    app.query_one("#mark").display = True
    app.query_one("#tagline").display = show_tagline(app.size.height)
    app.query_one("#ribbon", Static).update(step_ribbon(len(RIBBON), index) if index >= 0 else "")


def choices_list(app: SetupApp) -> None:
    app.query_one("#choices", Static).update(
        choice_list(app._options, app._selected) if app._options else ""
    )


def ask(app: SetupApp, placeholder: str, *, secret: bool, for_field: str, hint: str) -> None:
    field = app.query_one("#field-input", Input)
    field.remove_class("hidden")
    field.disabled = False
    field.password = secret
    field.placeholder = placeholder
    field.value = ""
    app._field_for = for_field
    # The rule that applies to the field being SHOWN — the password rule used to be invisible
    # because the username's was still on screen.
    app.query_one("#hint", Static).update(hint)
    field.focus()


def collapse_empty(app: SetupApp) -> None:
    for sel in MAYBE_EMPTY:
        node = app.query_one(sel, Static)
        node.set_class(not str(node.render()).strip(), "blank")


def fit(app: SetupApp) -> None:
    """Fit the header to the terminal, in BOTH axes. Re-checked on resize, because a window that
    grows should get the full mark back rather than keep the compromise.

    Height was never considered, and the header is the one fixed-height region on screen — so a
    24-row terminal gave 17 rows to a logotype and pushed the choice list off the bottom, with no
    key bound to scrolling it back.
    """
    rows, cols = app.size.height, app.size.width
    app.query_one("#mark", Static).update(mark_for(cols, rows))
    app.query_one("#tagline", Static).display = show_tagline(rows)
    app.query_one("#header").styles.height = header_rows(rows)
    app.set_class(compact(rows), "compact")
    app._narrow = cols < NARROW_COLUMNS
