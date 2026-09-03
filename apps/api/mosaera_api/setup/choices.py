"""What each screen's selections DO.

Split from `app.py` at the 500-line ceiling, along a real seam: this module is the only place that
maps a chosen row to an action, so the mapping cannot be spread across seven step methods and drift.

One rule worth keeping: the database step dispatches on the row's LABEL, not its index. Its offers
are conditional on what is actually wrong, so a positional map would run the wrong action the moment
the cause changed — which is exactly the class of bug that made the step a dead end to begin with.
"""

from __future__ import annotations

import dataclasses
import secrets
from pathlib import Path
from typing import TYPE_CHECKING

from mosaera_memory import MemoryStore

from mosaera_api.setup import done_flow, launch, password_reset, screens, uninstall_flow
from mosaera_api.setup.enter_steps import new_secret_key
from mosaera_api.setup.env_file import effective_env, port_from, write_env_file
from mosaera_api.setup.explain import explain
from mosaera_api.setup.prereq_bridge import missing_now
from mosaera_api.setup.steps import access_env, with_timeout

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mosaera_api.setup.app import SetupApp


async def dispatch(app: SetupApp, index: int) -> None:
    if app.step == "machine":
        gaps = missing_now(app)
        if index >= len(gaps):
            await app._advance()
            return
        await app._install(gaps[index])
    elif app.step == "reset":
        await password_reset.chose(app, index)
    elif app.step == "database":
        await _database(app, index)
    elif app.step == "access":
        # 0 = loopback, 1 = network behind HTTPS, 2 = network over plain http. The TLS answer
        # rides the choice because #124 requires the operator to DECLARE it (see `screens.access`).
        await app._set_access(public=index in (1, 2), secure=index == 1)
    elif app.step == "done":
        await done_flow.chose(app, index)
    elif app.step == "uninstall":
        await uninstall_flow.confirmed(app, index)
    elif app.step == "uninstall_confirm":
        await uninstall_flow.confirmed(app, index)
    elif app.step == "removed":
        app.exit(0)
    elif app.step == "configured":
        await _configured(app, index)
    else:
        await app._advance()


async def set_access(app: SetupApp, *, public: bool, secure: bool = False) -> None:
    """Write the bind, and say exactly what happened to the service token.

    Idempotence lives in `access_env`, which computes against what is ALREADY in `.env` — the first
    version minted a fresh token on every run and silently invalidated every credential already
    issued while the screen reported success.
    """
    env_path = app.repo_root / ".env"
    current = effective_env(env_path)
    port = port_from(current, "MOSAERA_API_PORT", 8000)
    changes = access_env(
        public=public,
        secure=secure,
        port=port,
        current=current,
        make_token=lambda: secrets.token_urlsafe(24),
        make_secret_key=new_secret_key,
    )
    if changes and not _write_env(app, env_path, changes):
        return
    # `mosaera-api` reads its environment at START. A live process cannot see a bind, port or token
    # we just rewrote, so writing them while it runs and saying nothing is a no-op the operator has
    # every reason to read as applied — and going network -> this-machine-only that way leaves the
    # instance REACHABLE, which is the opposite of what they asked for. Reported 2026-08-31.
    if changes:
        app._needs_restart = True
    # NOT a toast. What happened to the service token is the one message here that has to outlive
    # its own screen: it is decided on the access step and answered on the finished screen, where
    # someone is looking for how to reach this instance. Shown as a toast it either vanished with
    # the very `_advance` below, or — before toasts were cleared on a step change — rode into the
    # administrator step and sat above its key hints reading like an instruction for it.
    if public:
        minted = "MOSAERA_API_TOKEN" in changes
        how = "behind HTTPS" if secure else "over plain http"
        app._access_note = (
            f"Reachable on your network {how} — a service token was generated."
            if minted
            else f"Reachable on your network {how} — your existing service token was kept."
        )
    else:
        cleared = changes.get("MOSAERA_API_TOKEN") == ""
        app._access_note = (
            "Bound to this machine only — the old service token was cleared."
            if cleared
            else "Bound to this machine only."
        )
    await app._advance()


