"""The wizard's screens, driven headlessly.

Textual's `run_test()` gives a real app with a virtual terminal, so the flow is exercised in CI
where there is no tty at all — the same reason the decisions live in `steps.py` rather than in the
widgets.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from mosaera_api.setup.app import SetupApp
from mosaera_api.setup.steps import Image
from mosaera_core.prereqs import PREREQS, Found, Platform, plan_for


def _found(key: str, *, present: bool) -> Found:
    """A surveyed prerequisite, without touching this machine."""
    prereq = next(p for p in PREREQS if p.key == key)
    detail = "installed" if present else "not installed"
    return Found(prereq, present, detail, plan_for(prereq, Platform("linux", "fedora", "Fedora")))


@pytest.fixture
def satisfied(monkeypatch: pytest.MonkeyPatch) -> None:
    """A machine where everything is already done — the path a re-run takes."""
    monkeypatch.setattr(
        "mosaera_api.setup.enter_steps.survey",
        lambda _bin, _plat: [_found(n, present=True) for n in ("git", "docker", "compose", "node")],
    )
    monkeypatch.setattr(
        "mosaera_api.setup.enter_steps.survey_images",
        lambda _s: [Image("mosaera-sandbox:dev", "f", present=True)],
    )

    class _Store:
        def count_users(self) -> int:
            return 1

    monkeypatch.setattr(
        "mosaera_api.setup.enter_steps.MemoryStore.open_or_reason",
        classmethod(lambda _cls, _url: (_Store(), "")),
    )


@pytest.fixture
def bare(monkeypatch: pytest.MonkeyPatch) -> None:
    """A machine with nothing — the path a first install takes."""
    monkeypatch.setattr(
        "mosaera_api.setup.enter_steps.survey",
        lambda _bin, _plat: [
            _found("git", present=True),
            _found("docker", present=False),
            _found("node", present=False),
        ],
    )
    monkeypatch.setattr(
        "mosaera_api.setup.enter_steps.survey_images",
        lambda _s: [Image("mosaera-sandbox:dev", "infra/docker/sandbox.Dockerfile", present=False)],
    )
    monkeypatch.setattr(
        "mosaera_api.setup.enter_steps.MemoryStore.open_or_reason",
        classmethod(lambda _cls, _url: (None, "connection refused")),
    )


@pytest.mark.usefixtures("satisfied")
def test_a_configured_machine_is_told_so_instead_of_walked_through_setup(tmp_path: Path) -> None:
    """Every step self-skips when satisfied — except access, which always stops — so a finished
    instance got dropped back into the flow with no acknowledgement it was already finished."""

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            # The readiness probe is a worker now — forty seconds of `docker` calls and a database
            # connect, which used to run inline on the first frame and freeze the application.
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.step == "configured"
            # The cursor rests on the first row, whose text matches the instance's actual state —
            # "Stop Mosaera" when it is up, "Start Mosaera" when it is not. Nothing here is
            # serving, so it offers to start.
            assert app._options[0] in ("Stop Mosaera", "Start Mosaera")
            assert app._selected == 0
            assert app._options[-1] == "Uninstall Mosaera"

    asyncio.run(_body())


@pytest.mark.usefixtures("satisfied")
def test_re_running_setup_from_the_configured_screen_does_not_bounce_back(tmp_path: Path) -> None:
    """Without the flag, welcome re-detects the finished instance and returns the operator to the
    screen they just left."""
    from mosaera_api.setup import choices

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await choices.dispatch(app, 1)  # "Re-run setup"
            await pilot.pause()
            assert app.step != "configured"

    asyncio.run(_body())


@pytest.mark.usefixtures("bare")
def test_a_bare_machine_stops_on_the_machine_step_and_shows_each_command(tmp_path: Path) -> None:
    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            assert app.step == "machine"
            # The exact command, beside the thing it installs — never "see the docs" — and Docker
            # goes through Docker's own script, which is the only one that brings compose.
            choices = str(app.query_one("#choices").render())
            assert "get.docker.com" in choices
            assert "sudo dnf install -y nodejs npm" in choices

    asyncio.run(_body())


@pytest.mark.usefixtures("bare")
def test_nothing_is_installed_without_a_press(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _body() -> None:
        """Consent is the whole difference between this and the web button I refused to build."""
        ran: list[Any] = []

        def _record(argv: list[str], on_line: Any, cwd: Any = None) -> int:
            ran.append(argv)
            return 0

        # Both paths that could execute something here: the image/database worker's runner and
        # the privileged installer's. Neither may fire without a press.
        monkeypatch.setattr("mosaera_api.setup.build_flow.run_streaming", _record)

        def _installed(_app: Any, found: Any) -> str:
            ran.append(found.prereq.key)
            return ""

        monkeypatch.setattr("mosaera_api.setup.app.install_with_consent", _installed)
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            assert app.step == "machine"
            assert ran == []

    asyncio.run(_body())


@pytest.mark.usefixtures("satisfied")
def test_the_screen_carries_no_chrome(tmp_path: Path) -> None:
    async def _body() -> None:
        # No rail, no header, no footer, no framed log: hierarchy comes from weight and dimness.
        # Every step paints through one shape, so none can drift away from the others.
        app = SetupApp(tmp_path)
        async with app.run_test():
            assert not app.query("Header")
            assert not app.query("Footer")
            assert not app.query("RichLog")
            assert app.query_one("#mark")
            assert app.query_one("#title")

    asyncio.run(_body())


def test_a_public_bind_writes_a_token_and_loopback_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `_set_access` advances, and advancing from an off-spine step is a no-op: stay on the spine.
    monkeypatch.setattr("mosaera_api.setup.enter_steps.configured", lambda _app: None)

    async def _body() -> None:
        from mosaera_api.setup.env_file import read_env_file

        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            await app._set_access(public=True)
            await pilot.pause()
        written = read_env_file(tmp_path / ".env")
        # `guard_bind` refuses to start on a public bind with no token, so the wizard may not
        # write that pair.
        assert written["MOSAERA_API_HOST"] == "0.0.0.0"  # noqa: S104 — asserting the value
        assert written["MOSAERA_API_TOKEN"]

        app2 = SetupApp(tmp_path)
        async with app2.run_test() as pilot:
            await app2._set_access(public=False)
            await pilot.pause()
        assert read_env_file(tmp_path / ".env")["MOSAERA_API_HOST"] == "127.0.0.1"

    asyncio.run(_body())


def test_a_stray_submit_never_reaches_the_account_path(tmp_path: Path) -> None:
    """The bug this pins, found by looking at a render rather than at a test.

    The credential Input is mounted once and hidden between steps. Hidden was not enough: it kept
    FOCUS, so Enter on the welcome screen posted `Input.Submitted`, the submit handler fell through
    to `create_admin`, and the wizard tried to create an administrator with an empty username and
    password. An installer must not have a path from "press Enter to continue" into writing an
    account.
    """
    from unittest.mock import patch

    async def _body() -> None:
        with patch("mosaera_api.setup.admin.create_admin") as created:
            app = SetupApp(tmp_path)
            async with app.run_test():
                assert app._field_for == ""  # nothing is being asked on the welcome screen
                await app._submit_field()
            created.assert_not_called()

    asyncio.run(_body())


def test_the_hidden_field_is_disabled_so_it_cannot_hold_focus(tmp_path: Path) -> None:
    from textual.widgets import Input

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test():
            field = app.query_one("#field-input", Input)
            assert field.has_class("hidden")
            assert field.disabled

    asyncio.run(_body())


def test_the_wordmark_never_moves_between_screens(tmp_path: Path) -> None:
    """The whole point of a pinned header, pinned by measurement rather than by intent.

    Every screen used to sit in one vertically-centred column, so a screen with three lines of copy
    put the wordmark 100px lower than a screen with six. Measured across four screens it landed at
    four different heights, which reads as the page reloading each time.

    Measured across a bookend and two working steps, because the mark is on ALL of them. It briefly
    was not — the working steps wore a one-line bar to buy back the twelve rows the art costs — and
    what that bought was a screen whose content floated in the space the header used to fill. The
    box's own height settles that instead; the mark stays.
    """

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test(size=(120, 42)) as pilot:
            seen = set()
            for step in ("welcome", "database", "access", "done", "removed"):
                app.step = step
                await app._enter(step)
                await pilot.pause()
                mark = app.query_one("#mark")
                seen.add((mark.region.y, mark.region.height))
                # And it must actually be drawn: an auto-width parent once collapsed it to zero
                # columns, present in the widget tree and invisible on screen.
                assert mark.region.width > 0
            assert len(seen) == 1, f"the wordmark moved: {seen}"

    asyncio.run(_body())


def test_the_title_lands_on_the_same_row_on_every_working_step(tmp_path: Path) -> None:
    """One baseline, and the reason the box has a minimum height.

    The title used to move with the length of the copy beneath it, because the stage was centred and
    only as tall as its content — so every step re-taught the eye where to look. Centred with a
    floor under its height, a three-line screen and a six-line screen open on the same row.
    """

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test(size=(120, 42)) as pilot:
            rows = set()
            for step in ("machine", "database", "access"):
                app.step = step
                await app._enter(step)
                await pilot.pause()
                rows.add(app.query_one("#title").region.y)
            assert len(rows) == 1, f"the title moved between steps: {rows}"

    asyncio.run(_body())


def test_a_toast_does_not_ride_into_the_next_step(tmp_path: Path) -> None:
    """A message about the screen you just left, shown above the hints of the screen you are on,
    reads as an instruction for the new screen. It survives a repaint of its own step, and nothing
    further."""

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test(size=(120, 42)) as pilot:
            app.step = "database"
            await app._enter("database")
            app._note("Could not reach the database.", error=True)
            await pilot.pause()
            assert "Could not reach" in str(app.query_one("#notice").render())

            await app._enter("database")  # a repaint of the same step keeps it
            await pilot.pause()
            assert "Could not reach" in str(app.query_one("#notice").render())

            await app._enter("access")  # a different step does not
            await pilot.pause()
            assert "Could not reach" not in str(app.query_one("#notice").render())

    asyncio.run(_body())


def test_the_task_list_never_claims_a_percentage() -> None:
    """No caller of the old bar ever reported anything but 0 and then 100, so the bar measured
    nothing and animated a fiction. What is actually known is a state and an elapsed time."""
    from mosaera_api.setup.ui import DONE, FAILED, RUNNING, Row, task_list

    out = task_list(
        [
            Row("Container", DONE, "running", 2.1),
            Row("Database", RUNNING, "creating", started=1.0),
            Row("Schema", FAILED, "no such database"),
            Row("Volume"),
        ]
    )
    assert "%" not in out
    assert "2.1s" in out  # the one honest number
    assert "no such database" in out


def test_a_running_task_keeps_moving_without_a_state_change(tmp_path: Path) -> None:
    """The task list is written when a task CHANGES state, and a long-running task by definition
    does not — so its spinner froze on one frame and its clock read 0.0s for the whole of a
    thirty-second container start. The spinner tick redraws it, so the row turns and the elapsed
    counts up while nothing else happens."""
    from mosaera_api.setup import timers
    from mosaera_api.setup.ui import RUNNING, Row

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test(size=(120, 42)) as pilot:
            app._busy = True
            app._rows([Row("Container", RUNNING, "checking", started=1.0)])
            await pilot.pause()
            first = str(app.query_one("#progress").render())
            app._tick += 1
            timers.paint_status(app)
            await pilot.pause()
            assert str(app.query_one("#progress").render()) != first

    asyncio.run(_body())


def test_every_renderer_draws_to_the_same_measure() -> None:
    """The box is drawn by where the text lands, so the edge has to be one number.

    Each renderer used to pick its own: the note column was padded to 24, a prerequisite's detail
    ran straight on after its label, the access rows were spaced with a hand-counted run of spaces.
    No two screens agreed where the right-hand edge was, and nothing read as a block.
    """
    from mosaera_api.setup import screens
    from mosaera_api.setup.ui import DONE, RUNNING, Row, machine_table, task_list, visible
    from mosaera_core.prereqs import PREREQS, Found, Platform, plan_for

    width = 70
    found = [
        Found(p, True, "installed", plan_for(p, Platform("linux", "fedora", "Fedora")))
        for p in PREREQS
    ]
    blocks = {
        "task_list": task_list(
            [Row("Container", DONE, "running", 2.1), Row("Schema", RUNNING, "migrating")], 0, width
        ),
        "machine_table": machine_table(found, width),
        "access": "\n".join(
            screens.access(
                public_now=False, blocked="", port=8000, lan="192.168.11.69", width=width
            ).choices
        ),
    }
    for name, block in blocks.items():
        drawn = [len(visible(line)) for line in block.splitlines() if line.strip()]
        assert max(drawn) <= width, f"{name} overflows the box: {max(drawn)} > {width}"
        # And at least one line reaches it, or the edge is notional rather than drawn.
        assert width - 2 <= max(drawn) <= width, f"{name} never reaches the box edge: {max(drawn)}"


def test_a_column_is_placed_by_what_it_draws_not_by_what_it_says() -> None:
    """Padding computed on the marked-up string counted `[$dim]creating[/]` as 22 characters, so the
    column moved whenever the colour did — and a failure, which is marked up differently, sat in a
    different place from the success it replaced."""
    from mosaera_api.setup.ui import split, visible

    plain = split("left", "right", 40)
    marked = split("[$dim]left[/]", "[$accent]right[/]", 40)
    assert visible(plain) == visible(marked)
    assert len(visible(marked)) == 40


def test_an_over_long_row_keeps_the_value_and_trims_the_label() -> None:
    """An address or an elapsed time is the fact being read; half of one is worth nothing. And the
    trim must not cut through a markup tag — a sliced `[$dim` paints the rest of the screen."""
    from mosaera_api.setup.ui import split, visible

    out = split("[$dim]" + "a" * 60 + "[/]", "[$accent]127.0.0.1:8000[/]", 30)
    assert "127.0.0.1:8000" in visible(out)
    assert len(visible(out)) <= 30
    assert out.count("[/]") == out.count("[$dim]") + out.count("[$accent]")


def test_the_palette_has_one_source() -> None:
    """The stylesheet and the renderers must agree, because they are two halves of one palette and
    only one of them can be checked by eye."""
    from mosaera_api.setup import ui

    css = (Path(ui.__file__).parent / "app.tcss").read_text(encoding="utf-8")
    for name, value in (
        ("accent", ui.ACCENT),
        ("dim", ui.DIM),
        ("alarm", ui.ALARM),
        ("faint", ui.FAINT),
    ):
        assert f"${name}: {value};" in css, f"${name} in the stylesheet is not {value}"


def test_a_dimmed_label_is_actually_dimmed(tmp_path: Path) -> None:
    """Asserted on the PIXELS, because the thing this catches is invisible in the source.

    `[$dim]` and `[$alarm]` were markup referring to stylesheet variables — and Textual resolves a
    `$name` inside content markup against the THEME's variables, not this file's. They silently did
    nothing: every dimmed label had been drawing at the widget's own full brightness since the first
    one, which is why the screens read as a wall of equally-weighted text, and an error toast was
    never once red.
    """
    from mosaera_api.setup import ui

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test(size=(120, 42)) as pilot:
            app.step = "database"
            await app._enter("database")
            app._note("something failed", error=True)
            await pilot.pause()
            svg = app.export_screenshot().lower()
            assert ui.DIM in svg, "nothing on this screen is drawn dim"
            assert ui.ALARM in svg, "the failure toast is not drawn in the alarm colour"

    asyncio.run(_body())


def test_two_gaps_closed_by_one_command_are_one_row() -> None:
    """A machine with no Docker has no Compose either, and one vendor script closes both. Listed as
    two rows the screen said "Install Docker  curl … | sudo sh" and "Install Docker Compose
    curl … | sudo sh" one under the other — one problem wearing two labels, and an operator being
    asked to pick between two spellings of the same action."""
    from mosaera_api.setup.prereq_bridge import actionable
    from mosaera_core.prereqs import PREREQS, Found, Platform, plan_for

    plat = Platform("linux", "fedora", "Fedora")

    def _gap(key: str) -> Found:
        prereq = next(p for p in PREREQS if p.key == key)
        return Found(prereq, False, "not installed", plan_for(prereq, plat))

    both = actionable([_gap("docker"), _gap("compose")])
    assert [f.prereq.key for f in both] == ["docker"]

    # But a Compose missing on its own is still its own gap — some distributions ship the daemon
    # without the plugin, and that row is the only thing that offers to fix it.
    alone = actionable([_gap("compose")])
    assert [f.prereq.key for f in alone] == ["compose"]

    # And two unrelated tools are never collapsed, whatever else they have in common.
    pair = actionable([_gap("git"), _gap("node")])
    assert [f.prereq.key for f in pair] == ["git", "node"]


def test_a_task_list_does_not_outlive_its_screen(tmp_path: Path) -> None:
    """The spinner tick redraws the list so a running task's clock keeps counting — and it drew from
    `_tasks`, which nothing cleared. Painting the next screen blanked the widget and the very next
    tick put the old rows back, so the database step's work flashed over "Starting Mosaera"."""
    from mosaera_api.setup import timers
    from mosaera_api.setup.ui import RUNNING, Row

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test(size=(120, 42)) as pilot:
            app._begin("Database", "Starting Postgres.")
            app._rows([Row("Container", RUNNING, "checking", started=1.0)])
            await pilot.pause()
            assert "Container" in str(app.query_one("#progress").render())

            app._begin("Starting Mosaera", "Building the dashboard.")
            app._tick += 1
            timers.paint_status(app)
            await pilot.pause()
            assert str(app.query_one("#progress").render()) == ""
            # The log line goes with them. What survives is the bare spinner, which on a screen with
            # no task list is the only thing saying the wizard has not wedged.
            assert "Container" not in str(app.query_one("#status").render())

    asyncio.run(_body())


