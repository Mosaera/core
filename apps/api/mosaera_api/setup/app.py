"""The first-run wizard's terminal UI (ADR-0116).

WHY THE TERMINAL. Only Postgres is containerised; the API runs on the host. Every install already
happens at a terminal, and a browser could not install Docker, start Postgres or write `.env` even
in principle — the web flow this replaces asked an operator to configure a machine from the one
place with no access to it.

THREE RULES THIS FILE KEEPS, each of which it broke once:

  - **Nothing slow runs on the UI loop.** Installs, builds and compose go to a worker thread, so the
    screen keeps repainting and the operator can cancel. Run inline, a twenty-minute build froze the
    display on one frame — the exact "indistinguishable from a hang" the streaming code exists to
    prevent.
  - **Anything that needs a password suspends the app.** `sudo` prompts on stdin; with Textual
    holding the terminal in raw mode that prompt is invisible and unanswerable, and the wizard
    deadlocks forever. `App.suspend()` hands the real terminal back for the duration.
  - **Running it again changes nothing.** Every step reads the machine first and writes only what
    differs. It used to mint a fresh service token on every run, silently invalidating every
    credential already issued.

The decisions live in `steps.py`, `prereqs.py` and `admin.py` — pure, and tested without a terminal.
This file renders them.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from mosaera_core.config import Settings
from mosaera_core.prereqs import Found, detect_platform
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical, VerticalScroll
from textual.events import Key
from textual.timer import Timer
from textual.widgets import Input, Static

from mosaera_api.setup import admin as admin_step
from mosaera_api.setup import (
    build_flow,
    choices,
    done_flow,
    enter_steps,
    keys,
    paint,
    resume,
    screens,
    timers,
)
from mosaera_api.setup.app_workers import SetupWorkers
from mosaera_api.setup.installer import install_with_consent
from mosaera_api.setup.ui import (
    MARK,
    Row,
    measure_for,
    mosaic,
    save_shot,
    task_list,
    toast,
)
from mosaera_api.setup.uninstall import (
    Removable,
)

# "images" was its own step and is not any more: building them is WORK, not a question, and it now
# happens inside `done` beside the dashboard build and the server launch. What is left is the shape
# an operator actually has to follow — check the machine, set up the database, make an account,
# choose who can reach it — and then one step where everything is brought up at once.
STEPS = ("welcome", "machine", "database", "access", "admin", "done")


#: Shown instead of the walk when there is nothing left to do.
CONFIGURED_STEP = "configured"
REMOVED_STEP = "removed"
UNINSTALL_STEP = "uninstall"


#: What the ribbon calls each step. "welcome" and "done" are bookends, not stops.
RIBBON = ("Machine", "Images", "Database", "Access", "Account")

#: How long a toast stays up. Long enough to read a sentence twice, short enough that it cannot
#: still be on screen when it stops being true.
TOAST_SECONDS = 10.0

#: How fast the spinner turns. Fast enough to read as motion, slow enough not to strobe.
_SPIN_SECONDS = 0.12

#: The longest a toast may be. Past this it is a diagnosis, and diagnoses live in `#detail`.
_NOTICE_LIMIT = 160


class SetupApp(SetupWorkers, App[int]):
    """The wizard. Exits 0 once the instance is set up, 1 if the operator leaves part-way."""

    CSS_PATH = "app.tcss"
    BINDINGS: ClassVar = [
        Binding("ctrl+q", "leave", "Leave", priority=True),
        # A full-screen app leaves nothing in the scrollback, so "what did you see?" is otherwise
        # unanswerable — this writes the current screen to a file that can be shared or attached.
        Binding("ctrl+s", "shot", "Save a screenshot", priority=True),
        # Reachable from EVERY step. Uninstall used to hang off the finished screen alone, so an
        # operator who changed their mind at step two had to complete a setup they did not want in
        # order to be allowed to remove it.
        # `priority=True` because Textual checks the FOCUSED widget's bindings first, and
        # `Input` binds ctrl+x to `cut` — so on the credential and URL prompts this chord was
        # cutting text while the docstring above claimed it worked on every step.
        Binding("ctrl+x", "abandon", "Stop and remove Mosaera", priority=True),
    ]
    TITLE = "Mosaera setup"

    def __init__(self, repo_root: Path) -> None:
        super().__init__()
        self.repo_root = repo_root
        self.settings = Settings.from_env()
        self.platform = detect_platform()
        self.step = "welcome"
        self.completed: set[str] = set()
        self._options: list[str] = []
        self._selected = 0
        self._field_for = ""
        self._username = ""
        #: The first of two password entries, cleared on every outcome; and the reset's account.
        self._password = ""
        self._reset_user: dict[str, object] | None = None
        self._busy = False
        self._cancel = False
        #: Survivable across a repaint: a failure must not be erased in the tick it is written.
        self._notice = ""
        #: What the access step decided about the service token, carried to the finished screen.
        self._access_note = ""
        #: Configuration was rewritten under a server that reads its environment only at
        #: START, so what it serves is stale until it is restarted. Set by the writers,
        #: cleared by `done_flow` once it has acted on it.
        self._needs_restart = False
        #: Uninstall selection, by index into `self._removable`.
        self._removable: list[Removable] = []
        self._chosen: set[int] = set()
        #: Set when the operator chose to remove the installation itself. Read by `__main__` AFTER
        #: `run()` returns — the removal cannot happen from inside this process, which lives in the
        #: directory it would delete, so the app records the intent and the launcher carries it out.
        self._remove_install: Path | None = None
        #: A server we did not start holds the database port. Sends the operator to the port fix.
        self._port_conflict = False
        self._api_port_conflict = False  #: same, for the dashboard's port
        #: The database refused our credentials and we started it. Offers the repair screen.
        self._db_stale = False
        #: The raw refusal, shown there — the wizard reports evidence rather than naming a cause.
        self._db_reason = ""
        #: Healthy container, unreachable client: the publish address is not one this host shares.
        self._db_unreachable = False
        #: Set when that reset is confirmed; `build_flow` clears the volume before bringing it up.
        self._db_reset = False
        #: Which way the operator is travelling. A step that is already satisfied must be stepped
        #: OVER, not bounced off — auto-skip used to be hard-coded forward, so Esc on the database
        #: step went back to `images`, found nothing to build, and advanced straight to `database`
        #: again. Backwards movement was dead through the whole middle of the flow.
        self._going_back = False
        #: Where Ctrl-X was pressed, so cancelling an abandon returns there rather than to "done".
        self._returns_to = "done"
        self._serving = False
        self._cancelled_launch = False
        self._attempted_launch = True
        #: False only for the removal, which runs to the end by design.
        self._cancel_allowed = True
        self._remaining = 0
        self._countdown: Timer | None = None
        #: The resume line is said ONCE per session. Stepping back to welcome is not "picking up
        #: where you left off" — you left off nowhere, you pressed Esc a moment ago.
        self._greeted = False
        self._toast: Timer | None = None
        self._notice_error = False
        #: The third timer in this application. All three — countdown, toast, spinner — are stopped
        #: on leaving the thing that started them; a timer that outlives its screen fires into the
        #: next one.
        self._spinner: Timer | None = None
        self._tick = 0
        self._status_line = ""
        #: The task list, kept so the spinner tick can repaint the running row.
        self._tasks: list[Row] = []
        #: Set by "Re-run setup" on the configured screen. Without it, welcome would re-detect the
        #: finished instance and bounce straight back to the screen the operator just left.
        self._rerunning = False
        #: The readiness probe runs once per session. It is slow, and re-running it on every return
        #: to welcome would freeze the screen each time.
        self._probed = False
        #: Set from the terminal width; picks the short form of every keys line.
        self._narrow = False

    # --- one shape for every screen ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        # The field sits BEHIND everything on its own layer, at the opacity the stylesheet gives it.
        yield Static(mosaic(240, 60), id="field")
        # The header is its own fixed region. It used to sit inside the centred stage, so every
        # change in content height shoved the wordmark up or down — measured across four screens it
        # landed at four different heights. It is the one thing that should never move.
        with Vertical(id="page"):
            with Center(id="header"):
                with Vertical(id="header-stage"):
                    yield Static(MARK, id="mark")
                    yield Static("GOVERNED EXECUTION", id="tagline")
                    yield Static("", id="ribbon")
            with VerticalScroll(id="scroll"), Center(), Vertical(id="stage"):
                yield Static("", id="title")
                yield Static("", id="body")
                # Directly under the body: the raw cause belongs with the claim it explains. It
                # used to sit below the choices, with the actions between explanation and evidence.
                yield Static("", id="detail")
                yield Static("", id="table")
                yield Static("", id="choices")
                # `#progress` BEFORE `#status`: the log line grows and shrinks with every line of
                # `docker build` output, and above the bars it reflowed the whole block on every
                # one of them.
                yield Static("", id="progress")
                yield Static("", id="status")
                yield Input(id="field-input", classes="hidden")
                # UNDER the rule, not inside the box. As the Input's placeholder the example
                # vanished at the first keystroke — exactly when it is most useful.
                yield Static("", id="field-note")
            # Docked above the hint: a toast is an overlay, not part of the column it interrupts.
            yield Static("", id="notice")
            # Docked, so the actions sit on the last row of every screen regardless of what is
            # above them. Inside the centred stage they floated to a different height per step.
            yield Static("", id="hint")

    async def on_mount(self) -> None:
        self._fit_mark()
        await self._enter(self.step)

    def exit(  # type: ignore[override]
        self,
        result: int | None = None,
        return_code: int = 0,
        message: object | None = None,
    ) -> None:
        # A `@work(thread=True)` build/probe still running when we exit makes `App.run()` never
        # return — asyncio's loop teardown joins the worker executor with no timeout — so the
        # operator's shell never comes back (CachyOS 2026-09-03: finished screen shown, terminal
        # held). Arm a daemon failsafe that force-exits just after Textual restores the terminal.
        # See `launch.arm_exit_failsafe`.
        from mosaera_api.setup import launch

        launch.arm_exit_failsafe(return_code)
        super().exit(result, return_code, message)  # type: ignore[arg-type]

    def on_resize(self) -> None:
        self._fit_mark()

    def _fit_mark(self) -> None:
        paint.fit(self)

    def _screen(
        self,
        *,
        title: str = "",
        body: str = "",
        choices: list[str] | None = None,
        hint: str = "",
    ) -> None:
        paint.blank_screen(self, title, body, choices or [], hint)

    def _paint(self, screen: screens.Screen) -> None:
        paint.screen(self, screen)

    def _paint_choices(self) -> None:
        paint.choices_list(self)

    def _paint_hint(self, line: str) -> None:
        """Rewrite only the hint. The countdown ticks through here rather than through `_paint`,
        which would reset the operator's place in the choice list once a second."""
        self.query_one("#hint", Static).update(line)

    def start_countdown(self) -> None:
        self.stop_countdown()
        self._countdown = self.set_interval(1.0, lambda: done_flow.tick(self))

    def stop_countdown(self) -> None:
        """Cancel the clock. Called on leaving the finished screen — a timer that closes the
        application is fine there and catastrophic one screen into an uninstall."""
        timers.stop(self, "_countdown")

    def _blanks(self) -> None:
        paint.collapse_empty(self)

    def _say(self, line: str) -> None:
        """Remember what the command last said. The spinner timer is what paints it."""
        self._status_line = line
        self._paint_status()

    def _paint_status(self) -> None:
        timers.paint_status(self)

    def start_spinner(self) -> None:
        timers.start_spinner(self)

    def stop_spinner(self) -> None:
        timers.stop(self, "_spinner")

    def _note(self, line: str, *, error: bool = False) -> None:
        """A toast. Survives the repaint that follows it, then clears itself.

        Two things it was getting wrong. A failure was the same colour as a success, so "Database
        created" and "Could not start Postgres" read identically at a glance. And it stayed on
        screen for the rest of the session, so a message about a step you fixed three screens ago
        was still there implying it had not been.
        """
        # ONE LINE, always. Call sites are supposed to pass explained text, and mostly do — but a
        # notice that can grow to ten centred lines of psycopg internals is a defect in the notice,
        # not only in whoever fed it. Capped here so no future call site can reintroduce the wall.
        line = " ".join(line.split())[:_NOTICE_LIMIT]
        self._notice, self._notice_error = line, error
        notice = self.query_one("#notice", Static)
        notice.update(toast(line, error=error) if line else "")
        notice.set_class(error, "error")
        self._blanks()
        self.clear_toast()
        if line:
            self._toast = self.set_timer(TOAST_SECONDS, self._expire_toast)

    def _expire_toast(self) -> None:
        self._notice = ""
        self._toast = None
        self.query_one("#notice", Static).update("")
        self._blanks()

    def clear_toast(self) -> None:
        """Cancel a pending expiry. Leaving a step must not leave a timer that fires into the next
        one — the same discipline the countdown keeps."""
        timers.stop(self, "_toast")

    @property
    def measure(self) -> int:
        """The width of the box every screen draws inside, for this terminal. See `ui.MEASURE`."""
        return measure_for(self.size.width)

    def _rows(self, rows: list[Row]) -> None:
        self._tasks = list(rows)
        self.query_one("#progress", Static).update(task_list(self._tasks, self._tick, self.measure))
        self._blanks()

    def _ask(self, placeholder: str, *, secret: bool, for_field: str, hint: str) -> None:
        paint.ask(self, placeholder, secret=secret, for_field=for_field, hint=hint)

    # --- movement -------------------------------------------------------------------------------

    async def on_key(self, event: Key) -> None:
        await keys.pressed(self, event)

    def action_shot(self) -> None:
        line, failed = save_shot(self)
        self._note(line, error=failed)

    async def action_abandon(self) -> None:
        await keys.abandon(self)

    def action_leave(self) -> None:
        keys.leave(self)

    async def _back(self) -> None:
        await keys.back(self)

    async def action_confirm(self) -> None:
        await keys.confirm(self)

    async def on_input_submitted(self, _event: Input.Submitted) -> None:
        await self._submit_field()

    async def _skip(self) -> None:
        """This step has nothing to show. Step over it in whichever direction we are travelling."""
        await self._back() if self._going_back else await self._advance()

    async def _advance(self) -> None:
        await keys.advance(self)

    async def _enter(self, step: str) -> None:
        # Any step but the last one cancels the clock. Leaving it running would let the installer
        # close itself part-way through an uninstall the operator started from the finished screen.
        if step != "done":
            self.stop_countdown()
        if step != self.step:
            # A toast belongs to the action that raised it, not to the wizard. It used to ride into
            # the next screen and sit above the key hints, reading as one more instruction.
            self.clear_toast()
            self._notice = ""
        if not self._busy:
            self.stop_spinner()
        resume.record(self.settings.home, step)
        await enter_steps.dispatch(self, step)

    # --- steps ----------------------------------------------------------------------------------

    async def _enter_welcome(self) -> None:
        self._going_back = False
        if not self._rerunning and not self._probed:
            # OFF THE UI THREAD. This probe is four `docker` calls, four `docker image inspect`s and
            # a database connect — up to forty seconds on a cold or wedged daemon, and it ran inline
            # on the very first frame. The loop was blocked, so there was no repaint, no key, and
            # not even Ctrl-Q: an empty stage, indistinguishable from a hang.
            self._begin("Checking this machine", "Looking at what is already set up.")
            self._probe_worker()
            return
        self._show_welcome()

    # The five thread workers live in `SetupWorkers` (mixed in above) — split out to keep this
    # file under the god-file ratchet; they run the slow half of a step off the UI loop.

    def _begin(self, title: str, body: str, hint: str = "Esc to cancel") -> None:
        """Enter a long action: mark busy so keys mean cancel, and say so.

        `hint` is overridable for the one action that is NOT cancellable — a half-finished removal
        is a state nothing can describe, so offering Esc there would be a lie.
        """
        self._busy, self._cancel, self._cancel_allowed = True, False, True
        self._status_line = ""
        # AND the rows behind it. Painting a screen blanks the widget, but the spinner tick redraws
        # it from `_tasks` — so the first tick of "Starting Mosaera" put the database step's three
        # rows back on screen, and the previous step's work flashed over the next one.
        self._tasks = []
        self._screen(title=title, body=body, hint=hint)
        self.start_spinner()

    def _finish_action(self, step: str | None = None) -> None:
        """Leave a long action. `step` repaints it; `None` moves on.

        `_going_back` is cleared: an action is a REPAIR, and a step that fixes itself must move on
        rather than reverse, however the operator arrived at it.

        `_busy` is NOT cleared here. It used to be, and the repaint was scheduled with `call_later`
        — so a keystroke in between reached `confirm` with the finished screen's empty options, and
        Enter meant "advance from the step that just completed", skipping the screen about to be
        painted. It is released in `_released` once the next screen exists.
        """
        self._cancel, self._going_back = False, False
        self._cancel_allowed = True
        self.stop_spinner()
        self.call_later(self._released, step)

    def _show_welcome(self) -> None:
        enter_steps.welcome(self)

    async def _enter_removed(self) -> None:
        """Already painted by the flow that got here. Re-entering must not repeat the work."""
        return

    async def _enter_done(self) -> None:
        await done_flow.enter(self)

    async def _choose(self, index: int) -> None:
        await choices.dispatch(self, index)

    async def _goto(self, step: str) -> None:
        """Jump to a named step — the paths that are not simply forward.

        A jump is never "backwards". `_going_back` used to survive it, so a step that auto-skipped
        on arrival skipped in the wrong DIRECTION: install the last missing prerequisite, and the
        wizard congratulated you by returning to the welcome screen.

        The notice is NOT cleared here. Clearing it erased the very message the jump was made to
        deliver — every success toast this wizard writes was being wiped in the same tick.
        """
        self._going_back = False
        self.step = step
        await self._enter(step)

    async def _install(self, found: Found) -> None:
        line, failed = install_with_consent(self, found)
        self._note(line, error=failed)
        self._going_back = False  # a repair moves forward
        await enter_steps.machine(self)

    async def _start_database(self) -> None:
        self._begin("Database", "Starting Postgres, creating it, applying the schema. Esc cancels.")
        self._database_worker()

    async def _released(self, step: str | None) -> None:
        """The next screen, and only then the keyboard."""
        self._busy = False
        await self._enter(step) if step else await self._advance()

    async def _set_access(self, *, public: bool, secure: bool = False) -> None:
        await choices.set_access(self, public=public, secure=secure)

    async def _submit_field(self) -> None:
        if not self._field_for:
            return  # nothing is being asked; a stray Submitted must not reach the account path
        value = self.query_one("#field-input", Input).value
        # A table, not a ladder — an unrouted field falls through to the ACCOUNT path.
        submit = choices.FIELD_SUBMITS.get(self._field_for)
        if submit is not None:
            await submit(self, value)
            return
        await admin_step.submit(self, self._field_for, value)
