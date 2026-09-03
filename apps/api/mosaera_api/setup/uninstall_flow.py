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
from mosaera_api.setup.ui import RUNNING, Row
from mosaera_api.setup.uninstall import Removable, perform, plan
from mosaera_api.setup.uninstall_text import summary, survives

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mosaera_api.setup.app import SetupApp

#: A ceiling per removal command. Removal cannot be cancelled by design, so the bound is the only
#: thing standing between a hung daemon and an unusable terminal.
_COMMAND_TIMEOUT = 180.0

#: The two screens Ctrl-X must not re-enter: it is already where it would take you.
_UNINSTALL = ("uninstall", "uninstall_confirm", "removed")


async def enter(app: SetupApp, lead: str = "") -> None:
    """Arriving at the uninstall. ONE screen, everything of ours selected.

    It used to be a nine-row checklist that started empty. Friction should match severity, and a
    checklist was friction without protection — it asked the operator to assemble the removal, and
    the obvious assembly was wrong: every destructive row arrived unticked, so ticking only
    "Remove Mosaera itself" left the database volume AND the running server behind while the
    screen reported success. Both were reported live. "Uninstall" is one decision.

    Cancelling must return where the operator came FROM. `_returns_to` was set only by Ctrl-X, so
    reaching this screen any other way left a stale value.
    """
    if app.step not in _UNINSTALL:
        app._returns_to = app.step
    app.step = "uninstall_confirm"
    app._removable = plan(app.settings, app.settings.home, app.repo_root)
    # SHARED artefacts are not ours to take (ADR-0119 §3). They leave the selection entirely
    # rather than sitting on it unticked, and are named below instead.
    app._chosen = {i for i, r in enumerate(app._removable) if r.key not in _SHARED}
    _paint_confirm(app, lead)


#: Removable keys that belong to more than this install. Never removed; always named.
_SHARED = frozenset({"uv_cache"})


def _paint_confirm(app: SetupApp, lead: str = "") -> None:
    selected = [app._removable[i] for i in sorted(app._chosen)]
    shared = [r for r in app._removable if r.key in _SHARED]
    leaves = lead + ("\n\n" if lead else "")
    leaves += "Only what this wizard installed is removed; anything already here is left alone."
    if shared:
        leaves += "\n\nLeft in place — shared with your other projects:\n" + "\n".join(
            f"  · {r.label}" for r in shared
        )
    extra = survives(selected, app._removable)
    if extra:
        leaves += "\n\n" + extra
    app._paint(screens.uninstall_confirm(summary(selected), leaves, len(selected)))


async def abandon(app: SetupApp) -> None:
    """Ctrl-X from anywhere: stop, and give the machine back.

    Reachable from EVERY step, because the alternative was requiring an operator to finish a setup
    they had decided against in order to be allowed to undo it.
    """
    if app.step in _UNINSTALL:
        return
    app.stop_countdown()
    app._notice = ""
    saved, app.step = app.step, "uninstall_confirm"
    await enter(app)
    app._returns_to = saved


async def confirmed(app: SetupApp, index: int) -> None:
    if index == 0:  # Cancel — the row the cursor starts on
        await app._goto(app._returns_to)
        return
    await run(app)


def _with_implied(removable: list[Removable], chosen: set[int]) -> set[int]:
    """Removing the installation IMPLIES stopping its server.

    The rows arrive unticked, which is right for destructive ones — but "Remove Mosaera itself"
    deletes the install directory, and the data home nests inside it, so it takes `api.pid` with
    it. That pid file is the ONLY handle `our_pid` has on the running server. Leave the server
    ticked off and the installation goes while the process stays, now unfindable by the wizard
    that started it and by every later one: it holds port 8000, answers /healthz, and the next
    install concludes it is already serving and skips its own build and launch entirely.

    Observed end to end on macOS 2026-08-31 — a "fresh" install that never built its dashboard and
    never started, reporting success over a stranger's process.

    Stopping a server destroys NOTHING, so this is not the pre-armed destructive checklist the
    unticked rule protects against. It is a precondition of the row the operator did tick.
    """
    keys = {removable[i].key for i in chosen}
    if "install" not in keys or "server" in keys:
        return chosen
    server = next((i for i, r in enumerate(removable) if r.key == "server"), None)
    return chosen if server is None else chosen | {server}


async def run(app: SetupApp) -> None:
    """Start the removal. The work itself goes to a thread — see `work`."""
    app._chosen = _with_implied(app._removable, app._chosen)
    selected = [app._removable[i] for i in sorted(app._chosen)]
    if not selected:
        await app._goto(app._returns_to)
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