def test_only_one_thing_spins_at_a_time(tmp_path: Path) -> None:
    """Beside a task list the running row is already turning in the marker column, and a second
    spinner on the log line three columns to its right reads as the two being out of line. With no
    task list the log line keeps its spinner, because then it is the only motion on screen."""
    from mosaera_api.setup import timers
    from mosaera_api.setup.ui import RUNNING, SPINNER, Row

    def _spinning(app: SetupApp) -> bool:
        return any(frame in str(app.query_one("#status").render()) for frame in SPINNER)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test(size=(120, 42)) as pilot:
            app._begin("Starting Mosaera", "Building the dashboard.")
            app._say("Waiting for it to answer…")
            await pilot.pause()
            assert _spinning(app), "nothing is moving on a screen with no task list"

            app._rows([Row("Container", RUNNING, "checking", started=1.0)])
            app._say("Container mosaera-postgres-1 Waiting")
            timers.paint_status(app)
            await pilot.pause()
            assert not _spinning(app), "two spinners, in two different columns"

    asyncio.run(_body())


def test_a_toast_does_not_move_the_screen_it_reports_on(tmp_path: Path) -> None:
    """It is an overlay. In the page's normal flow it took a row from the scroll region, so the
    centred box jumped up when a toast appeared and back down ten seconds later when it expired."""

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test(size=(120, 42)) as pilot:
            app.step = "access"
            await app._enter("access")
            await pilot.pause()
            before = app.query_one("#title").region.y
            app._note("Could not do the thing.", error=True)
            await pilot.pause()
            assert app.query_one("#title").region.y == before
            assert app.query_one("#notice").region.height == 1  # and it is genuinely on screen

    asyncio.run(_body())


