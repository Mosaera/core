"""The wizard's flow rules, each test pinning a defect a real run produced.

None of these assert a happy path. Every one of them is a thing the wizard did wrong on the
operator's machine, written down so it cannot come back.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
from pathlib import Path
from typing import Any

import pytest
from mosaera_api.setup import build_flow, launch, resume, screens
from mosaera_api.setup.app import SetupApp
from mosaera_api.setup.steps import DatabaseState, Image
from mosaera_core.prereqs import PREREQS, Found, Platform, plan_for


def _found(key: str) -> Found:
    prereq = next(p for p in PREREQS if p.key == key)
    return Found(prereq, True, "installed", plan_for(prereq, Platform("linux", "fedora", "Fedora")))


def _not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the welcome step walking. Otherwise these tests land on the configured screen, which is
    a different thing than the one each of them is about."""
    monkeypatch.setattr("mosaera_api.setup.enter_steps.configured", lambda _app: None)


async def _settled(app: SetupApp, pilot: Any) -> None:
    """Let the readiness probe finish.

    It runs on a worker now — it is up to forty seconds of `docker` calls and a database connect,
    and inline on the first frame it froze the whole application. Tests that press keys have to wait
    for it, because `_busy` swallows keys while it runs.
    """
    await app.workers.wait_for_complete()
    await pilot.pause()