async def _configured(app: SetupApp, index: int) -> None:
    """Dispatched on the row's TEXT, not its position.

    A row here is conditional — "Build the sandbox images" appears only when there are any — and a
    positional map is what made the database step run the wrong action the moment its rows changed.
    The same mistake was one edit away here.
    """
    label = app._options[index] if index < len(app._options) else ""

    if label == screens.BUILD_IMAGES:
        # The gap this screen reports, closed from the screen that reports it. Re-running setup
        # walks the whole spine to reach the same build, which is what made this a dead end.
        app._begin("Sandbox images", "Building. Esc cancels.")
        app._images_worker()
        return

    if label.startswith(("Start", "Stop")):
        host, port = done_flow.bind(app)
        if not launch.already_serving(host, port):
            await app._goto("done")  # the same path that starts it at the end of a first run
            return
        # STOP it. Nothing is deleted and nothing is asked twice: bringing a server down loses no
        # data, so the confirmation an uninstall earns would only be ceremony here.
        problem = launch.stop(app.settings.home, app.repo_root)
        if problem:
            app._note(f"Could not stop it — {problem}", error=True)
        else:
            app._note("Mosaera has been stopped. Its data and configuration are untouched.")
        # Repaint rather than exit, so the row that now reads "Start Mosaera" is the one under the
        # cursor — the operator who stopped it by mistake is one Enter from undoing that. Through
        # the readiness probe, so the screen is drawn from what the machine SAYS rather than from
        # what this branch just tried to do; `stop` reports the process's state, but the screen is
        # about the port, and those are the two facts this wizard has repeatedly conflated.
        from mosaera_api.setup import enter_steps  # local: it imports this module

        enter_steps.reprobe(app)
        return

    if label == "Re-run setup":
        app._rerunning = True
        await app._goto("welcome")
        return

    if label == "Reset a password":
        app._returns_to = "configured"
        await password_reset.enter(app)
        return

    await uninstall_flow.abandon(app)


async def _database(app: SetupApp, index: int) -> None:
    """Two rows, dispatched on TEXT. See `screens.USE_BUNDLED`."""
    label = app._options[index] if index < len(app._options) else ""
    if label == screens.USE_BUNDLED:
        await app._start_database()
    elif label == screens.POINT_ELSEWHERE:
        _ask_for_url(app)
    elif label == screens.PUBLISH_FOR_HOST:
        await _publish_for_host(app)
    elif label == screens.RESET_BUNDLED:
        # Recorded, not performed here: the teardown shells out, so it belongs on the worker with
        # the rest of the bundled-database work rather than on the UI thread.
        app._db_reset = True
        await app._start_database()


def ask_for_port(app: SetupApp, problem: str = "") -> None:
    from mosaera_api.setup.steps import database_port, next_free_port

    taken = database_port()
    app._paint(screens.database_port_prompt(next_free_port(taken + 1), taken, problem))
    app._ask("", secret=False, for_field="db_port", hint="Enter to use it  ·  Esc to go back")


async def submit_db_port(app: SetupApp, value: str) -> None:
    """Take a port, CHECK IT IS FREE, and only then keep it — then start the database on it.

    Same order as `submit_db_url`, for the same reason: writing first and testing after would leave
    `.env` naming a port that cannot be published on, and the next run would begin from that broken
    value with no memory of what it replaced.

    ONE write covers both halves. `MOSAERA_DB_PORT` drives the published port and the DSN, and
    Compose reads `.env` from the project directory (`compose_argv --project-directory`), so the
    container and the client cannot end up on different numbers — which is the failure this whole
    screen exists to repair.
    """
    import os

    from mosaera_api.setup.steps import port_is_free

    raw = value.strip()
    try:
        port = int(raw)
    except ValueError:
        ask_for_port(app, f"{raw!r} is not a port number. Enter a number between 1024 and 65535.")
        return
    if not 1024 <= port <= 65535:
        # Below 1024 needs root to publish, which this wizard will not ask for.
        ask_for_port(app, "Choose a port between 1024 and 65535.")
        return
    if not port_is_free(port):
        ask_for_port(app, f"Port {port} is also in use. Try another.")
        return

    if not _write_env(app, app.repo_root / ".env", {"MOSAERA_DB_PORT": str(port)}):
        return
    # The PROCESS environment too. `.env` is merged at startup, so a value written now reaches
    # Compose (which re-reads the file) but not `database_port()`, which asks `os.environ` — and
    # the two disagreeing is exactly the split this is fixing.
    os.environ["MOSAERA_DB_PORT"] = str(port)
    app._port_conflict = False
    await app._start_database()


def ask_for_api_port(app: SetupApp, problem: str = "") -> None:
    from mosaera_api.setup.env_file import effective_env, port_from
    from mosaera_api.setup.steps import next_free_port

    taken = port_from(effective_env(app.repo_root / ".env"), "MOSAERA_API_PORT", 8000)
    app._paint(screens.api_port_prompt(next_free_port(taken + 1), taken, problem))
    app._ask("", secret=False, for_field="api_port", hint="Enter to use it  ·  Esc to go back")