def test_one_enter_submits_one_field(tmp_path: Path) -> None:
    """Enter belongs to a focused field. Both this application's key handler AND the field's own
    `Submitted` message were acting on it — measured, in that order — so one Enter on the username
    submitted the username, moved on to ask for the password, and submitted that too, empty. The
    operator arrived at the password prompt already being told it was too short.
    """
    from mosaera_api.setup import admin as admin_step
    from mosaera_api.setup import screens

    seen: list[tuple[str, str]] = []
    real = admin_step.submit

    async def _spy(app: Any, field: str, value: str) -> None:
        seen.append((field, value))
        await real(app, field, value)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test(size=(120, 42)) as pilot:
            app.step = "admin"
            app._paint(screens.admin())
            app._ask("Username", secret=False, for_field="username", hint="3-64 characters.")
            await pilot.pause()
            await pilot.press(*"tester")
            await pilot.press("enter")
            await pilot.pause()
            assert seen == [("username", "tester")]
            # And the field the operator has not submitted is not validated.
            assert app._field_for == "password"
            assert app._notice == ""

    import mosaera_api.setup.app as app_module

    original = app_module.admin_step.submit
    app_module.admin_step.submit = _spy  # type: ignore[assignment]
    try:
        asyncio.run(_body())
    finally:
        app_module.admin_step.submit = original  # type: ignore[assignment]


