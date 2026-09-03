"""The database step's REPAIRS — the two failures that look identical and are opposite.

"Postgres rejected the password" is one sentence covering two problems. A server that was already
answering before setup touched anything is somebody else's, and the fix is to move off its port. A
container we started ourselves that still refuses us is OUR problem, and the fix is that the bundled
volume predates these credentials.

The second one is why `rm -rf ~/.mosaera` never helped: that volume is a named Docker volume living
inside the Docker or Colima VM, not under the install directory. Postgres applies POSTGRES_PASSWORD
only when it initialises an EMPTY data directory, so an attempt interrupted before `initdb` finished
leaves a volume that every later run reuses and every later run is rejected by.

Split out of `test_setup_flow.py` at the god-file ceiling, on the seam it already had.
"""

from __future__ import annotations

from pathlib import Path


def test_a_foreign_server_on_the_port_is_named_as_the_cause(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The failure the wizard has always been able to see, and never said.

    `build_flow` already distinguishes "a server is answering on the port" from "we started the
    container" — the comment there says a system Postgres on 5432 "was being adopted, migrated into,
    and written to `.env`". What it did not do was carry that fact forward, so when the foreign
    server refused our credentials the operator was told "Postgres started, but the schema failed —
    Postgres rejected the password". Wrong twice: nothing of ours started, and the password is not
    the problem. The remedy — move MOSAERA_DB_PORT — is documented in `.env.example` and
    `compose.yaml` and had never reached the screen at the moment it was needed.
    """
    from mosaera_api.setup.build_flow import _credentials_note, _is_auth_failure

    assert _is_auth_failure('FATAL:  password authentication failed for user "mosaera"')
    assert _is_auth_failure('FATAL:  role "mosaera" does not exist')
    # Not everything that goes wrong is someone else's server. A refused connection means nothing
    # is there at all, and a missing database is ours to create.
    assert not _is_auth_failure("could not connect to server: Connection refused")
    assert not _is_auth_failure('database "mosaera" does not exist')
    assert not _is_auth_failure("")

    # The note only REPORTS. The repair is the screen that comes next, so this must not send the
    # operator anywhere — not to a menu row, and not to a shell.
    note = _credentials_note(5432, adopted=True)
    assert "5432" in note
    assert "not the bundled database" in note
    assert "password" not in note.lower(), "do not repeat the diagnosis that was wrong"
    assert "MOSAERA_DB_PORT" not in note, "the wizard fixes this; it does not delegate it"


def test_a_port_conflict_is_fixable_in_the_wizard(tmp_path: Path) -> None:
    """Naming a problem the tool is holding the fix for is a diagnosis, not a fix.

    The wizard could see that something else held the database port — it reports "a server is
    answering on the port" rather than "running" — and its answer was to tell the operator to leave,
    set MOSAERA_DB_PORT in a shell, and start over. The row now appears where the problem is shown.
    """
    import asyncio
    import os
    import socket

    from mosaera_api.setup import choices, screens
    from mosaera_api.setup.app import SetupApp
    from mosaera_api.setup.env_file import read_env_file

    held = socket.socket()
    held.bind(("127.0.0.1", 0))
    held.listen()
    taken = held.getsockname()[1]

    # NO THIRD ROW. The recommended path carries its own repair: adding a row put "(recommended)"
    # on the option that had just failed and made the fix read as a departure from it.
    assert screens.database(object(), 5432).choices == [
        screens.USE_BUNDLED,
        screens.POINT_ELSEWHERE,
    ]

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test(size=(120, 42)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            os.environ["MOSAERA_DB_PORT"] = str(taken)
            app.step = "database"
            app._port_conflict = True

            # Rejected, each for its own reason, and the screen keeps asking rather than giving up.
            for bad, expected in (
                ("abc", "not a port number"),
                ("80", "between 1024 and 65535"),  # below 1024 needs root to publish
                (str(taken), "also in use"),
            ):
                await choices.submit_db_port(app, bad)
                await pilot.pause()
                body = app.query_one("#body").render_line(0).text
                assert expected in body, f"{bad!r} -> {body!r}"
                assert not read_env_file(app.repo_root / ".env").get("MOSAERA_DB_PORT"), (
                    "a rejected port must never reach `.env`"
                )

    try:
        asyncio.run(_body())
    finally:
        held.close()
        os.environ.pop("MOSAERA_DB_PORT", None)


def test_a_chosen_port_reaches_both_compose_and_the_client(tmp_path: Path) -> None:
    """ONE write has to cover both halves, or the container and the client end up on different
    numbers — which is the split this whole screen exists to repair.

    `.env` is what Compose reads (`compose_argv --project-directory`); `os.environ` is what
    `database_port()` asks. Writing only one of them would fix the symptom and keep the disease.
    """
    import asyncio
    import os

    from mosaera_api.setup import choices
    from mosaera_api.setup.app import SetupApp
    from mosaera_api.setup.env_file import read_env_file
    from mosaera_api.setup.steps import database_port, next_free_port

    free = next_free_port(5500)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test(size=(120, 42)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.step = "database"
            started: list[bool] = []

            async def _record() -> None:
                started.append(True)

            app._start_database = _record  # type: ignore[assignment,method-assign]
            await choices.submit_db_port(app, str(free))
            await pilot.pause()

            assert read_env_file(app.repo_root / ".env")["MOSAERA_DB_PORT"] == str(free)
            assert os.environ["MOSAERA_DB_PORT"] == str(free)
            assert database_port() == free, "the DSN half must move too"
            assert started, "and it must actually retry, not just record the number"
            assert not app._port_conflict, "the conflict is resolved; the row goes away"

    try:
        asyncio.run(_body())
    finally:
        os.environ.pop("MOSAERA_DB_PORT", None)


def test_the_port_repair_happens_inside_the_recommended_path(tmp_path: Path) -> None:
    """A port already taken is a step WITHIN choosing the bundled database, not a route away.

    The first cut added a third row to the database menu. That put "(recommended)" on the option
    which had just failed and made the actual repair read as a departure from it — reported as
    looking exactly that way. The recommended path now carries its own repair: the conflict sends
    the operator straight to the port prompt, and the menu keeps the two choices that are genuinely
    choices.

    The flag is consumed as it is used, so Esc from the prompt reaches the menu instead of bouncing
    the operator back onto the screen they just declined.
    """
    import asyncio
    import os
    import socket

    from mosaera_api.setup import enter_steps, screens
    from mosaera_api.setup.app import SetupApp

    held = socket.socket()
    held.bind(("127.0.0.1", 0))
    held.listen()
    taken = held.getsockname()[1]

    assert screens.database(object(), 5432).choices == [
        screens.USE_BUNDLED,
        screens.POINT_ELSEWHERE,
    ], "no third row: the recommended path repairs itself"

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test(size=(120, 42)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            os.environ["MOSAERA_DB_PORT"] = str(taken)
            app._port_conflict = True
            app.step = "database"
            await enter_steps.database(app)
            await pilot.pause()

            title = app.query_one("#title").render_line(0).text
            assert "different port" in title, f"went somewhere else: {title!r}"
            assert not app._options, "a prompt, not another menu to choose from"
            assert not app._port_conflict, "consumed, or Esc traps the operator in a loop"

    try:
        asyncio.run(_body())
    finally:
        held.close()
        os.environ.pop("MOSAERA_DB_PORT", None)


def test_the_same_refusal_routes_to_opposite_repairs(tmp_path: Path) -> None:
    """ "Postgres rejected the password" is two different problems wearing one sentence.

    If a server was already answering before setup touched anything, it is somebody else's and the
    fix is to move off its port. If we started the container ourselves and it STILL refuses us, the
    fix is on our side: the bundled volume predates these credentials.

    The second was the one reported, and it is the one nothing could clear by hand — the volume is
    a named Docker volume inside the Docker or Colima VM, not under `~/.mosaera`, so removing the
    install directory never touched it. Postgres applies POSTGRES_PASSWORD only when it initialises
    an EMPTY data directory, so an interrupted first attempt leaves a volume every later run reuses
    and every later run is rejected by.
    """
    import asyncio

    from mosaera_api.setup import enter_steps, screens
    from mosaera_api.setup.app import SetupApp
    from mosaera_api.setup.build_flow import _blame_credentials

    class _Flags:
        def __init__(self) -> None:
            self._port_conflict = False
            self._db_stale = False
            self._db_reason = ""

    adopted, ours = _Flags(), _Flags()
    _blame_credentials(adopted, adopted=True)  # type: ignore[arg-type]
    _blame_credentials(ours, adopted=False, reason="FATAL: password authentication failed")  # type: ignore[arg-type]
    assert (adopted._port_conflict, adopted._db_stale) == (True, False)
    assert (ours._port_conflict, ours._db_stale) == (False, True)
    # The raw refusal travels with it: the screen SHOWS what happened rather than naming a cause.
    assert "authentication failed" in ours._db_reason

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test(size=(120, 42)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            app._db_stale = True
            app.step = "database"
            await enter_steps.database(app)
            await pilot.pause()

            title = app.query_one("#title").render_line(0).text.lower()
            assert "refused these credentials" in title, title
            assert screens.RESET_BUNDLED in app._options
            assert not app._db_stale, "consumed, or Esc traps the operator on it"

    asyncio.run(_body())


def test_the_reset_clears_the_volume_and_is_scoped_to_this_install() -> None:
    """`down` alone keeps the data, which is the whole thing that has to go — and an unscoped
    teardown erases whichever database answers to the shared compose name."""
    from pathlib import Path as _Path

    from mosaera_api.setup.steps import compose_down_argv
    from mosaera_core.config import Settings

    argv = compose_down_argv(Settings.from_env(), _Path.cwd(), volumes=True)
    assert argv[-2:] == ["down", "--volumes"], "keeping the data defeats the repair"
    assert "--project-directory" in argv, "an unscoped teardown reaches other installs"
    assert "-p" in argv, "and the project must be pinned above any ambient COMPOSE_PROJECT_NAME"


def test_the_reset_proves_the_volume_is_gone_rather_than_assuming(tmp_path: Path) -> None:
    """A repair that reports success by not checking is worse than no repair.

    The first cut fired `down --volumes` and moved on without looking. When the teardown did not
    take, setup walked back into the same refusal and told the operator their data predated the
    install a SECOND time — having just told them it was being removed. Reported exactly that way.
    """
    from unittest.mock import patch

    from mosaera_api.setup import _uninstall_probe, steps
    from mosaera_core.config import Settings

    settings = Settings.from_env()
    calls: list[list[str]] = []

    def _fake_run(argv: list[str], **_kw: object) -> object:
        calls.append(argv)

        class _R:
            # `volume inspect` succeeding means the volume is STILL THERE.
            returncode = 0
            stdout = ""

        return _R()

    with (
        patch.object(_uninstall_probe, "data_volume", lambda *_a, **_k: "proj_mosaera-pgdata"),
        patch.object(steps.subprocess, "run", _fake_run),
    ):
        problem = steps.reset_bundled_volume(settings, tmp_path)

    assert problem, "a volume that survived must be reported, not passed over"
    assert "proj_mosaera-pgdata" in problem, "name it, so the operator can act on it"
    assert any("volume" in a and "rm" in a for a in calls), "removing it by name is the second try"

    # And when it really is gone, the repair says nothing and setup continues.
    def _gone(argv: list[str], **_kw: object) -> object:
        class _R:
            returncode = 1 if "inspect" in argv else 0
            stdout = ""

        return _R()

    with (
        patch.object(_uninstall_probe, "data_volume", lambda *_a, **_k: "proj_mosaera-pgdata"),
        patch.object(steps.subprocess, "run", _gone),
    ):
        assert steps.reset_bundled_volume(settings, tmp_path) == ""


def test_the_refusal_screen_reports_evidence_and_names_no_cause() -> None:
    """It asserted a cause twice and was wrong twice.

    First "Postgres rejected the password", then "its data predates this install" — on a machine
    where every volume had just been deleted, so there was no such data. A credential refusal looks
    identical whatever is behind it, and the wizard cannot tell from the client side. Postgres CAN,
    in its startup log, so the screen shows that and offers both repairs rather than picking one.
    """
    from mosaera_api.setup import screens

    screen = screens.database_reset(
        5432,
        evidence="postgres-1  | Database directory appears to contain a database; Skipping init",
        raw='FATAL:  password authentication failed for user "mosaera"',
    )
    assert screens.RESET_BUNDLED in screen.choices
    assert screens.POINT_ELSEWHERE in screen.choices, "both repairs, since the cause is unproven"
    assert "Skipping init" in screen.table, "the evidence has to be on the screen"
    assert "password authentication failed" in screen.detail, "and so does the raw refusal"
    # It may DESCRIBE both possibilities; it must not declare one of them to be the case.
    assert "predates this install." not in screen.body


def test_a_healthy_container_the_host_cannot_reach_is_its_own_diagnosis() -> None:
    """The real failure, after three wrong ones.

    `compose up --wait` returns only once the healthcheck passes, so "container running" and
    "client cannot connect" together are PROVEN, not inferred — the port is published at an address
    this host does not share. On Colima and Lima a container published to 127.0.0.1 binds the VM's
    loopback, not the Mac's, and nothing on the host can reach it.

    Every earlier version walked on from that point and reported whatever came next — which is how
    a credential message came to be blamed for it three times, and how an operator was sent to
    delete data that was never involved.
    """
    from mosaera_api.setup import screens
    from mosaera_api.setup.build_flow import _is_auth_failure

    real = (
        "(psycopg.OperationalError) connection failed: connection to server at "
        '"127.0.0.1", port 5432 failed: Connection refused'
    )
    assert not _is_auth_failure(real), "a connection failure is not a credential failure"

    screen = screens.database_unreachable(5432, evidence="listening on 0.0.0.0", raw=real)
    assert screens.PUBLISH_FOR_HOST in screen.choices
    assert screens.POINT_ELSEWHERE in screen.choices
    assert screens.RESET_BUNDLED not in screen.choices, "the data is not the problem here"
    # The trade must be on screen: this widens exposure inside the VM.
    assert "other containers" in screen.body
    assert "data is untouched" in screen.body.replace("Your ", "").replace("data is", "data is")


def test_the_republish_keeps_the_data() -> None:
    """A changed publish needs the container recreated — but `--volumes` would take the database
    with it, and the database was never the problem on this path."""
    import inspect

    from mosaera_api.setup import choices

    source = inspect.getsource(choices._publish_for_host)
    assert "volumes=False" in source, "recreating the container must not erase it"
    assert "MOSAERA_DB_BIND_HOST" in source
    # Both halves, as everywhere else: `.env` for Compose, `os.environ` for this process.
    assert "_write_env" in source and "os.environ" in source


def test_the_wizard_waits_for_the_host_side_forward() -> None:
    """One probe was never enough, and this is the case that proved it.

    `compose up --wait` returns when the CONTAINER's healthcheck passes, and that healthcheck runs
    inside the VM. Colima and Lima establish the host-side port forward separately and afterwards,
    so there is a window where the container is genuinely healthy and the host genuinely cannot
    connect.

    From the machine that hit it: `docker compose ps` showed `0.0.0.0:5432->5432/tcp Up 5 minutes
    (healthy)` and `nc -vz 127.0.0.1 5432` succeeded — while the wizard, probing the instant
    Compose returned, had failed on both `::1` and `127.0.0.1` and declared the install broken.
    """
    from unittest.mock import patch

    from mosaera_api.setup import build_flow

    class _State:
        def __init__(self, reachable: bool) -> None:
            self.reachable = reachable
            self.reason = ""
            self.missing_database = False

    class _App:
        _cancel = False
        settings = None

        def call_from_thread(self, *_a: object, **_k: object) -> None: ...

        def _say(self, *_a: object, **_k: object) -> None: ...

    # Refused, refused, then the forward comes up — exactly the observed shape.
    answers = [_State(False), _State(False), _State(True)]
    with (
        patch.object(build_flow, "database_state", lambda *_a, **_k: answers.pop(0)),
        patch.object(build_flow, "dataclasses"),
        patch.object(build_flow.time, "sleep", lambda _s: None),
    ):
        state = build_flow._wait_reachable(_App(), "postgresql://x", grace=5.0)  # type: ignore[arg-type]
    assert state.reachable, "it must keep asking across the window, not fail on the first look"
    assert not answers, "and it must stop as soon as the port answers"

    # A port that never answers still fails, and within the grace rather than hanging.
    never = [_State(False)] * 500
    with (
        patch.object(build_flow, "database_state", lambda *_a, **_k: never[0]),
        patch.object(build_flow, "dataclasses"),
        patch.object(build_flow.time, "sleep", lambda _s: None),
    ):
        stubbed = build_flow._wait_reachable(_App(), "postgresql://x", grace=0.01)  # type: ignore[arg-type]
        assert not stubbed.reachable


def test_a_server_that_refuses_us_is_not_an_unreachable_one() -> None:
    """The misreading that cost four fixes.

    `database_state` reports `reachable=False` for EVERY failure, including one where the server
    answered and rejected the credentials. The unreachable branch sat above the auth branch, so an
    auth refusal was reported as "running, but not reachable from here" — and psycopg's own wording
    made that plausible, because it prefixes the message with "connection failed:" and only says
    `FATAL: password authentication failed` after the host and port.

    The real message, from the machine that hit it:

        connection failed: connection to server at "127.0.0.1", port 5432 failed:
        FATAL:  password authentication failed for user "mosaera"

    TCP was fine the whole time — `nc` succeeded on both stacks. The screen truncated the line
    exactly where it stops looking like authentication and starts looking like networking.
    """
    from mosaera_api.setup.build_flow import _is_auth_failure

    real = (
        'connection failed: connection to server at "127.0.0.1", port 5432 failed: '
        'FATAL:  password authentication failed for user "mosaera"'
    )
    assert _is_auth_failure(real), "the prefix is psycopg's; the cause is after the colon"

    # A genuine connect failure must NOT be read as credentials — that is the opposite mistake.
    refused = (
        'connection failed: connection to server at "127.0.0.1", port 5432 failed: '
        "Connection refused\n\tIs the server running on that host and accepting connections?"
    )
    assert not _is_auth_failure(refused)


def test_an_answering_server_does_not_spend_the_grace_window() -> None:
    """A refusal is an answer. Polling for a port forward that is demonstrably carrying traffic
    only makes the operator watch a spinner before reading the wrong diagnosis."""
    from unittest.mock import patch

    from mosaera_api.setup import build_flow

    class _State:
        reachable = False
        reason = 'FATAL:  password authentication failed for user "mosaera"'
        missing_database = False

    class _App:
        _cancel = False
        settings = None

        def call_from_thread(self, *_a: object, **_k: object) -> None: ...

        def _say(self, *_a: object, **_k: object) -> None: ...

    probes = 0

    def _probe(*_a: object, **_k: object) -> _State:
        nonlocal probes
        probes += 1
        return _State()

    with (
        patch.object(build_flow, "database_state", _probe),
        patch.object(build_flow, "dataclasses"),
        patch.object(build_flow.time, "sleep", lambda _s: None),
    ):
        build_flow._wait_reachable(_App(), "postgresql://x", grace=30.0)  # type: ignore[arg-type]
    assert probes == 1, f"an auth refusal must end the wait at once, took {probes} probes"


class _StubApp:
    """Enough of `SetupApp` for `bundled_database`, and nothing more.

    A real one needs a running event loop for `call_from_thread`; what is under test here is which
    branch the routing takes, which is decided before any of that matters.
    """

    def __init__(self, tmp_path: Path) -> None:
        from mosaera_core.config import Settings
        from mosaera_core.prereqs import detect_platform

        self.settings = Settings.from_env(env={"MOSAERA_DOCKER_BIN": "docker-not-here"})
        self.repo_root = tmp_path
        self.platform = detect_platform()
        self._cancel = False
        self._port_conflict = False
        self._db_stale = False
        self._db_unreachable = False
        self._db_reset = False
        self._db_reason = ""
        self.notes: list[str] = []

    def call_from_thread(self, fn: object, *a: object, **k: object) -> None:
        if callable(fn):
            fn(*a, **k)

    def _rows(self, *_a: object, **_k: object) -> None: ...

    def _say(self, *_a: object, **_k: object) -> None: ...

    def _note(self, line: str, **_k: object) -> None:
        self.notes.append(line)

    def _finish_action(self, *_a: object, **_k: object) -> None: ...


def _fresh_app(tmp_path: Path) -> _StubApp:
    return _StubApp(tmp_path)


def test_a_foreign_server_that_enforces_auth_is_still_a_foreign_server(tmp_path: Path) -> None:
    """THE root cause, and the reason five diagnoses missed it.

    "Is this port held by somebody else" was decided from a FULLY SUCCESSFUL connection. But a
    server answers by accepting a connection OR by refusing our credentials — both mean something
    already holds the port. So a foreign Postgres that enforces auth (an embedded-postgres from
    another project on 5432) failed that test in exactly the way our own stale volume does, and was
    routed to "reset your database" instead of "pick another port".

    That misrouting is what made a freshly-initialised container still report a rejected password:
    the bundled Postgres was healthy and simply never in the path, because the foreign server owned
    the host port.
    """
    from unittest.mock import patch

    from mosaera_api.setup import build_flow

    refused = type(
        "S",
        (),
        {
            "reachable": False,
            "reason": 'FATAL:  password authentication failed for user "mosaera"',
            "missing_database": False,
        },
    )()

    app = _fresh_app(tmp_path)
    started: list[str] = []

    def _record_up(*_a: object, **_k: object) -> int:
        started.append("up")
        return 0

    with (
        patch.object(build_flow, "database_state", lambda *_a, **_k: refused),
        patch.object(build_flow, "published_ports", lambda *_a, **_k: ""),  # nothing of OURS is up
        patch.object(build_flow, "ensure_compose_project", lambda *_a, **_k: "p"),
        patch.object(build_flow, "run_streaming", _record_up),
        patch.object(build_flow, "record_install", lambda *_a, **_k: None),
    ):
        build_flow.bundled_database(app)  # type: ignore[arg-type]

    assert app._port_conflict, "a refusal from a server we did not start is a PORT conflict"
    assert not app._db_stale, "and emphatically not our own data"
    assert not started, "and we must not start ours on top of a port somebody else holds"


def test_our_own_container_refusing_us_is_still_the_stale_volume_case(tmp_path: Path) -> None:
    """The regression the fix must not cause.

    Identical symptom, opposite cause: when OUR compose project already has a container up, a
    credential refusal is our own data directory refusing the password it was never given.
    """
    from unittest.mock import patch

    from mosaera_api.setup import build_flow

    refused = type(
        "S",
        (),
        {
            "reachable": False,
            "reason": 'FATAL:  password authentication failed for user "mosaera"',
            "missing_database": False,
        },
    )()

    app = _fresh_app(tmp_path)
    with (
        patch.object(build_flow, "database_state", lambda *_a, **_k: refused),
        patch.object(build_flow, "_wait_reachable", lambda *_a, **_k: refused),
        # OURS is up — so the refusal is ours to answer for.
        patch.object(build_flow, "published_ports", lambda *_a, **_k: "core-x-postgres-1  5432"),
        patch.object(build_flow, "ensure_compose_project", lambda *_a, **_k: "p"),
        patch.object(build_flow, "run_streaming", lambda *_a, **_k: 0),
        patch.object(build_flow, "record_install", lambda *_a, **_k: None),
    ):
        build_flow.bundled_database(app)  # type: ignore[arg-type]

    assert app._db_stale, "our own container refusing us is the volume case"
    assert not app._port_conflict
