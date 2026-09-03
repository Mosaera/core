"""What the wizard SAYS about a running server — and whether it is true.

Split out of `test_setup_flow.py` at the 1500-line test ceiling. Cohesive on its own: every test
here is one instance of a single defect family this wizard has met four times — a probe answering a
narrower question than the one asked of it. A refusal read as absence, an open socket read as
health, a stranger's healthy server read as ours, and configuration written under a process that
reads its environment only at start.
"""

from __future__ import annotations

import asyncio
import urllib.error
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from mosaera_api.setup import launch, screens
from mosaera_api.setup.app import SetupApp


def _record(into: list[Any], result: Any = "") -> Any:
    """A stand-in that records its call. Written once: three separate hand-rolled
    `lambda: into.append(x) or y` versions of this were each rejected by mypy, because `append`
    returns None and the `or` then silently changes the stub's return value."""

    def _fn(*args: Any, **_kw: Any) -> Any:
        into.append(args)
        return result

    return _fn


@contextmanager
def _answers(status: int, seen: list[str] | None = None) -> Any:
    if seen is not None:
        seen.append("called")

    class _R:
        pass

    r = _R()
    r.status = status  # type: ignore[attr-defined]
    yield r


def test_an_open_port_that_errors_on_every_request_is_not_serving(monkeypatch: Any) -> None:
    """The completion screen printed "Running at http://127.0.0.1:8000" over an instance the
    browser could only get an Internal Server Error out of. `already_serving` opens a TCP
    connection and a uvicorn that 500s accepts those perfectly, so the wizard never asked the
    server anything — it knocked on the port. Live macOS run, 2026-08-30."""

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise urllib.error.HTTPError("u", 500, "Internal Server Error", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(launch.urllib.request, "urlopen", _boom)
    assert launch.responds_ok("127.0.0.1", 8000) is False


def test_a_healthy_instance_is_serving(monkeypatch: Any) -> None:
    monkeypatch.setattr(launch.urllib.request, "urlopen", lambda url, *a, **k: _answers(200))
    assert launch.responds_ok("127.0.0.1", 8000) is True


def test_a_bind_all_host_is_probed_on_loopback(monkeypatch: Any) -> None:
    """0.0.0.0 is not an address you can connect TO — the trap `already_serving` documents."""
    seen: list[str] = []

    def _record(url: str, *_a: Any, **_k: Any) -> Any:
        seen.append(url)
        return _answers(200)

    monkeypatch.setattr(launch.urllib.request, "urlopen", _record)
    assert launch.responds_ok("0.0.0.0", 8000) is True  # noqa: S104 — the bug this test names
    assert "127.0.0.1" in seen[0]


def test_waiting_polls_health_not_the_socket(monkeypatch: Any) -> None:
    """A wait that polled the socket returns True the instant uvicorn binds — before the app can
    fail. That is the same bug moved one function along."""
    monkeypatch.setattr(launch, "already_serving", lambda *_a, **_k: True)
    monkeypatch.setattr(launch, "our_pid", lambda *_a, **_k: 4242)  # it is OURS
    monkeypatch.setattr(launch, "responds_ok", lambda *_a, **_k: False)
    assert launch.wait_until_serving("127.0.0.1", 8000, timeout=0.3) is False


def test_minting_a_key_under_a_running_server_says_it_is_not_in_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Red-team round 2, and the highest-severity finding of the pass.

    `encrypt_secret` with no key in the environment is the IDENTITY function — it stores the
    credential in plaintext and only warns. A server started BEFORE the mint therefore keeps
    writing plaintext, while the wizard paints a success screen and ADR-0126 claims every install
    encrypts at rest. That is the upgrade path of every install predating the ADR.
    """
    from mosaera_api.setup import done_flow, enter_steps

    monkeypatch.setattr(launch, "already_serving", lambda *_a, **_k: True)
    monkeypatch.setattr(launch, "our_pid", lambda *_a, **_k: 4242)  # it is OURS
    monkeypatch.setattr(launch, "responds_ok", lambda *_a, **_k: True)
    monkeypatch.setattr(enter_steps, "remember_database", lambda _a: "")
    monkeypatch.setattr(enter_steps, "ensure_secret_key", lambda _a: True)  # a key WAS minted

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "done"
            await done_flow.enter(app)
            await pilot.pause()
            assert "plaintext" in app._access_note
            assert "Restart" in app._access_note

    asyncio.run(_body())


def test_no_note_when_the_key_was_already_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The common re-run. Nothing was minted, so nothing is stale and the screen stays quiet."""
    from mosaera_api.setup import done_flow, enter_steps

    monkeypatch.setattr(launch, "already_serving", lambda *_a, **_k: True)
    monkeypatch.setattr(launch, "our_pid", lambda *_a, **_k: 4242)  # it is OURS
    monkeypatch.setattr(launch, "responds_ok", lambda *_a, **_k: True)
    monkeypatch.setattr(enter_steps, "remember_database", lambda _a: "")
    monkeypatch.setattr(enter_steps, "ensure_secret_key", lambda _a: False)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "done"
            await done_flow.enter(app)
            await pilot.pause()
            assert "plaintext" not in app._access_note

    asyncio.run(_body())


def test_a_strangers_server_on_our_port_is_not_reported_as_ours(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The third sighting of one defect family, and the one an operator actually hit.

    An orphaned Mosaera from a previous install answers /healthz perfectly. Taking that as our own
    instance made a fresh install skip its dashboard build AND its launch and still show a live
    address — `dist/index.html` missing, no `api.pid`, no `api.log`, port 8000 answering 200
    (macOS, 2026-08-31). We must still not start a second server on a held port; we must also not
    claim the stranger's.
    """
    from mosaera_api.setup import done_flow, enter_steps

    started: list[object] = []
    monkeypatch.setattr(launch, "already_serving", lambda *_a, **_k: True)
    monkeypatch.setattr(launch, "our_pid", lambda *_a, **_k: 0)  # nothing of OURS is running
    monkeypatch.setattr(launch, "responds_ok", lambda *_a, **_k: True)  # the stranger is healthy

    monkeypatch.setattr(launch, "start_detached", _record(started, (1, tmp_path)))
    monkeypatch.setattr(enter_steps, "remember_database", lambda _a: "")
    monkeypatch.setattr(enter_steps, "ensure_secret_key", lambda _a: False)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "done"
            await done_flow.enter(app)
            await pilot.pause()
            assert app._serving is False, "a stranger's server is not ours to report as running"
            assert started == [], "a held port must still stop us starting a second server"
            # And it goes STRAIGHT TO THE FIX. Naming the conflict in a note and leaving the
            # operator to run `lsof` and edit `.env` is a diagnosis by a tool holding the repair.
            assert app._api_port_conflict is True
            assert app._field_for == "api_port", "the port picker is on screen, not a note"

    asyncio.run(_body())


def test_changing_the_bind_under_a_running_server_actually_applies_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`mosaera-api` reads its environment at START, so rewriting `.env` under a live process is a
    no-op the operator reads as applied. Going network -> this-machine-only that way left the
    instance REACHABLE — the opposite of what was asked for — while the screen reported success.
    Reported 2026-08-31.
    """
    from mosaera_api.setup import done_flow, enter_steps

    stopped: list[object] = []
    monkeypatch.setattr(launch, "already_serving", lambda *_a, **_k: True)
    monkeypatch.setattr(launch, "our_pid", lambda *_a, **_k: 4242)
    monkeypatch.setattr(launch, "responds_ok", lambda *_a, **_k: True)
    monkeypatch.setattr(launch, "stop", _record(stopped))
    monkeypatch.setattr(enter_steps, "remember_database", lambda _a: "")
    monkeypatch.setattr(enter_steps, "ensure_secret_key", lambda _a: False)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "done"
            app._needs_restart = True  # the access step rewrote the bind
            await done_flow.enter(app)
            await pilot.pause()
            assert stopped, "a changed bind must not be left to a process that cannot see it"
            assert app._needs_restart is False

    asyncio.run(_body())


def test_an_unchanged_rerun_does_not_bounce_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The common re-run. Nothing was written, so nothing is stale and the instance is left alone —
    restarting a healthy server to apply no change is its own kind of dishonesty."""
    from mosaera_api.setup import done_flow, enter_steps

    stopped: list[object] = []
    monkeypatch.setattr(launch, "already_serving", lambda *_a, **_k: True)
    monkeypatch.setattr(launch, "our_pid", lambda *_a, **_k: 4242)
    monkeypatch.setattr(launch, "responds_ok", lambda *_a, **_k: True)
    monkeypatch.setattr(launch, "stop", _record(stopped))
    monkeypatch.setattr(enter_steps, "remember_database", lambda _a: "")
    monkeypatch.setattr(enter_steps, "ensure_secret_key", lambda _a: False)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "done"
            await done_flow.enter(app)
            await pilot.pause()
            assert stopped == []

    asyncio.run(_body())


def test_the_hint_does_not_promise_a_server_that_did_not_start() -> None:
    assert "leave it running" in screens.done("u", "n", serving=True, log="l", seconds=9).hint
    assert "leave it running" not in screens.done("u", "n", serving=False, log="l", seconds=9).hint


# ------------------------------------------------------- the sweep: presence is not currency


def test_a_dashboard_older_than_its_source_is_not_built(tmp_path: Path) -> None:
    """`install.sh` updates the clone IN PLACE, so presence-only meant every update served a new
    backend behind the previous dashboard. The API already calls this "the classic reason
    freshly-added UI doesn't appear" — and warns into api.log, too late and unread."""
    import os

    web = tmp_path / "apps" / "web"
    (web / "dist").mkdir(parents=True)
    (web / "src").mkdir(parents=True)
    index = web / "dist" / "index.html"
    index.write_text("<html>")
    src = web / "src" / "App.tsx"
    src.write_text("x")

    os.utime(index, (2_000_000_000, 2_000_000_000))
    os.utime(src, (1_000_000_000, 1_000_000_000))
    assert launch.dashboard_built(tmp_path) is True, "a bundle newer than its source is current"

    os.utime(src, (2_100_000_000, 2_100_000_000))
    assert launch.dashboard_built(tmp_path) is False, "source newer than the bundle means rebuild"


def test_a_packaged_tree_with_no_source_falls_back_to_presence(tmp_path: Path) -> None:
    """No `src/` is a built wheel: presence is the only question there is, and the honest answer."""
    web = tmp_path / "apps" / "web"
    (web / "dist").mkdir(parents=True)
    (web / "dist" / "index.html").write_text("<html>")
    assert launch.dashboard_built(tmp_path) is True


def test_a_missing_dashboard_is_still_not_built(tmp_path: Path) -> None:
    assert launch.dashboard_built(tmp_path) is False


def test_the_api_port_picker_refuses_a_port_that_is_also_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same order as `submit_db_port`: CHECK, then keep. Writing first and testing after would
    leave `.env` naming a port that cannot be bound, and the next run would start from that broken
    value with no memory of what it replaced."""
    from mosaera_api.setup import choices, steps

    (tmp_path / ".env").write_text("MOSAERA_API_PORT=8000\n", encoding="utf-8")
    monkeypatch.setattr(steps, "port_is_free", lambda *_a, **_k: False)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "done"
            await choices.submit_api_port(app, "8001")
            await pilot.pause()
            assert app._field_for == "api_port", "it asks again rather than keeping a taken port"
            assert "8001" not in (tmp_path / ".env").read_text()

    asyncio.run(_body())


def test_the_api_port_picker_rejects_nonsense_and_privileged_ports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaera_api.setup import choices

    (tmp_path / ".env").write_text("MOSAERA_API_PORT=8000\n", encoding="utf-8")

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "done"
            for bad in ("eight thousand", "80", "70000", ""):
                await choices.submit_api_port(app, bad)
                await pilot.pause()
                assert app._field_for == "api_port", f"{bad!r} must not be accepted"
            assert "MOSAERA_API_PORT=8000" in (tmp_path / ".env").read_text()

    asyncio.run(_body())


def test_a_free_port_is_kept_in_both_places(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`.env` is what a relaunch reads; `os.environ` is what THIS process reads when it works out
    where to serve. The two disagreeing is the split `submit_db_port` documents."""
    import os

    from mosaera_api.setup import choices, steps

    (tmp_path / ".env").write_text("MOSAERA_API_PORT=8000\n", encoding="utf-8")
    monkeypatch.setattr(steps, "port_is_free", lambda *_a, **_k: True)
    monkeypatch.delenv("MOSAERA_API_PORT", raising=False)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "done"
            app._api_port_conflict = True
            await choices.submit_api_port(app, "8123")
            await pilot.pause()
            assert "MOSAERA_API_PORT=8123" in (tmp_path / ".env").read_text()
            assert os.environ["MOSAERA_API_PORT"] == "8123"
            assert app._api_port_conflict is False

    asyncio.run(_body())


# ------------------------------------------------- ending a process, on a machine without /proc


def test_our_server_is_identified_without_proc(monkeypatch: pytest.MonkeyPatch) -> None:
    """macOS has NO procfs. Reading `/proc` and failing closed is right on Linux and
    UNCONDITIONAL on macOS, so `our_pid` returned 0 for every server the wizard had itself
    started: `stop` found nothing, and every uninstall left the API running with its port bound.
    """
    from mosaera_api.setup import process

    monkeypatch.setattr(process, "cmdline", lambda _p: "/x/.venv/bin/mosaera-api")
    monkeypatch.setattr(process, "cwd", lambda _p: Path("/x"))
    assert launch._is_our_server(1234, Path("/x")) is True
    assert launch._is_our_server(1234, Path("/somewhere-else")) is False

    monkeypatch.setattr(process, "cmdline", lambda _p: "/usr/bin/postgres")
    assert launch._is_our_server(1234, Path("/x")) is False

    # Genuinely unanswerable still fails CLOSED — an unverified pid is never signalled.
    monkeypatch.setattr(process, "cmdline", lambda _p: "")
    assert launch._is_our_server(1234, Path("/x")) is False


def test_terminate_escalates_and_reports_the_process_not_the_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A signal is a request, not an outcome. `stop` sent SIGTERM and returned success, so a
    process that ignored it reported as stopped. SIGTERM -> grace -> SIGKILL -> VERIFY."""
    from mosaera_api.setup import process

    sent: list[int] = []
    state = {"alive": True}

    def _kill(_pid: int, sig: int) -> None:
        sent.append(sig)
        if sig == 9:
            state["alive"] = False  # only SIGKILL gets through

    monkeypatch.setattr(process.os, "kill", _kill)
    monkeypatch.setattr(process, "alive", lambda _p: state["alive"])
    assert process.terminate(4242, grace=0.3) == ""
    assert sent == [15, 9], "SIGTERM first, SIGKILL only after the grace period"


def test_terminate_says_so_when_the_process_survives(monkeypatch: pytest.MonkeyPatch) -> None:
    from mosaera_api.setup import process

    monkeypatch.setattr(process.os, "kill", lambda *_a: None)
    monkeypatch.setattr(process, "alive", lambda _p: True)  # nothing kills it
    assert "still running after SIGKILL" in process.terminate(4242, grace=0.2)


def test_an_orphan_with_no_pid_file_is_still_found_and_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reported case: every box ticked, and a server still holding the port. Its pid file was
    deleted with the installation that wrote it, so `our_pid` saw nothing and the row that stops
    it was never even offered."""
    from mosaera_api.setup import process

    (tmp_path / ".env").write_text("MOSAERA_API_PORT=8000\n", encoding="utf-8")
    monkeypatch.setattr(process, "listeners", lambda _port: [9911])
    monkeypatch.setattr(process, "cmdline", lambda _p: "/old/.venv/bin/mosaera-api")
    assert launch._our_holders(tmp_path, tmp_path) == [9911]

    killed: list[int] = []
    monkeypatch.setattr(process, "terminate", _record(killed))
    assert launch.stop(tmp_path, tmp_path) == ""
    assert killed == [(9911,)], "an orphan that identifies as a Mosaera API is stopped"


def test_a_strangers_process_on_our_port_is_never_touched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unidentified process on a port is somebody else's, and stays that way."""
    from mosaera_api.setup import process

    (tmp_path / ".env").write_text("MOSAERA_API_PORT=8000\n", encoding="utf-8")
    monkeypatch.setattr(process, "listeners", lambda _port: [9911])
    monkeypatch.setattr(process, "cmdline", lambda _p: "/usr/bin/some-other-server")
    assert launch._our_holders(tmp_path, tmp_path) == []


def test_the_port_prompt_does_not_blame_a_leftover_mosaera() -> None:
    """An uninstall leaves nothing behind, so "probably an old Mosaera" is a sentence this product
    must not need — and a first-time operator must never read their clean machine as dirty."""
    body = screens.api_port_prompt(8001, 8000).body
    assert "Mosaera" not in body
    assert "already in use" in body


def test_cmdline_works_on_a_machine_with_no_proc(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE macOS regression itself, not the logic above it.

    `test_our_server_is_identified_without_proc` stubs `cmdline`, so it survives a `/proc`-only
    implementation — reverting the fallback left it green. This one denies `/proc` the way macOS
    does and asserts the process is still identified, which is the property that was missing.
    """
    import os
    import shutil

    from mosaera_api.setup import process

    # The property under test is the FALLBACK, so it needs the thing it falls back to. On a host
    # without `ps` (Debian slim ships no `procps`) `cmdline` correctly returns "" and this would
    # fail while asserting nothing about the code — an environment capability, not a defect. CI
    # installs `procps` precisely so this runs there; the skip is for hosts that do not.
    if shutil.which("ps") is None:
        pytest.skip("no `ps` on this host — the /proc fallback has nothing to fall back to")

    real = Path.read_bytes

    def _no_proc(self: Path, *a: object, **k: object) -> bytes:
        if str(self).startswith("/proc/"):
            raise OSError("no procfs here")
        return real(self, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_bytes", _no_proc)
    assert process.cmdline(os.getpid()), "with no /proc, `ps` must still identify the process"
    assert "python" in process.cmdline(os.getpid()).lower()


def test_changing_the_port_migrates_the_instance_instead_of_adding_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reported 2026-09-01: switching from a machine-only bind to a network bind built a dashboard
    on the new port and left the old one running — two dashboards, two ports.

    The restart was gated on something answering at the NEW address. The old server is on the
    PREVIOUS one, so the branch was skipped and nothing stopped it. `stop` asks the pid file,
    which names our server wherever it happens to be listening.
    """
    from mosaera_api.setup import done_flow, enter_steps

    stopped: list[object] = []
    monkeypatch.setattr(launch, "already_serving", lambda *_a, **_k: False)  # new port is FREE
    monkeypatch.setattr(launch, "our_pid", lambda *_a, **_k: 0)
    monkeypatch.setattr(launch, "stop", _record(stopped))
    monkeypatch.setattr(launch, "dashboard_built", lambda *_a, **_k: True)
    monkeypatch.setattr(launch, "start_detached", _record([], (1, tmp_path)))
    monkeypatch.setattr(launch, "wait_until_serving", lambda *_a, **_k: True)
    monkeypatch.setattr(enter_steps, "remember_database", lambda _a: "")
    monkeypatch.setattr(enter_steps, "ensure_secret_key", lambda _a: False)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "done"
            app._needs_restart = True  # the access step moved the bind
            await done_flow.enter(app)
            await pilot.pause()
            assert stopped, "the old instance must be stopped even though the NEW port is free"
            assert app._needs_restart is False

    asyncio.run(_body())


def test_a_failed_stop_does_not_start_a_second_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the old one will not die, adding another is the worst available outcome."""
    from mosaera_api.setup import done_flow, enter_steps

    started: list[object] = []
    monkeypatch.setattr(launch, "already_serving", lambda *_a, **_k: False)
    monkeypatch.setattr(launch, "our_pid", lambda *_a, **_k: 0)
    monkeypatch.setattr(launch, "stop", lambda *_a, **_k: "pid 42 is still running after SIGKILL")
    monkeypatch.setattr(launch, "responds_ok", lambda *_a, **_k: True)
    monkeypatch.setattr(launch, "start_detached", _record(started, (1, tmp_path)))
    monkeypatch.setattr(enter_steps, "remember_database", lambda _a: "")
    monkeypatch.setattr(enter_steps, "ensure_secret_key", lambda _a: False)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "done"
            app._needs_restart = True
            await done_flow.enter(app)
            await pilot.pause()
            assert started == [], "never add a second instance when the first would not stop"
            assert "could not be stopped" in app._access_note

    asyncio.run(_body())


def test_the_finished_screen_offers_the_same_three_things_as_the_configured_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reported 2026-09-01: the finished screen offered only Finish and Uninstall, so changing one
    answer meant leaving and running the installer again to be offered "Re-run setup" — the same
    instance and the same wizard, with two different menus depending on which screen you were on.
    """
    from mosaera_api.setup import done_flow

    assert screens.done("u", "n", serving=True, log="l", seconds=9).choices == [
        "Finish now",
        "Re-run setup",
        "Uninstall Mosaera",
    ]

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "done"
            await done_flow.chose(app, 1)
            await pilot.pause()
            assert app.step == "welcome", "re-run walks the spine again"

    asyncio.run(_body())


def test_the_sandbox_images_are_built_inside_the_startup_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Sandbox images" was one screen out of five, and there was nothing on it to decide: the
    images are present or they are not, and the answer is always "build them". It is WORK, so it
    belongs in the one step that does work — beside the dashboard build and the server launch."""
    from mosaera_api.setup import app as app_mod
    from mosaera_api.setup import build_flow, done_flow, enter_steps

    assert "images" not in app_mod.STEPS
    assert app_mod.STEPS == ("welcome", "machine", "database", "access", "admin", "done")

    order: list[str] = []

    def _images(_a: Any) -> list[str]:
        order.append("images")
        return []

    def _dashboard(*_a: Any) -> bool:
        order.append("dashboard?")
        return True

    monkeypatch.setattr(build_flow, "build_missing_images", _images)
    monkeypatch.setattr(launch, "dashboard_built", _dashboard)
    monkeypatch.setattr(launch, "already_serving", lambda *_a, **_k: False)
    monkeypatch.setattr(launch, "our_pid", lambda *_a, **_k: 0)
    monkeypatch.setattr(launch, "start_detached", _record(order, (1, tmp_path)))
    monkeypatch.setattr(launch, "wait_until_serving", lambda *_a, **_k: True)
    monkeypatch.setattr(enter_steps, "remember_database", lambda _a: "")
    monkeypatch.setattr(enter_steps, "ensure_secret_key", lambda _a: False)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "done"
            await asyncio.to_thread(done_flow.bring_up, app)
            await pilot.pause()
            assert order and order[0] == "images", "images are built FIRST, before the dashboard"

    asyncio.run(_body())


def test_an_unbuildable_image_does_not_stop_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The images are what RUNS work, not what serves the dashboard. Refusing to start over one
    would take away the operator's ability to reach Settings and fix it — and `_outstanding`
    already reports the gap on the configured screen."""
    from mosaera_api.setup import build_flow, done_flow, enter_steps

    started: list[object] = []
    monkeypatch.setattr(build_flow, "build_missing_images", lambda _a: ["mosaera-sandbox — failed"])
    monkeypatch.setattr(launch, "dashboard_built", lambda *_a: True)
    monkeypatch.setattr(launch, "already_serving", lambda *_a, **_k: False)
    monkeypatch.setattr(launch, "our_pid", lambda *_a, **_k: 0)
    monkeypatch.setattr(launch, "start_detached", _record(started, (1, tmp_path)))
    monkeypatch.setattr(launch, "wait_until_serving", lambda *_a, **_k: True)
    monkeypatch.setattr(enter_steps, "remember_database", lambda _a: "")
    monkeypatch.setattr(enter_steps, "ensure_secret_key", lambda _a: False)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "done"
            await asyncio.to_thread(done_flow.bring_up, app)
            await pilot.pause()
            assert started, "a missing sandbox image must not cost the operator the dashboard"

    asyncio.run(_body())


def test_the_first_row_stops_a_running_instance_without_uninstalling_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Leave it running" was not an action — Ctrl-Q already leaves it running, so the most
    prominent row on the screen did what quitting does. What was MISSING is the other direction:
    someone who wants the instance down and does not want it removed had only "Uninstall Mosaera".
    """
    from mosaera_api.setup import choices, enter_steps

    stopped: list[object] = []
    monkeypatch.setattr(launch, "already_serving", lambda *_a, **_k: True)
    monkeypatch.setattr(launch, "stop", _record(stopped))
    monkeypatch.setattr(enter_steps, "configured", lambda _a: None)

    _serving = True

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "configured"
            # The rows come from the SCREEN, because dispatch reads their text — a hand-made list
            # here would be testing this test's idea of the rows rather than the wizard's.
            app._options = screens.configured(
                "u", 1, "e", serving=_serving, images_to_build=False
            ).choices
            await choices._configured(app, 0)
            await pilot.pause()
            assert stopped, "the first row brings it down"
            assert "stopped" in app._notice.lower()
            assert "untouched" in app._notice, "and says nothing was deleted"

    asyncio.run(_body())


def test_stopping_does_not_remove_anything(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """It is the option BETWEEN leaving it alone and uninstalling, so it must be neither."""
    from mosaera_api.setup import choices, enter_steps, uninstall_flow

    removed: list[object] = []
    monkeypatch.setattr(launch, "already_serving", lambda *_a, **_k: True)
    monkeypatch.setattr(launch, "stop", lambda *_a, **_k: "")
    monkeypatch.setattr(uninstall_flow, "perform", _record(removed))
    monkeypatch.setattr(enter_steps, "configured", lambda _a: None)

    _serving = True

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "configured"
            # The rows come from the SCREEN, because dispatch reads their text — a hand-made list
            # here would be testing this test's idea of the rows rather than the wizard's.
            app._options = screens.configured(
                "u", 1, "e", serving=_serving, images_to_build=False
            ).choices
            await choices._configured(app, 0)
            await pilot.pause()
            assert removed == [], "stopping is not uninstalling"

    asyncio.run(_body())


def test_a_stop_that_fails_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from mosaera_api.setup import choices, enter_steps

    monkeypatch.setattr(launch, "already_serving", lambda *_a, **_k: True)
    monkeypatch.setattr(launch, "stop", lambda *_a, **_k: "pid 42 is still running after SIGKILL")
    monkeypatch.setattr(enter_steps, "configured", lambda _a: None)

    _serving = True

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "configured"
            # The rows come from the SCREEN, because dispatch reads their text — a hand-made list
            # here would be testing this test's idea of the rows rather than the wizard's.
            app._options = screens.configured(
                "u", 1, "e", serving=_serving, images_to_build=False
            ).choices
            await choices._configured(app, 0)
            await pilot.pause()
            assert "could not stop" in app._notice.lower()

    asyncio.run(_body())


def test_the_first_row_still_starts_a_stopped_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaera_api.setup import choices

    monkeypatch.setattr(launch, "already_serving", lambda *_a, **_k: False)
    monkeypatch.setattr(
        launch, "stop", lambda *_a, **_k: pytest.fail("must not stop a stopped one")
    )

    _serving = False

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "configured"
            # The rows come from the SCREEN, because dispatch reads their text — a hand-made list
            # here would be testing this test's idea of the rows rather than the wizard's.
            app._options = screens.configured(
                "u", 1, "e", serving=_serving, images_to_build=False
            ).choices
            await choices._configured(app, 0)
            await pilot.pause()
            assert app.step == "done", "the same path that starts it at the end of a first run"

    asyncio.run(_body())


def test_the_configured_screen_can_close_the_gap_it_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gap with no way to close it is a dead end, and this screen had one: it reported "2 sandbox
    images to build" while offering only Start, Re-run, Reset and Uninstall. The only route was
    Re-run, which walks the whole spine to reach the one thing missing. Reported 2026-09-02:
    "there's no way to just run that part"."""
    from mosaera_api.setup import build_flow, choices

    rows = screens.configured("u", 1, "e", serving=True, images_to_build=True).choices
    assert screens.BUILD_IMAGES in rows, "the gap is actionable from the screen that reports it"
    assert screens.BUILD_IMAGES not in screens.configured("u", 1, "e", serving=True).choices, (
        "and absent when there is nothing to build"
    )

    built: list[object] = []
    monkeypatch.setattr(build_flow, "build_images_only", _record(built))

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "configured"
            app._options = rows
            await choices._configured(app, rows.index(screens.BUILD_IMAGES))
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert built, "the row builds them, without walking the spine to get there"

    asyncio.run(_body())


def test_the_configured_rows_are_dispatched_on_text_not_position(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A conditional row makes positions lie. The database step already learned this — a positional
    map ran the wrong action the moment its rows changed — and the same mistake was one edit away
    here the moment "Build the sandbox images" became conditional."""
    from mosaera_api.setup import choices, password_reset

    reset: list[object] = []

    async def _enter(*args: Any, **_kw: Any) -> None:
        reset.append(args)

    monkeypatch.setattr(password_reset, "enter", _enter)

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            app.step = "configured"
            # WITH the extra row present, so "Reset a password" is at a different index than it
            # would be without it. Position would pick the wrong action; text picks the right one.
            rows = screens.configured("u", 1, "e", serving=True, images_to_build=True).choices
            app._options = rows
            await choices._configured(app, rows.index("Reset a password"))
            await pilot.pause()
            assert reset, "the row that says reset is the row that resets"

    asyncio.run(_body())