def test_the_machine_guidance_is_drawn_whole_not_truncated(tmp_path: Path) -> None:
    """Asserting the STRING would not have caught this, and did not.

    The guidance first went into `#detail`, which is `text-wrap: nowrap; text-overflow: ellipsis` —
    correct for the raw cause of a failure, wrong for a paragraph. On a real Mac it rendered as
    "Install Docker Desktop from the page above (it includes C…", cutting off the half that says
    installing Homebrew lets this wizard set up Colima. Advice that is visible but truncated is
    worse than advice that is absent, because it looks like all of it.

    So this reads the pixels: every word must appear in a line the widget actually draws.
    """
    from mosaera_api.setup import screens
    from mosaera_core.prereqs import ABSENT, PREREQS, Found, Platform, plan_for

    async def _body() -> None:
        for size in ((152, 49), (80, 30)):
            app = SetupApp(tmp_path)
            async with app.run_test(size=size) as pilot:
                # The readiness probe is a WORKER; without this it repaints over the screen below.
                await app.workers.wait_for_complete()
                await pilot.pause()
                plat = Platform("darwin", "", "macOS", brew=False)
                found = [
                    Found(
                        prereq=p,
                        present=p.key not in ("docker", "compose"),
                        detail="not installed",
                        reason=ABSENT,
                        plan=plan_for(p, plat),
                    )
                    for p in PREREQS
                ]
                gaps = [f for f in found if not f.present]
                app._paint(screens.machine(found, gaps, plat, app.measure))
                await pilot.pause()

                widget = app.query_one("#body")
                drawn = " ".join(widget.render_line(y).text for y in range(widget.size.height))
                for word in ("Homebrew", "brew.sh", "Colima", "no agreement to accept"):
                    assert word in drawn, f"{word!r} missing at {size}: {drawn!r}"
                assert "…" not in drawn and "..." not in drawn, "the paragraph was cut off"

    asyncio.run(_body())