async def submit_api_port(app: SetupApp, value: str) -> None:
    """Take a port, CHECK IT IS FREE, and only then keep it — then start on it.

    Same order as `submit_db_port`, for the same reason: writing first and testing after would
    leave `.env` naming a port that cannot be bound, and the next run would begin from that broken
    value with no memory of what it replaced.
    """
    import os

    from mosaera_api.setup.steps import port_is_free

    raw = value.strip()
    try:
        port = int(raw)
    except ValueError:
        ask_for_api_port(
            app, f"{raw!r} is not a port number. Enter a number between 1024 and 65535."
        )
        return
    if not 1024 <= port <= 65535:
        ask_for_api_port(app, "Choose a port between 1024 and 65535.")
        return
    if not port_is_free(port):
        ask_for_api_port(app, f"Port {port} is also in use. Try another.")
        return
    if not _write_env(app, app.repo_root / ".env", {"MOSAERA_API_PORT": str(port)}):
        return
    # The PROCESS environment too, for the same split `submit_db_port` documents: `.env` is what a
    # relaunch reads, `os.environ` is what THIS process reads when it works out where to serve.
    os.environ["MOSAERA_API_PORT"] = str(port)
    app._api_port_conflict = False
    await app._goto("done")


def _ask_for_url(app: SetupApp, problem: str = "") -> None:
    app._paint(screens.database_url_prompt(problem))
    # No placeholder: the screen already carries the example on its own line UNDER the rule, where
    # it survives the first keystroke. Both at once printed it twice.
    app._ask("", secret=False, for_field="db_url", hint="Enter to test it  ·  Esc to go back")


async def submit_db_url(app: SetupApp, value: str) -> None:
    """Take an operator's URL, TEST IT, and only then keep it.

    Order matters and is the whole point: `open_or_reason` opens *and migrates*, so a URL that
    reaches this far is known to work rather than merely to parse. Writing first and testing after
    would leave `.env` pointing at a database that does not answer, and the next run would start
    from that broken value with no memory of what it replaced.
    """
    url = value.strip()
    if not url:
        _ask_for_url(app, "A URL is needed.")
        return
    if not url.startswith(("postgresql://", "postgresql+psycopg://", "postgres://")):
        _ask_for_url(app, "That is not a PostgreSQL URL — it must start with postgresql:// .")
        return
    app._say("Opening it…")
    # Bounded — this runs in a key handler, and an unreachable host would freeze the wizard here.
    store, reason = MemoryStore.open_or_reason(with_timeout(url))
    if store is None:
        why = explain(reason)
        _ask_for_url(app, f"{why.summary} {why.action}".strip())
        return
    if not _write_env(app, app.repo_root / ".env", {"MOSAERA_DB_URL": url}):
        return
    app.settings = dataclasses.replace(app.settings, db_url=url)
    app._note("Database opened and migrated")
    await app._advance()


def _write_env(app: SetupApp, path: Path, changes: dict[str, str]) -> bool:
    """Write `.env`, or say why not. Returns whether it worked.

    These two call sites run on the UI thread inside a key handler, where `_guarded` — which exists
    for exactly this, and whose docstring names "a read-only checkout reaching `write_env_file`" —
    does not reach. Unwrapped, a read-only checkout or a full disk raised out of `on_key` and
    Textual tore the wizard down mid-flow.
    """
    try:
        write_env_file(path, changes)
    except OSError as exc:
        app._note(f"Could not write {path.name} — {explain(str(exc)).summary}", error=True)
        return False
    return True


async def _publish_for_host(app: SetupApp) -> None:
    """Republish the bundled database at an address this machine can actually reach.

    The container has to be recreated for a changed publish to take effect, so this is a `down`
    WITHOUT `--volumes` — the data is not the problem and must survive. One write again covers both
    halves: `.env` is what Compose reads, `os.environ` is what this process reads.
    """
    import os

    from mosaera_api.setup.steps import compose_down_argv, run_streaming

    # S104: the bind is INSIDE the Docker VM, which is the whole point — Colima and Lima forward a
    # 0.0.0.0-published port out to this machine and leave a 127.0.0.1 one unreachable. The host
    # side stays loopback. The operator chose this on a screen that states the trade.
    all_interfaces = "0.0.0.0"  # noqa: S104
    if not _write_env(app, app.repo_root / ".env", {"MOSAERA_DB_BIND_HOST": all_interfaces}):
        return
    os.environ["MOSAERA_DB_BIND_HOST"] = all_interfaces
    run_streaming(
        compose_down_argv(app.settings, app.repo_root, volumes=False),
        lambda _line: None,
        app.repo_root,
    )
    await app._start_database()


#: Which coroutine answers each asked-for field. Defined HERE, beside the handlers themselves, so
#: adding one cannot mean editing a table in another module. Anything absent falls through to the
#: account step in `_submit_field`, which is the one place a stray value must never land.
FIELD_SUBMITS = {
    "reset1": password_reset.submit_first,
    "reset2": password_reset.submit_second,
    "db_url": submit_db_url,
    "db_port": submit_db_port,
    "api_port": submit_api_port,
}