@pytest.fixture
def provisioned(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prerequisites present, images built — so the only step with anything to show is the one
    under test. This is the shape that exposed the backwards-bounce."""
    monkeypatch.setattr(
        "mosaera_api.setup.enter_steps.survey",
        lambda _bin, _plat: [_found(n) for n in ("git", "docker", "compose", "node")],
    )
    monkeypatch.setattr(
        "mosaera_api.setup.enter_steps.survey_images",
        lambda _s: [Image("mosaera-sandbox:dev", "f", present=True)],
    )
    _not_configured(monkeypatch)


def _unreachable(monkeypatch: pytest.MonkeyPatch, *, missing_db: bool = False) -> None:
    monkeypatch.setattr(
        "mosaera_api.setup.enter_steps.database_state",
        lambda _s: DatabaseState(False, missing_db, True, "connection refused", "mosaera"),
    )
    _not_configured(monkeypatch)


@pytest.mark.usefixtures("provisioned")
def test_escape_from_the_database_step_does_not_land_back_on_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bounce. `_back` stepped to `images`, `images` had nothing to build and auto-ADVANCED, and
    the operator arrived back where they pressed Esc. Backwards movement was dead through the whole
    middle of the flow because auto-skip only knew one direction."""
    _unreachable(monkeypatch)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            assert app.step == "database"
            await pilot.press("escape")
            await pilot.pause()
            assert app.step != "database"

    asyncio.run(_body())


@pytest.mark.parametrize(
    ("missing_db", "declared"),
    [(True, True), (False, True), (False, False)],
)
def test_the_database_step_never_offers_a_way_past_it(*, missing_db: bool, declared: bool) -> None:
    """ "Skip — I'll sort the database out myself" produced an instance with no account and no
    login. Whatever is wrong, the offers must all lead to a database."""
    state = DatabaseState(False, missing_db, declared, "connection refused", "mosaera")
    offers = screens.database(state, 5432).choices
    assert offers, "a cause with no offers is the dead end this replaced"
    assert not any(o.lower().startswith("skip") for o in offers)
    assert screens.POINT_ELSEWHERE in offers


def test_there_is_no_account_screen_without_a_database() -> None:
    """The dead end one screen later: `admin_no_database` offered "Continue without an account"."""
    assert not hasattr(screens, "admin_no_database")
    rendered = " ".join(
        str(getattr(screens, name)) for name in dir(screens) if not name.startswith("_")
    )
    assert "Continue without an account" not in rendered


def test_a_database_url_is_tested_before_it_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Order is the whole point. Writing first would leave `.env` pointing at a database that does
    not answer, and the next run would start from that broken value with no memory of what it
    replaced."""
    from mosaera_api.setup import choices

    _not_configured(monkeypatch)
    monkeypatch.setattr(
        "mosaera_api.setup.choices.MemoryStore.open_or_reason",
        classmethod(lambda _c, _u: (None, 'database "nope" does not exist')),
    )

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test():
            await choices.submit_db_url(app, "postgresql://u:p@localhost:5432/nope")
            assert app.step != "access"  # not advanced
            assert app._field_for == "db_url"  # re-asked
            assert not (tmp_path / ".env").exists()  # and nothing was persisted

    asyncio.run(_body())


def test_a_url_that_is_not_postgres_is_refused_without_a_connection_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaera_api.setup import choices

    # Otherwise the welcome step's readiness probe opens the store first and lands in `tried`.
    _not_configured(monkeypatch)
    tried: list[str] = []

    def _record(_cls: object, url: str) -> tuple[None, str]:
        tried.append(url)
        return None, "x"

    monkeypatch.setattr(
        "mosaera_api.setup.choices.MemoryStore.open_or_reason", classmethod(_record)
    )

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test():
            await choices.submit_db_url(app, "mysql://u:p@localhost/mosaera")
            assert tried == []

    asyncio.run(_body())


def test_a_breadcrumb_changes_the_words_and_nothing_else(tmp_path: Path) -> None:
    """Resume is DERIVED. The breadcrumb produces a sentence; the position still comes from probing
    the machine, because "you were at images" is a lie the moment someone removes Docker."""
    resume.record(tmp_path, "database")
    said = screens.welcome(resume.sentence(resume.read(tmp_path))).body
    assert "Picking up where you left off" in said
    assert screens.welcome().choices == screens.welcome("anything").choices
    resume.clear(tmp_path)
    assert resume.sentence(resume.read(tmp_path)) == ""


def test_an_unrecognised_breadcrumb_says_nothing(tmp_path: Path) -> None:
    # A stale or hand-edited file must degrade to a first run, never to a wrong claim.
    from mosaera_core.settings_store import write_settings

    write_settings(tmp_path, {"setup_progress": {"step": "teleport"}})
    assert resume.sentence(resume.read(tmp_path)) == ""


@pytest.mark.usefixtures("provisioned")
def test_ctrl_x_reaches_the_picker_from_mid_flow_and_returns_where_it_came_from(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chord exists so an operator who changes their mind at step two is not made to finish a
    setup they do not want in order to be allowed to undo it.

    It arrives EMPTY, like every other door into this screen — it used to pre-tick the reversible
    rows here and nowhere else. And Esc returns to the step it was pressed on, not to a screen
    claiming the install succeeded.
    """
    _unreachable(monkeypatch)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            assert app.step == "database"
            await pilot.press("ctrl+x")
            await pilot.pause()
            # One screen now: Ctrl-X lands on the confirmation itself. The picker it used to open
            # is gone — assembling the removal was the operator's job, and the default assembly
            # left the volume and the server behind.
            assert app.step == "uninstall_confirm"
            # The unticked rule is DELIBERATELY REVERSED here (ADR-0119 amendment, 2026-09-01).
            # It protected against a checklist being confirmed without reading each row — but the
            # checklist is gone, and its own default was the unsafe one: unticked rows meant the
            # obvious path left the database volume and the running server behind while reporting
            # a clean removal. What replaces it is asserted below: one question, cursor on Cancel,
            # consequences shown, and nothing SHARED in the selection.
            from mosaera_api.setup.uninstall_flow import _SHARED

            assert app._chosen, "the one question arrives answerable, not half-assembled"
            assert not {app._removable[i].key for i in app._chosen} & _SHARED
            assert app._options[0] == "Cancel"
            assert app._selected == 0, "the cursor rests on the option that changes nothing"
            assert app._removable, "there was nothing to offer at all"
            await pilot.press("escape")
            await pilot.pause()
            assert app.step == "database"

    asyncio.run(_body())


def test_a_server_that_is_already_up_is_never_started_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The idempotence rule the whole wizard keeps. A second `mosaera-api` on a taken port either
    dies on bind or, worse, quietly answers somewhere else."""
    from mosaera_api.setup import done_flow

    started: list[Any] = []
    monkeypatch.setattr(launch, "already_serving", lambda *_a, **_k: True)
    monkeypatch.setattr(launch, "our_pid", lambda *_a, **_k: 4242)  # it is OURS
    monkeypatch.setattr(launch, "responds_ok", lambda *_a, **_k: True)

    def _spawn(*args: Any, **_kw: Any) -> tuple[int, Path]:
        started.append(args)
        return 1, tmp_path

    monkeypatch.setattr(launch, "start_detached", _spawn)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "done"
            await done_flow.enter(app)
            await pilot.pause()
            assert started == []
            assert app._serving is True

    asyncio.run(_body())


def test_a_taken_port_stops_a_second_server_without_claiming_the_first_one_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two questions this branch used to answer with one probe.

    "Is the port taken" decides whether to start a second server, and the answer must stay yes —
    idempotence is the rule the whole wizard keeps. "Does it work" is what we then TELL the
    operator, and it is a different fact: the screen advertised a live address over an instance
    that returned 500 to every request (live macOS run, 2026-08-30).
    """
    from mosaera_api.setup import done_flow

    started: list[Any] = []
    monkeypatch.setattr(launch, "already_serving", lambda *_a, **_k: True)
    monkeypatch.setattr(launch, "our_pid", lambda *_a, **_k: 4242)  # it is OURS
    monkeypatch.setattr(launch, "responds_ok", lambda *_a, **_k: False)

    def _spawn(*args: Any, **_kw: Any) -> tuple[int, Path]:
        started.append(args)
        return 1, tmp_path

    monkeypatch.setattr(launch, "start_detached", _spawn)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "done"
            await done_flow.enter(app)
            await pilot.pause()
            assert started == [], "a taken port must still stop a second server"
            assert app._serving is False, "an open port that 500s is not a working instance"

    asyncio.run(_body())


def test_the_countdown_is_cancelled_on_leaving_the_finished_screen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timer that closes the application is fine on the finished screen and catastrophic one
    screen into an uninstall. Asserted on the timer itself, not on the absence of an exit."""
    from mosaera_api.setup import done_flow

    monkeypatch.setattr(launch, "already_serving", lambda *_a, **_k: True)
    monkeypatch.setattr(launch, "our_pid", lambda *_a, **_k: 4242)  # it is OURS

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "done"
            await done_flow.enter(app)
            await pilot.pause()
            assert app._countdown is not None
            await app._goto("uninstall")
            await pilot.pause()
            assert app._countdown is None

    asyncio.run(_body())


def test_the_finished_screen_shows_no_link_when_nothing_came_up() -> None:
    """A link that refuses is worse than being told where the log is, and this is the last thing
    the operator reads."""
    up = screens.done("http://127.0.0.1:8000", "ana", serving=True, log="/l", seconds=60)
    down = screens.done("http://127.0.0.1:8000", "ana", serving=False, log="/l", seconds=60)
    assert "http://127.0.0.1:8000" in up.body
    assert "http://127.0.0.1:8000" not in down.body
    assert "/l" in down.body
    assert "60s" in up.hint


def test_the_ribbon_does_not_repeat_the_heading() -> None:
    from mosaera_api.setup.ui import step_ribbon

    ribbon = step_ribbon(5, 2)
    assert "Database" not in ribbon
    assert ribbon.count("▰") == 3 and ribbon.count("▱") == 2


def test_a_public_bind_is_shown_as_an_address_you_can_reach() -> None:
    # `http://0.0.0.0:8000` is not something an operator can click.
    all_interfaces = "0.0.0.0"  # noqa: S104 — the bind under test, not one being made
    assert launch.address(all_interfaces, 8000, "192.168.1.5") == "http://192.168.1.5:8000"
    assert launch.address("127.0.0.1", 8000, "192.168.1.5") == "http://127.0.0.1:8000"


def test_only_a_server_we_started_is_offered_for_removal(tmp_path: Path) -> None:
    from unittest.mock import patch

    from mosaera_api.setup.uninstall import plan
    from mosaera_core.config import Settings

    settings = Settings.from_env()
    assert "server" not in {r.key for r in plan(settings, tmp_path)}
    # A pid file alone no longer qualifies: the process must actually BE this install's server.
    # Writing our own pid here used to make the row appear, which is exactly the breach that let a
    # stale `api.pid` get an unrelated process SIGTERMed.
    (tmp_path / launch.PID_NAME).write_text(str(os.getpid()), encoding="utf-8")
    assert "server" not in {r.key for r in plan(settings, tmp_path)}

    with patch("mosaera_api.setup.launch.our_pid", return_value=4242):
        assert "server" in {r.key for r in plan(settings, tmp_path)}


def test_a_process_we_may_not_signal_is_not_treated_as_ours(tmp_path: Path) -> None:
    """pid 1 exists on every Linux box and is emphatically not this wizard's server. A recorded pid
    can be reused by anything after a reboot, so "cannot signal it" must read as "not ours" rather
    than as "alive" — the offer is to stop OUR server, not whatever now holds that number."""
    (tmp_path / launch.PID_NAME).write_text("1", encoding="utf-8")
    assert launch.our_pid(tmp_path) == 0


def test_the_resume_line_is_said_once_per_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stepping back to welcome is not "picking up where you left off" — you left off nowhere, you
    pressed Esc a moment ago. The acknowledgement belongs to the first paint of the session."""
    _not_configured(monkeypatch)
    resume.record(tmp_path, "database")

    async def _body() -> None:
        app = SetupApp(tmp_path)
        app.settings = dataclasses.replace(app.settings, home=tmp_path)
        async with app.run_test() as pilot:
            # The first paint is `on_mount`'s, which is the one that may greet.
            first = str(app.query_one("#body").render())
            assert "Picking up where you left off" in first
            await app._enter("welcome")  # reached again, e.g. by pressing Esc
            await pilot.pause()
            assert "Picking up where you left off" not in str(app.query_one("#body").render())

    asyncio.run(_body())


def test_a_resumed_welcome_does_not_recite_the_introduction() -> None:
    fresh = screens.welcome().body
    again = screens.welcome("Picking up where you left off — the last run stopped at X.").body
    assert "Configures the machine" in fresh
    assert "Configures the machine" not in again


def test_a_failure_toast_is_red_and_clears_itself(tmp_path: Path) -> None:
    """A success and a failure used to be the same colour and both stayed up for the session, so a
    message about a step fixed three screens ago was still there implying it had not been."""

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app._note("Could not start Postgres", error=True)
            await pilot.pause()
            notice = app.query_one("#notice")
            assert notice.has_class("error")
            assert app._toast is not None
            app._expire_toast()
            await pilot.pause()
            assert str(notice.render()).strip() == ""

            app._note("Database created")
            await pilot.pause()
            assert not app.query_one("#notice").has_class("error")
            # And leaving the step must not leave a timer that fires into the next one.
            app.clear_toast()
            assert app._toast is None

    asyncio.run(_body())


def test_no_screen_speaks_conversationally() -> None:
    """The voice rule, enforced rather than remembered: state what the thing is or what to do."""
    import inspect

    banned = ("I'll", "you like", "a moment ago", "You chose", "we will", "let's")
    for name, fn in vars(screens).items():
        if name.startswith("_") or not inspect.isfunction(fn):
            continue
        source = inspect.getsource(fn)
        for phrase in banned:
            assert phrase not in source, f"screens.{name} says {phrase!r}"


# --- the audit's findings, pinned -----------------------------------------------------------------


def test_repairing_a_step_moves_forward_however_you_arrived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_going_back` survived a repair, so installing the last missing prerequisite congratulated
    the operator by returning them to the welcome screen."""

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test():
            app._going_back = True
            app.step = "machine"
            app._finish_action("machine")
            assert app._going_back is False
            app._going_back = True
            await app._goto("database")
            assert app._going_back is False

    asyncio.run(_body())


def test_a_worker_that_raises_neither_kills_the_app_nor_strands_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`@work(thread=True)` defaults to `exit_on_error=True`. An unexpected exception used to tear
    the application down mid-install, and on that path `_busy` stayed True forever: every key
    swallowed, Esc setting a flag nobody polled."""
    _not_configured(monkeypatch)

    def _boom(_app: Any) -> list[str]:
        raise RuntimeError("disk full")

    # Driven through the STARTUP worker, which is where the image build lives now.
    monkeypatch.setattr("mosaera_api.setup.build_flow.build_missing_images", _boom)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "done"
            app._begin("Starting Mosaera", "…")
            app._launch_worker()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app._busy is False, "a dead worker must not strand the keyboard"
            assert "disk full" in app._notice
            assert app.is_running, "and it must not take the application with it"

    asyncio.run(_body())


def test_a_success_message_survives_the_step_it_belongs_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every success toast was written and wiped in the same tick, because `_advance` and `_goto`
    blanked `_notice` before the repaint.

    The service-token line — the only thing that says whether a NEW credential was minted — no
    longer takes that route at all: it is recorded on the app and rendered on the finished screen,
    because a message decided on one step and needed on another is not a toast. What is asserted
    here is that neither transition ERASES a toast that belongs to the step still being shown.

    Asserted on the transition itself rather than on whichever step comes next, so the test does not
    depend on a reachable database.
    """
    _not_configured(monkeypatch)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            await _settled(app, pilot)
            # The access step records its outcome where the finished screen will read it...
            app.step = "access"
            monkeypatch.setattr(SetupApp, "_advance", _noop)
            await app._set_access(public=True)
            await pilot.pause()
            assert "service token" in app._access_note

            # ...and neither transition ERASES a toast belonging to the step on screen. Isolated
            # from what the next step might say by
            # stubbing the entry: the claim is about `_advance`/`_goto` themselves, which used to
            # assign `self._notice = ""` before the repaint.
            monkeypatch.undo()
            monkeypatch.setattr(SetupApp, "_enter", _noop_step)
            for move in (app._advance(), app._goto("machine")):
                app._notice = "a result worth reading"
                app.step = "access"
                await move
                assert app._notice == "a result worth reading"

    asyncio.run(_body())


async def _noop(_self: object) -> None:
    """Stands in for `_advance` so a transition does not run while the toast is being checked."""
    return


async def _noop_step(_self: object, _step: str) -> None:
    """Stands in for `_enter`, so a transition can be tested without whatever the next step says."""
    return


def test_the_uninstall_runner_is_given_the_repo_root(tmp_path: Path) -> None:
    """`_compose_argv` names the compose file RELATIVELY. Without a cwd every `docker compose down`
    failed with "no configuration file provided", so an uninstall run from anywhere but the checkout
    removed nothing and said "did not fully succeed"."""
    from unittest.mock import patch

    from mosaera_api.setup import uninstall_flow

    seen: list[Any] = []

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            await _settled(app, pilot)
            # The containers row is gated on a daemon answering and a project being up; neither is
            # true in a test. Force it — what is under test here is the RUNNER's cwd and timeout,
            # not whether the row is offered.
            with (
                patch("mosaera_api.setup.uninstall.docker_available", lambda *_a, **_k: True),
                patch("mosaera_api.setup.uninstall._compose_project_exists", lambda *_a: True),
            ):
                app._removable = uninstall_flow.plan(app.settings, tmp_path)
            app._chosen = {i for i, r in enumerate(app._removable) if r.key == "containers"}
            assert app._chosen, "the containers row must be present for this test to mean anything"

            def _record(_argv: Any, _on_line: Any, cwd: Any = None, **kw: Any) -> int:
                seen.append((cwd, kw.get("timeout")))
                return 0

            with patch("mosaera_api.setup.uninstall_flow.run_streaming", _record):
                await uninstall_flow.run(app)
                await app.workers.wait_for_complete()
                await pilot.pause()
            assert seen, "the removal ran no commands at all"
            assert all(cwd == app.repo_root for cwd, _t in seen)
            # And bounded: removal cannot be cancelled, so the timeout is the only thing between a
            # wedged daemon and an unusable terminal.
            assert all(t and t < 30 * 60 for _c, t in seen)

    asyncio.run(_body())


def test_the_data_row_does_not_promise_to_delete_a_database_it_cannot_reach() -> None:
    """`compose down --volumes` erases the BUNDLED volume. Pointed at an external Postgres it
    removes nothing, while the row claimed "every project, run and piece of history"."""
    import dataclasses as dc

    from mosaera_api.setup.uninstall import _data_row
    from mosaera_core.config import Settings

    # Asked of `_data_row`, which OWNS the wording, not of `plan`. Reaching it through `plan` also
    # required a live Docker daemon — the row is only offered when there is a volume to destroy —
    # so on a host without one this raised `StopIteration` while proving nothing about the text.
    # Whether the row is offered at all is a separate property, tested above.
    external = dc.replace(Settings.from_env(), db_url="postgresql://u:p@db.example.com:5432/m")
    assert "external" in _data_row(external, Path("/nonexistent")).detail

    bundled = dc.replace(Settings.from_env(), db_url="postgresql://u:p@localhost:5432/mosaera")
    assert "no undo" in _data_row(bundled, Path("/nonexistent")).detail


def test_a_quoted_env_value_is_a_value_not_a_quoted_string(tmp_path: Path) -> None:
    """`PORT="8000"` means 8000. Kept verbatim it crashed every `int(...)` in a step entry, and made
    `access_env` rewrite the key on every single run."""
    from mosaera_api.setup.env_file import read_env_file, write_env_file

    env = tmp_path / ".env"
    env.write_text("export MOSAERA_API_PORT=\"8000\"\nMOSAERA_API_HOST='127.0.0.1'\n")
    read = read_env_file(env)
    assert read["MOSAERA_API_PORT"] == "8000"
    assert int(read["MOSAERA_API_PORT"]) == 8000
    assert read["MOSAERA_API_HOST"] == "127.0.0.1"
    # And `export` survives a rewrite — dropping it silently broke a sourced `.env` on run two.
    write_env_file(env, {"MOSAERA_API_PORT": "9000"})
    assert "export MOSAERA_API_PORT=9000" in env.read_text()


def test_the_installer_records_docker_when_it_installed_compose() -> None:
    """Compose arrives via Docker's own script and uninstall never offers compose on its own — so
    recording the key we were ASKED for meant the wizard installed Docker and then held no record
    that it might remove it."""
    from mosaera_api.setup.installer import _record_key

    assert _record_key("compose") == "docker"
    assert _record_key("node") == "node"


def test_a_failed_dashboard_build_does_not_start_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A server with no dashboard serves a 404 at the address the finished screen prints, which is
    the exact outcome `dashboard_built` exists to prevent."""
    started: list[Any] = []
    monkeypatch.setattr(launch, "already_serving", lambda *_a, **_k: False)
    monkeypatch.setattr(launch, "dashboard_built", lambda _r: False)
    monkeypatch.setattr("mosaera_api.setup.done_flow.run_streaming", lambda *_a, **_k: 1)

    def _spawn(*args: Any, **_kw: Any) -> tuple[int, Path]:
        started.append(args)
        return 1, tmp_path

    monkeypatch.setattr(launch, "start_detached", _spawn)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "done"
            app._begin("Starting Mosaera", "…")
            app._launch_worker()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert started == []

    asyncio.run(_body())


def test_a_cancelled_startup_is_not_reported_as_a_timeout() -> None:
    down = screens.done("http://x", "a", serving=False, log="/l", seconds=9, cancelled=True)
    timed = screens.done("http://x", "a", serving=False, log="/l", seconds=9, cancelled=False)
    assert "cancelled" in down.body.lower()
    assert "timeout" in timed.body.lower()


def test_esc_during_an_uninterruptible_action_says_nothing_rather_than_lying(
    tmp_path: Path,
) -> None:
    """The removal's hint says it cannot be interrupted; Esc printed "Cancelling…" anyway."""

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app._begin("Removing", "…", hint="This cannot be interrupted")
            app._cancel_allowed = False
            await pilot.press("escape")
            await pilot.pause()
            assert app._cancel is False
            assert "Cancelling" not in app._status_line

    asyncio.run(_body())


def test_a_long_notice_is_one_line(tmp_path: Path) -> None:
    """The wall of psycopg internals from the operator's screenshot, fed straight to a toast."""
    raw = (
        "OperationalError: (psycopg.OperationalError) connection failed: connection to server at\n"
        '"127.0.0.1", port 5432 failed: FATAL:  database "wizard_demo" does not exist\n'
        "Multiple connection attempts failed. All failures were:\n- host: 'localhost'\n" * 3
    )

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app._note(raw, error=True)
            await pilot.pause()
            assert "\n" not in app._notice
            assert len(app._notice) <= 160

    asyncio.run(_body())


def test_a_bad_port_in_env_does_not_take_the_wizard_down() -> None:
    """Three call sites did `int(...)` on this, on the UI thread inside a step entry — so a
    hand-edited `MOSAERA_API_PORT=eight-thousand` raised out of a key handler and Textual tore the
    application down with a traceback."""
    from mosaera_api.setup.env_file import port_from

    assert port_from({"P": "eight-thousand"}, "P", 8000) == 8000
    assert port_from({"P": "0"}, "P", 8000) == 8000
    assert port_from({"P": "99999"}, "P", 8000) == 8000
    assert port_from({}, "P", 8000) == 8000
    assert port_from({"P": "9000"}, "P", 8000) == 9000


def test_settings_are_never_rewritten_from_a_degraded_read(tmp_path: Path) -> None:
    """`read_settings` degrades to `{}` on purpose. A WRITER merging into that and rewriting turned
    one unreadable read — a half-written file from a second wizard — into permanent loss of
    `setup_installed`, `providers`, `gitlab_token` and every role binding."""
    from mosaera_core.settings_store import read_settings, write_settings

    write_settings(tmp_path, {"setup_installed": ["docker"]})
    (tmp_path / "settings.json").write_text('{"setup_installed": ["dock')  # truncated
    assert read_settings(tmp_path) == {}  # readers still degrade
    with pytest.raises(OSError):
        write_settings(tmp_path, {"gitlab_url": "https://example.com"})
    # And the damaged file is left exactly as it was, for a human to look at.
    assert (tmp_path / "settings.json").read_text() == '{"setup_installed": ["dock'


def test_a_build_failure_leaves_a_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """It used to write the reason into a progress row and then repaint, which cleared the row — so
    a failed build showed the identical "4 of 4 still to build" screen with nothing said, and
    pressing Enter did the same nothing again."""
    from mosaera_api.setup.steps import Image

    monkeypatch.setattr(
        "mosaera_api.setup.build_flow.survey_images",
        lambda _s: [Image("mosaera-sandbox:dev", "f", present=False)],
    )

    def _fails(_argv: Any, on_line: Any, _cwd: Any = None, **_kw: Any) -> int:
        on_line("Cannot connect to the Docker daemon at unix:///var/run/docker.sock")
        return 1

    monkeypatch.setattr("mosaera_api.setup.build_flow.run_streaming", _fails)
    _not_configured(monkeypatch)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            await _settled(app, pilot)
            # No longer a step of its own — the build runs inside the startup step now, so this
            # calls the loop where it actually lives.
            app.step = "done"
            app._begin("Starting Mosaera", "…")
            failures = await asyncio.to_thread(build_flow.build_missing_images, app)
            await pilot.pause()
            assert failures, "a failed build must be reported to the caller, not swallowed"
            assert app._notice, "a failed build must not repaint into silence"
            # And the cause, not "exit 1" — the daemon line names it and `explain` knows it.
            assert "daemon" in app._notice.lower()

    asyncio.run(_body())


def test_a_server_answering_on_the_port_is_not_claimed_as_our_container() -> None:
    """A system Postgres on 5432 was reported as "already running", then migrated into and written
    to `.env` — the wizard reporting success for a database it never started. A successful connect
    says something holds the port; it says nothing about whose it is."""
    from mosaera_api.setup.build_flow import ANSWERING

    assert "running" not in ANSWERING
    assert "answering" in ANSWERING


@pytest.mark.parametrize("size", [(80, 24), (100, 30), (120, 42), (60, 18)])
def test_every_screen_keeps_its_controls_on_screen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, size: tuple[int, int]
) -> None:
    """The controls must be VISIBLE, at every terminal size the wizard agrees to run in.

    `#header` was a fixed 17 rows and `_fit_mark` looked only at width, so on an 80x24 terminal —
    still the default almost everywhere — the header took 17 of 24 rows, the docked hint took 2,
    and the choice list was off the bottom. Nothing is bound to scrolling, so the operator saw a
    wordmark and nothing they could act on. Measured against the viewport, not eyeballed.
    """
    _not_configured(monkeypatch)
    monkeypatch.setattr(
        "mosaera_api.setup.enter_steps.database_state",
        lambda _s: DatabaseState(
            False, False, True, "connection refused", "mosaera", "postgres://x"
        ),
    )

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test(size=size) as pilot:
            await _settled(app, pilot)
            for step in ("welcome", "database", "access"):
                app.step = step
                await app._enter(step)
                await pilot.pause()
                choices_widget = app.query_one("#choices")
                hint = app.query_one("#hint")
                if app._options:
                    bottom = choices_widget.region.y + choices_widget.region.height
                    assert choices_widget.region.y >= 0, f"{step} at {size}: choices above the top"
                    assert bottom <= size[1], (
                        f"{step} at {size}: choices past the bottom ({bottom})"
                    )
                assert hint.region.y + hint.region.height <= size[1], f"{step} at {size}: no hint"

    asyncio.run(_body())


def test_a_stopped_docker_is_offered_a_start_not_a_reinstall() -> None:
    """The wizard told operators to re-download the vendor script in order to start a service.

    `plan_for` returned the same three-step install whatever the reason, and `gap_label` hardcoded
    "Install" — so a Docker that was installed and merely stopped read
    "Install Docker  curl -fsSL https://get.docker.com | sudo sh".
    """
    from mosaera_api.setup.ui import gap_label
    from mosaera_core.prereqs import (
        ABSENT,
        DAEMON_DOWN,
        NO_PERMISSION,
        PREREQS,
        Found,
        Platform,
        plan_for,
    )

    linux = Platform("linux", "fedora", "Fedora")
    docker = next(p for p in PREREQS if p.key == "docker")

    stopped = plan_for(docker, linux, DAEMON_DOWN)
    assert stopped.steps[0].command == "sudo systemctl enable --now docker"
    assert "get.docker.com" not in gap_label(Found(docker, False, "stopped", stopped, DAEMON_DOWN))
    assert gap_label(Found(docker, False, "stopped", stopped, DAEMON_DOWN)).startswith("Start ")

    denied = plan_for(docker, linux, NO_PERMISSION)
    assert "usermod" in denied.steps[0].command
    assert "get.docker.com" not in denied.steps[0].command

    # And a genuinely absent Docker still gets the installer.
    assert "get.docker.com" in plan_for(docker, linux, ABSENT).steps[0].command


def test_the_environment_wins_over_dot_env(tmp_path: Path) -> None:
    """ADR-0005 is env > stored > default. The wizard read `.env` alone, so an exported
    MOSAERA_API_PORT was ignored: the access screen offered the default 8000 and the launcher then
    probed 8000, found whatever was already answering there, and called it ours."""
    from mosaera_api.setup import env_file
    from mosaera_api.setup.env_file import capture_real_env, effective_env, shadowed_by_env

    env = tmp_path / ".env"
    env.write_text("MOSAERA_API_PORT=8000\nMOSAERA_API_HOST=127.0.0.1\n")
    try:
        capture_real_env({"MOSAERA_API_PORT": "8123"})
        assert effective_env(env)["MOSAERA_API_PORT"] == "8123"
        assert effective_env(env)["MOSAERA_API_HOST"] == "127.0.0.1"
        # And the screen is told, because writing .env cannot change what the shell exports.
        assert shadowed_by_env(env, "MOSAERA_API_HOST", "MOSAERA_API_PORT") == ["MOSAERA_API_PORT"]

        # The snapshot is taken BEFORE `load_env` merges `.env` into `os.environ`. Compared against
        # the merged environment instead, this warned about variables nobody had exported — which is
        # exactly what a live run produced.
        capture_real_env({})
        assert shadowed_by_env(env, "MOSAERA_API_HOST", "MOSAERA_API_PORT") == []
        assert effective_env(env)["MOSAERA_API_PORT"] == "8000"
    finally:
        env_file._REAL_ENV = None


def test_images_are_only_offered_for_removal_when_this_wizard_built_them(tmp_path: Path) -> None:
    """Image TAGS are global to the daemon, not scoped to a project or a directory — so the row was
    offering to delete the images another checkout's running instance depends on, and Ctrl-X
    pre-ticked it."""
    from mosaera_api.setup.uninstall import plan, record_install
    from mosaera_core.config import Settings

    settings = Settings.from_env()
    assert "images" not in {r.key for r in plan(settings, tmp_path)}
    record_install(tmp_path, "images")
    assert "images" in {r.key for r in plan(settings, tmp_path)}


def test_the_ribbon_survives_a_short_terminal() -> None:
    """At two rows the header clipped the ribbon away entirely, so a short terminal lost its
    "where am I" indicator."""
    from mosaera_api.setup.ui import header_rows

    assert header_rows(24) >= 3  # one padding + the ribbon + its own padding
    assert header_rows(18) >= 3
    assert header_rows(42) == 17


def test_only_one_wizard_can_claim_an_empty_instance() -> None:
    """Two `mosaera-setup` runs racing each other BOTH passed "is it empty?" and both created an
    administrator on a first-run instance. Found by running two wizards side by side.

    `admin_exists` is a courtesy check for a better message; the control is `require_first`, which
    re-checks inside the creating transaction under an advisory lock.
    """
    from unittest.mock import MagicMock

    from mosaera_api.setup.admin import create_admin

    store = MagicMock()
    store.count_users.return_value = 0
    create_admin(store, "first", "a-good-password")
    # The guarantee is ASKED FOR, not assumed from the pre-check.
    assert store.create_user.call_args.kwargs["require_first"] is True

    loser = MagicMock()
    loser.count_users.return_value = 0
    loser.create_user.side_effect = ValueError("already_claimed")
    outcome = create_admin(loser, "second", "a-good-password")
    assert not outcome.ok
    assert "already has an account" in outcome.message


def test_an_instance_the_wizard_finished_is_recognised_on_the_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defect, stated exactly: `configured()` demanded MORE than the walk does.

    The walk offers "Skip — install these manually" and "Skip", so an operator can finish setup with
    prerequisites and images outstanding — and did. On the next run `configured()` refused to call
    that instance configured and walked them through from the top, not recognising the work the
    wizard itself had just printed "Mosaera is configured" about.
    """
    from mosaera_api.setup import enter_steps
    from mosaera_api.setup.steps import Image

    class _Store:
        def count_users(self) -> int:
            return 1

    # Every image absent and a prerequisite missing — the state "Skip" leaves behind.
    def _gap(key: str) -> Found:
        prereq = next(p for p in PREREQS if p.key == key)
        plat = Platform("linux", "fedora", "Fedora")
        return Found(prereq, False, "not installed", plan_for(prereq, plat))

    monkeypatch.setattr(
        "mosaera_api.setup.enter_steps.survey", lambda _bin, _plat: [_found("git"), _gap("docker")]
    )
    monkeypatch.setattr(
        "mosaera_api.setup.enter_steps.survey_images",
        lambda _s: [Image("mosaera-sandbox:dev", "f", present=False)],
    )
    monkeypatch.setattr(
        "mosaera_api.setup.enter_steps.MemoryStore.open_or_reason",
        classmethod(lambda _c, _u: (_Store(), "")),
    )

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            ready = enter_steps.configured(app)
            assert ready is not None, "a signed-into-able instance is configured"
            assert ready.accounts == 1
            # ...and what is still missing is NAMED rather than used to deny setup happened.
            assert any("sandbox image" in g for g in ready.gaps)
            assert any("Docker" in g for g in ready.gaps)

    asyncio.run(_body())


def test_the_configured_screen_names_what_is_outstanding() -> None:
    plain = screens.configured("http://x", 1, "/e", serving=True)
    gapped = screens.configured(
        "http://x", 1, "/e", serving=True, gaps=("Docker", "3 sandbox images to build")
    )
    assert "Still outstanding" not in plain.body
    assert "3 sandbox images to build" in gapped.body
    # Not "refused" — an all-Ollama, no-sandbox-image config STARTS a run and fails at the first
    # tool/model call rather than being turned away at the door (1C).
    assert "Runs cannot succeed" in gapped.body
    assert "refused" not in gapped.body


def test_an_instance_with_no_account_is_not_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pair that defines configured is the store AND an account. Neither alone."""
    from mosaera_api.setup import enter_steps

    class _Empty:
        def count_users(self) -> int:
            return 0

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            monkeypatch.setattr(
                "mosaera_api.setup.enter_steps.MemoryStore.open_or_reason",
                classmethod(lambda _c, _u: (_Empty(), "")),
            )
            assert enter_steps.configured(app) is None
            monkeypatch.setattr(
                "mosaera_api.setup.enter_steps.MemoryStore.open_or_reason",
                classmethod(lambda _c, _u: (None, "connection refused")),
            )
            assert enter_steps.configured(app) is None

    asyncio.run(_body())


def test_a_read_only_env_is_refused_rather_than_replaced(tmp_path: Path) -> None:
    """Replacing needs permission on the DIRECTORY, not the file — so a deliberately `chmod 0400`
    `.env` was silently overwritten and came back 0600. Found by doing that to a live one."""
    from mosaera_api.setup.env_file import read_env_file, write_env_file

    env = tmp_path / ".env"
    env.write_text("MOSAERA_API_PORT=8000\n")
    env.chmod(0o400)
    with pytest.raises(PermissionError, match="read-only"):
        write_env_file(env, {"MOSAERA_API_PORT": "9000"})
    assert read_env_file(env)["MOSAERA_API_PORT"] == "8000"  # untouched
    assert env.stat().st_mode & 0o777 == 0o400  # and unwidened


def test_an_existing_mode_is_never_widened(tmp_path: Path) -> None:
    """0600 is the default for a file that may hold a service token — but if the operator chose
    something stricter and still writable, the wizard must not grant itself more."""
    from mosaera_api.setup.env_file import write_env_file

    env = tmp_path / ".env"
    env.write_text("A=1\n")
    env.chmod(0o600)
    write_env_file(env, {"A": "2"})
    assert env.stat().st_mode & 0o777 == 0o600
    # A brand-new file still gets 0600 from creation.
    fresh = tmp_path / "sub" / ".env"
    write_env_file(fresh, {"A": "1"})
    assert fresh.stat().st_mode & 0o777 == 0o600


def test_the_installer_refuses_a_bare_mosaera_home() -> None:
    """`MOSAERA_HOME` is the application's DATA directory. `install.sh` used it as the clone target,
    so an operator pointing their data at /srv/mosaera got the repository cloned into it."""
    script = (Path(__file__).resolve().parents[3] / "scripts" / "install.sh").read_text()
    assert "MOSAERA_INSTALL_DIR" in script
    assert 'INSTALL_DIR="${MOSAERA_HOME' not in script
    # And it says so rather than guessing which of the two was meant.
    assert "is the data directory, not the install directory" in script


def test_the_configured_screen_never_offers_to_leave_running_a_stopped_instance() -> None:
    """Spotted on screen: the body said "(not currently running)" and the row beneath it said
    "Leave it running". The row was hardcoded for the case I had only imagined.

    It now reads "Stop Mosaera" when the instance is up. "Leave it running" was never an action —
    Ctrl-Q already does exactly that — so the most prominent row on the screen spent itself on what
    quitting does, while the operator who wanted the instance DOWN was offered only Uninstall."""
    up = screens.configured("http://x", 1, "/e", serving=True)
    down = screens.configured("http://x", 1, "/e", serving=False)
    assert up.choices[0] == "Stop Mosaera"
    assert "Ctrl-Q to leave it running" in up.hint, "quitting is what leaves it up"
    assert "not currently running" in down.body
    assert down.choices[0] == "Start Mosaera"
    # The other two rows are the same either way, and the destructive one stays last.
    assert (
        up.choices[1:]
        == down.choices[1:]
        == [
            "Re-run setup",
            "Reset a password",
            "Uninstall Mosaera",
        ]
    )


def test_the_first_row_starts_a_stopped_instance_and_stops_a_running_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaera_api.setup import choices

    _not_configured(monkeypatch)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            await _settled(app, pilot)
            app.step = "configured"

            # Stopped: the first row starts it, by the same path a first run finishes through.
            # Rows come from the SCREEN — dispatch reads their text, so a hand-made list would be
            # testing this test's idea of them.
            monkeypatch.setattr(launch, "already_serving", lambda *_a, **_k: False)
            monkeypatch.setattr("mosaera_api.setup.done_flow.enter", _record_started)
            _STARTED.clear()
            app._options = screens.configured("u", 1, "e", serving=False).choices
            await choices.dispatch(app, 0)
            await pilot.pause()
            assert _STARTED, "a stopped instance was not started"

            # Running: the first row STOPS it now, and starting is what it must not do.
            monkeypatch.setattr(launch, "already_serving", lambda *_a, **_k: True)
            monkeypatch.setattr(launch, "our_pid", lambda *_a, **_k: 4242)  # it is OURS
            monkeypatch.setattr(launch, "stop", lambda *_a, **_k: "")
            _STARTED.clear()
            app.step = "configured"
            app._options = screens.configured("u", 1, "e", serving=True).choices
            await choices.dispatch(app, 0)
            assert not _STARTED

    asyncio.run(_body())


_STARTED: list[object] = []


async def _record_started(app: object) -> None:
    _STARTED.append(app)


def test_a_reachable_database_is_recorded_so_the_started_server_uses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The end-to-end defect, found by opening the login page.

    The step skipped silently when the database was already up, so `.env` never learned which
    database the wizard had validated — and the server the finished screen starts inherits `.env`.
    The advertised address served an instance with NO store: `auth_required: false`, no accounts,
    and a login page that could not log anybody in, while the database sat right there holding the
    admin account the wizard had just created.
    """
    from mosaera_api.setup import enter_steps
    from mosaera_api.setup.env_file import read_env_file
    from mosaera_api.setup.steps import DatabaseState

    _not_configured(monkeypatch)
    monkeypatch.setattr(
        "mosaera_api.setup.enter_steps.database_state",
        lambda _s: DatabaseState(True, False, False, "", "mosaera", "postgres://x"),
    )

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            await _settled(app, pilot)
            (tmp_path / ".env").write_text("MOSAERA_API_PORT=8000\n")
            app.step = "database"
            await enter_steps.database(app)
            await pilot.pause()
            recorded = read_env_file(tmp_path / ".env").get("MOSAERA_DB_URL", "")
            assert recorded, "the server would start with no database at all"
            assert recorded.startswith("postgresql://")

    asyncio.run(_body())


def test_an_operators_own_database_url_is_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaera_api.setup import enter_steps
    from mosaera_api.setup.env_file import read_env_file

    _not_configured(monkeypatch)
    mine = "postgresql://me:secret@db.example.com:5432/mine"

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test():
            (tmp_path / ".env").write_text(f"MOSAERA_DB_URL={mine}\n")
            enter_steps.remember_database(app)
            assert read_env_file(tmp_path / ".env")["MOSAERA_DB_URL"] == mine

    asyncio.run(_body())


def test_the_service_token_outcome_reaches_the_finished_screen() -> None:
    """The one message that must outlive its own step. Decided on access, needed on the screen that
    tells the operator how to reach the instance — a toast showed it for the instant before
    `_advance`, and before toasts cleared on a step change it rode into the administrator step and
    read as an instruction for it."""
    out = screens.done(
        "http://192.168.11.69:8000",
        "ana",
        serving=True,
        log="/l",
        seconds=60,
        access="Reachable on your network — a service token was generated.",
    )
    assert "a service token was generated" in out.body
    # And it is absent when nothing was decided, rather than leaving a blank line behind.
    assert "\n\n\n" not in screens.done("http://x", "a", serving=True, log="/l", seconds=60).body


def test_uninstall_offers_only_what_actually_happened(tmp_path: Path) -> None:
    """The screen says "Only what this wizard installed is listed". The list must agree.

    A run that reached the prerequisites screen and stopped — no Docker, so nothing could be
    started — was still offered "Stop the database container", "Remove configuration" and "Delete
    all project data". Three rows appended unconditionally, directly beneath a header claiming the
    opposite, offering to undo things that had never been done.
    """
    from mosaera_api.setup.uninstall import plan
    from mosaera_core.config import Settings

    home = tmp_path / ".mosaera"
    home.mkdir()
    settings = Settings.from_env(env={"MOSAERA_DOCKER_BIN": "docker-not-here"})
    # "Remove Mosaera itself" is always offered — it always exists, we are running from it
    # (ADR-0119). What must be absent is everything CONDITIONAL on work that never happened.
    conditional = [r.key for r in plan(settings, home, tmp_path) if r.key != "install"]
    assert conditional == [], "nothing happened, so nothing else is offered"


def test_uninstall_offers_config_only_when_the_wizard_wrote_some(tmp_path: Path) -> None:
    """The KEYS, not the file. `settings.json` is mostly the dashboard's — provider keys, model
    bindings, every knob the Settings page manages — so its existence says nothing about whether
    this wizard has anything to take back."""
    import json

    from mosaera_api.setup.uninstall import plan
    from mosaera_core.config import Settings

    home = tmp_path / ".mosaera"
    home.mkdir()
    settings = Settings.from_env(env={"MOSAERA_DOCKER_BIN": "docker-not-here"})

    def _conditional() -> list[str]:
        return [r.key for r in plan(settings, home, tmp_path) if r.key != "install"]

    (home / "settings.json").write_text(json.dumps({"model_pm": "x", "openai_api_key": "y"}))
    assert _conditional() == [], "someone else's file is not ours to offer"

    (home / "settings.json").write_text(json.dumps({"setup_progress": {"machine": True}}))
    assert _conditional() == ["config"]


def test_choosing_to_remove_mosaera_records_the_intent_for_the_launcher(tmp_path: Path) -> None:
    """The removal cannot happen inside this process, so the app records it and `__main__` execs.

    Recorded BEFORE `perform` runs: an operator who asked to remove the installation gets it even
    if an earlier item fails, because a half-removed install that still leaves the tree behind is
    the worst outcome available.
    """
    import asyncio

    from mosaera_api.setup import uninstall_flow
    from mosaera_api.setup.app import SetupApp

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app._remove_install is None
            app._removable = uninstall_flow.plan(app.settings, app.settings.home, tmp_path)
            app._chosen = {i for i, r in enumerate(app._removable) if r.key == "install"}
            assert app._chosen, "the install row must be offered"
            await uninstall_flow.run(app)
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app._remove_install == app.repo_root

    asyncio.run(_body())


def test_the_hand_off_removes_the_tree_and_tidies_an_empty_parent(tmp_path: Path) -> None:
    """`exec` out, then delete — a process must not be the last user of what it removes.

    Run in a child because `_hand_off_removal` replaces the process image and never returns, which
    is exactly the property under test.
    """
    import subprocess
    import sys

    target = tmp_path / "parent" / "core"
    (target / ".venv" / "lib").mkdir(parents=True)
    (target / ".venv" / "lib" / "mod.py").write_text("x", encoding="utf-8")

    done = subprocess.run(  # noqa: S603 — argv is this test's own literal, not operator input
        [
            sys.executable,
            "-c",
            "from pathlib import Path\n"
            "from mosaera_api.setup.__main__ import _hand_off_removal\n"
            f"_hand_off_removal(Path({str(target)!r}))",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert not target.exists(), "the installation is gone"
    assert not target.parent.exists(), "and an empty ~/.mosaera is not left behind"
    assert "removed" in done.stdout.lower()


def test_the_hand_off_gives_the_terminal_back(tmp_path: Path) -> None:
    """`os.execv` runs NO atexit handler and NO finalizer.

    Textual restores the terminal at interpreter shutdown, which the removal path never reaches —
    so the removal succeeded, printed, and handed back a terminal still in raw mode: no echo, and
    Enter never forming a line. It looked exactly like a hang, and only Ctrl-C got out. Reported
    from a real macOS run.

    Driven through a real pty, because the defect only exists where there is a terminal to leave
    broken. Asserts the flags a shell needs to be usable, not that some code ran.
    """
    import os
    import pty
    import termios
    import time
    import tty

    target = tmp_path / "parent" / "core"
    (target / "x").mkdir(parents=True)
    (target / "x" / "f").write_text("y", encoding="utf-8")

    pid, fd = pty.fork()
    if pid == 0:  # pragma: no cover - the child execs away
        try:
            # fd 0 directly: pytest replaces `sys.stdin` with a capture object whose `fileno()`
            # raises, and under `pty.fork` fd 0 IS the pty either way.
            saved = termios.tcgetattr(0)
            tty.setraw(0)  # what the TUI does
            from mosaera_api.setup.__main__ import _hand_off_removal

            _hand_off_removal(target, saved)
        except BaseException:
            os._exit(1)

    time.sleep(0.6)
    try:
        while os.read(fd, 1024):
            pass
    except OSError:
        pass
    os.waitpid(pid, 0)

    flags = termios.tcgetattr(fd)[3]
    assert flags & termios.ECHO, "typing would be invisible"
    assert flags & termios.ICANON, "Enter would never form a line — this is the reported hang"
    assert flags & termios.ISIG, "Ctrl-C would be the only way out"
    assert not target.exists(), "and it still has to actually remove the installation"