# --- G4: the address, account and log path outlive the alternate screen -------------------------
#
# `outcome_lines` is a pure function precisely so these claims can be checked without a terminal —
# see its docstring in `__main__.py`. Each branch is a fact the wizard is allowed to assert on its
# way out; an untested branch is a claim nobody checked.


def _outcome(**overrides: Any) -> list[str]:
    from mosaera_api.setup.__main__ import outcome_lines

    args: dict[str, Any] = {
        "code": 0,
        "url": "http://127.0.0.1:8000",
        "username": "ana",
        "serving": True,
        "log": "/home/x/.mosaera/api.log",
        "log_exists": True,
        "step": "admin",
        "removed": False,
        "reenter": "cd /repo && uv run mosaera-setup",
    }
    args.update(overrides)
    return outcome_lines(**args)


def test_outcome_lines_running_names_the_url_and_the_account() -> None:
    body = "\n".join(_outcome())
    assert "http://127.0.0.1:8000" in body
    assert "Sign in as  ana" in body
    assert "Server log:  /home/x/.mosaera/api.log" in body
    assert "cd /repo && uv run mosaera-setup" in body


def test_outcome_lines_running_with_no_new_account_points_at_the_existing_one() -> None:
    """No account was created THIS session — a re-run against an already-configured instance. A
    fabricated username would be worse than admitting the wizard does not know one."""
    body = "\n".join(_outcome(username=""))
    assert "ana" not in body
    assert "sign in with the one made" in body


