"""Running slow work off the UI loop, so that nothing it does can take the wizard down.

Everything in this package that touches Docker, the network or the database goes through here. The
rule is one sentence: **a worker either finishes its own way or lands here, and either way the step
is repainted and the keyboard comes back.**

Two faults this exists for, and they compound. `@work(thread=True)` defaults to
`exit_on_error=True`, so an unexpected exception — a read-only checkout reaching `write_env_file`,
a full disk, a `NoMatches` on an unmounted tree — tore the application down with a traceback over
the top of a ten-minute install. And on that path `_finish_action` was never reached, so `_busy`
stayed True forever: every key swallowed, Esc setting a flag nobody polled, and the wizard
unkillable except by the quit chord.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mosaera_api.setup.app import SetupApp


def guarded(app: SetupApp, body: Callable[[], None], step: str) -> None:
    """Run a worker body so that NOTHING it does can strand the wizard."""
    from mosaera_api.setup import done_flow
    from mosaera_api.setup.explain import explain

    try:
        body()
    except Exception as exc:
        app.call_from_thread(app._note, explain(str(exc)).summary, error=True)
        if step == "done":
            # "done" is the ONE step whose entry starts work by itself, so repainting it after a
            # failure re-launches the thing that just failed — forever, with `_busy` True and
            # `_cancel` reset on every lap. Land on the screen instead.
            app.call_from_thread(done_flow.failed, app)
            return
        if step == "welcome":
            # Likewise: the readiness probe is started BY entering welcome.
            from mosaera_api.setup import enter_steps  # local: it imports this module

            app.call_from_thread(enter_steps.probed, app, None)
            return
        app.call_from_thread(app._finish_action, step)