def test_outcome_lines_finished_but_nothing_answers() -> None:
    body = "\n".join(_outcome(serving=False, code=0))
    assert "nothing is answering" in body
    assert "make up" in body


def test_outcome_lines_abandoned_names_the_known_step() -> None:
    """G3: an interactive abandon exits non-zero. What was reached, and that resuming skips it, are
    the two facts an operator stranded at a bare prompt needs."""
    body = "\n".join(_outcome(code=1, serving=False, log_exists=False, step="database"))
    assert "the database step" in body
    assert "running setup again skips it" in body
    assert "No server log was written" in body


def test_outcome_lines_abandoned_at_an_unknown_step_names_it_honestly() -> None:
    """A step outside `resume._NAMES` (the bookends) must not be silently dropped — it is named
    literally rather than defaulting to a step the operator was never actually at."""
    body = "\n".join(_outcome(code=1, serving=False, step="welcome"))
    assert "'welcome' step" in body


def test_outcome_lines_removed_says_the_install_was_kept() -> None:
    """`_hand_off_removal` execs away before `_print_outcome` can run when the whole install was
    taken — reaching this branch means only components were removed."""
    body = "\n".join(_outcome(removed=True, code=0))
    assert "installation was kept" in body
    assert "Sign in as" not in body


def test_outcome_lines_never_prints_a_line_it_does_not_know() -> None:
    """The contract stated in the function's own docstring: an unknown value is named as unknown,
    never guessed at. Exercised here by asking about a log that was never written."""
    body = "\n".join(_outcome(code=1, serving=False, log_exists=False))
    assert "unknown" not in body  # nothing here was asked to fabricate a value
    assert "No server log was written" in body


def test_print_outcome_writes_the_wizards_real_state_after_run_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The wiring, not just the pure function: `_print_outcome` must pull its facts from the app
    and the machine RIGHT NOW (`responds_ok`), not from what a screen believed a countdown ago."""
    from mosaera_api.setup import __main__ as setup_main
    from mosaera_api.setup import done_flow, launch

    class _Settings:
        home = tmp_path / ".mosaera"

    class _App:
        settings = _Settings()
        _username = "ana"
        step = "admin"

    monkeypatch.setattr(done_flow, "bind", lambda _app: ("127.0.0.1", 8000))
    monkeypatch.setattr(launch, "responds_ok", lambda _h, _p: True)

    setup_main._print_outcome(_App(), 0, tmp_path)
    out = capsys.readouterr().out
    assert "http://127.0.0.1:8000" in out
    assert "Sign in as  ana" in out
    # A successful, serving outcome with no log file says nothing about the log at all — silence
    # about a log nobody needed is correct; only a failure/not-serving outcome flags it as missing.
    assert "Server log" not in out
    assert f"cd {tmp_path} && uv run mosaera-setup" in out


def test_the_exit_failsafe_releases_a_terminal_a_stuck_worker_would_hold(tmp_path: Path) -> None:
    """The CachyOS hang (2026-09-03): a `@work(thread=True)` build/probe still running when the
    app exits makes `App.run()` never return — asyncio's loop teardown joins the worker executor
    with no timeout — so the operator's shell never comes back. `SetupApp.exit` starts a daemon
    failsafe (`_force_exit_after_teardown`) that force-exits regardless. Proven in a real
    subprocess against the real hang: a plain Textual App with a stuck worker reproduces it (a
    subclass of the full SetupApp will not mount headless), wired to the SAME failsafe helper the
    wizard ships, so the assertion is that the process ends promptly rather than at the worker's
    timeout (or never). Without the failsafe this subprocess hangs to the 20s ceiling.
    """
    import subprocess
    import sys
    import textwrap

    prog = textwrap.dedent(
        """
        import time
        from textual.app import App
        from textual import work
        from mosaera_api.setup.app import SetupApp

        class _P(App):
            def on_mount(self):
                self._block()
                self.set_timer(0.2, lambda: self.exit(0))

            def exit(self, result=None, return_code=0, message=None):
                # The real failsafe the wizard arms (launch.arm_exit_failsafe), on a plain App that
                # actually reproduces the executor-join hang headless.
                from mosaera_api.setup import launch
                launch.arm_exit_failsafe(return_code)
                super().exit(result, return_code, message)

            @work(thread=True, exit_on_error=False)
            def _block(self):
                time.sleep(120)  # still in a syscall when the app exits

        print("BEFORE-RUN", flush=True)
        _P().run(headless=True)
        print("RUN-RETURNED", flush=True)  # reached only if teardown did not hang
        """
    )
    script = tmp_path / "stuck.py"  # a real file: @work introspects the worker's source
    script.write_text(prog, encoding="utf-8")
    # The failsafe fires ~3s after exit is requested; the bug hangs for the worker's 120s. A 20s
    # ceiling cleanly separates "released" from "hung".
    r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, f"expected a forced clean exit, got {r.returncode}: {r.stderr[-400:]}"
    assert "BEFORE-RUN" in r.stdout
