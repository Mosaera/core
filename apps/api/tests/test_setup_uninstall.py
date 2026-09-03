"""Uninstall — and the line it must not cross.

Most machines already had Docker, git or Node before Mosaera arrived. Removing those because we
happen to need them would break unrelated work, and "present" is indistinguishable from "we put it
there" after the fact. So the wizard records what it installs, and only what is recorded is offered.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from mosaera_api.setup import uninstall
from mosaera_api.setup.uninstall import (
    Removable,
    commands_for,
    installed_by_setup,
    paths_for,
    plan,
    record_install,
)
from mosaera_api.setup.uninstall_text import survives
from mosaera_core.config import Settings


@pytest.fixture(autouse=True)
def _as_if_a_full_install_had_happened(monkeypatch: pytest.MonkeyPatch) -> None:
    """This module asks WHICH rows the recording policy offers. That is a different question from
    whether the thing a row removes exists at all.

    The plan is gated on both now — a run that never started a container is not offered to stop
    one — and the environment half is orthogonal here and has its own tests in `test_setup_flow.py`.
    Without this the whole module would be asserting against an empty list and proving nothing.
    """
    monkeypatch.setattr(uninstall, "docker_available", lambda *a, **k: True)
    monkeypatch.setattr(uninstall, "_compose_project_exists", lambda *a, **k: True)
    monkeypatch.setattr(uninstall, "_our_config_exists", lambda *a, **k: True)
    # The destructive row is only offered when there is a volume to destroy, and several tests here
    # turn on it existing. Patch the PREDICATE, not `data_volume` — that function works out what the
    # volume is called and has its own tests, which a blanket stub would silently answer for.
    monkeypatch.setattr(uninstall, "_data_exists", lambda *a, **k: True)


def test_a_prereq_we_did_not_install_is_never_offered(tmp_path: Path) -> None:
    """The property the whole feature turns on."""
    keys = {r.key for r in plan(Settings.from_env(), tmp_path)}
    assert not any(k.startswith("prereq:") for k in keys)


def test_only_what_we_recorded_is_offered(tmp_path: Path) -> None:
    record_install(tmp_path, "docker")
    keys = {r.key for r in plan(Settings.from_env(), tmp_path)}
    assert "prereq:docker" in keys
    assert "prereq:node" not in keys  # present on this box, but not ours


def test_recording_is_idempotent(tmp_path: Path) -> None:
    # The wizard is re-runnable; a second install attempt must not duplicate the record.
    record_install(tmp_path, "docker")
    record_install(tmp_path, "docker")
    assert installed_by_setup(tmp_path) == ["docker"]


def test_compose_is_not_offered_separately(tmp_path: Path) -> None:
    # It arrives with Docker and leaves with it; a separate entry would imply it can be removed on
    # its own, which is not true of the plugin.
    record_install(tmp_path, "compose")
    assert "prereq:compose" not in {r.key for r in plan(Settings.from_env(), tmp_path)}


def test_stopping_the_database_does_not_touch_its_data(tmp_path: Path) -> None:
    """`--volumes` is the entire difference between stopping and erasing, so the two are separate
    choices and the harmless one comes first."""
    settings = Settings.from_env()
    stop = commands_for("containers", settings, tmp_path, tmp_path)[0]
    erase = commands_for("data", settings, tmp_path, tmp_path)[0]
    assert "--volumes" not in stop
    assert "--volumes" in erase


def test_only_deleting_data_is_marked_irreversible(tmp_path: Path) -> None:
    record_install(tmp_path, "images")  # images are offered only when this wizard built them
    entries = {r.key: r for r in plan(Settings.from_env(), tmp_path)}
    assert entries["data"].destructive is True
    assert entries["images"].destructive is False
    assert entries["containers"].destructive is False
    assert entries["config"].destructive is False


def test_removal_touches_named_files_only(tmp_path: Path) -> None:
    # No globs and no recursion: every path is spelled out, so nothing adjacent can be swept up.
    paths = paths_for("config", tmp_path, tmp_path)
    assert [p.name for p in paths] == ["settings.json", ".env"]
    assert paths_for("images", tmp_path, tmp_path) == []


def test_a_prereq_removal_runs_nothing_by_itself(tmp_path: Path) -> None:
    # Uninstalling a system package needs the operator's own terminal, so it is handed over rather
    # than run behind a progress bar.
    record_install(tmp_path, "docker")
    assert commands_for("prereq:docker", Settings.from_env(), tmp_path, tmp_path) == []


def test_every_offer_says_what_it_costs() -> None:
    for entry in plan(Settings.from_env(), Path("/nonexistent")):
        assert isinstance(entry, Removable)
        assert entry.detail and entry.label


def test_the_confirm_screen_starts_on_cancel_and_cancelling_removes_nothing(tmp_path: Path) -> None:
    """The gate that stands between choosing to uninstall and it happening.

    It is a resting cursor rather than a typed word now. That is a smaller gate than REMOVE looked,
    and the same size as it actually was — a spelling test stops nobody who has already decided —
    but it must still be true that a straight Enter on this screen removes nothing.
    """
    import asyncio
    from unittest.mock import patch

    from mosaera_api.setup import uninstall_flow
    from mosaera_api.setup.app import SetupApp

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            # The readiness probe is a WORKER. Without this it lands mid-test and repaints over the
            # screen the test just set up.
            await app.workers.wait_for_complete()
            await pilot.pause()
            app._removable = plan(Settings.from_env(), tmp_path)
            app._chosen = {i for i, r in enumerate(app._removable) if r.destructive}
            app.step = "uninstall_confirm"
            await uninstall_flow.enter(app)
            await pilot.pause()
            assert app._options[0] == "Cancel"
            assert app._selected == 0  # the cursor rests on the harmless row
            with patch("mosaera_api.setup.uninstall_flow.perform") as done:
                await uninstall_flow.confirmed(app, 0)  # Enter, unmoved
                # Cancel now returns where the operator CAME FROM. There is no picker to fall
                # back to — the checklist it returned to no longer exists.
                assert app.step == app._returns_to
                assert app._chosen, "cancelling must not discard the selection"
                app.step = "uninstall_confirm"
                await uninstall_flow.confirmed(app, 1)  # moved down, then Enter
                await app.workers.wait_for_complete()
                done.assert_called_once()

    asyncio.run(_body())


def test_a_removal_never_leads_back_into_the_flow(tmp_path: Path) -> None:
    """The hang, pinned. `run` used to end at `_returns_to`, which defaults to "done" — so
    finishing an uninstall walked into the completion step and tried to start the server it had
    just removed, then waited ninety seconds for it to answer."""
    import asyncio
    from unittest.mock import patch

    from mosaera_api.setup import uninstall_flow
    from mosaera_api.setup.app import SetupApp

    async def _body() -> None:
        app = SetupApp(tmp_path)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            app._removable = plan(Settings.from_env(), tmp_path)
            app._chosen = {0}
            app._returns_to = "done"  # the value that caused it
            with (
                patch("mosaera_api.setup.uninstall_flow.perform", return_value=["ok"]),
                patch("mosaera_api.setup.launch.start_detached") as spawned,
            ):
                await uninstall_flow.run(app)
                await app.workers.wait_for_complete()
                await pilot.pause()
            assert app.step == "removed"
            spawned.assert_not_called()

    asyncio.run(_body())


def test_every_selected_item_reports_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaera_api.setup.uninstall import perform

    # `perform` VERIFIES each removal by asking Docker whether the thing is really gone, and that
    # probe ignores the stubbed `runner` — so on a host with no Docker it answered "could not
    # verify" and the first item reported `failed`, which is the code being honest about an
    # environment this test is not about. Verification has its own tests; the question here is
    # only whether progress is reported for every item, in order.
    monkeypatch.setattr(uninstall, "_still_there", lambda *a, **k: "")

    entries = [r for r in plan(Settings.from_env(), tmp_path) if not r.destructive][:2]
    assert len(entries) == 2, "the fixture must offer two removable rows or this proves nothing"
    seen: list[tuple[int, str]] = []
    perform(
        entries,
        Settings.from_env(),
        tmp_path,
        tmp_path,
        lambda _l: None,
        lambda _argv, _on: 0,
        lambda i, state, _note: seen.append((i, state)),
    )
    # Each item starts and finishes, in order — a list that only fills in at the end is a log.
    # Reported as a STATE, not a percentage: every one of these is binary, and a bar drawn from a
    # binary fact went from empty to full in one frame while claiming to measure something.
    assert seen == [(0, "running"), (0, "done"), (1, "running"), (1, "done")]


def test_perform_never_removes_a_system_package_itself(tmp_path: Path) -> None:
    from mosaera_api.setup.uninstall import perform

    record_install(tmp_path, "docker")
    entry = next(r for r in plan(Settings.from_env(), tmp_path) if r.key == "prereq:docker")
    ran: list[list[str]] = []

    def _runner(argv: list[str], _on_line: object) -> int:
        ran.append(argv)
        return 0

    out = perform([entry], Settings.from_env(), tmp_path, tmp_path, lambda _l: None, _runner)
    assert ran == []  # nothing was executed on the operator's behalf
    assert "your package manager" in out[0]


def test_the_destructive_row_names_the_volume_it_will_destroy(tmp_path: Path) -> None:
    """The last thing between an operator and their history should say WHAT it will erase.

    The compose project used to be derived from the compose file's own directory, so a scratch
    checkout and a live install resolved to the same volume — and nothing on screen said which one
    was about to go.
    """
    from unittest.mock import patch

    with patch("mosaera_api.setup.uninstall.data_volume", return_value="docker_mosaera-pgdata"):
        row = next(r for r in plan(Settings.from_env(), tmp_path) if r.key == "data")
    assert "docker_mosaera-pgdata" in row.detail
    assert "no undo" in row.detail


def test_an_ordinary_failure_names_its_cause_not_its_exit_code(tmp_path: Path) -> None:
    """`_FAILURE` mapped only the negative runner statuses, so a normal non-zero exit read
    "Delete all project data: exit 1" — a status that names no cause. Seen live."""
    from mosaera_api.setup.uninstall import perform

    entry = next(r for r in plan(Settings.from_env(), tmp_path) if r.key == "containers")

    def _runner(_argv: list[str], on_line: object) -> int:
        on_line("Cannot connect to the Docker daemon at unix:///var/run/docker.sock")  # type: ignore[operator]
        return 1

    out = perform([entry], Settings.from_env(), tmp_path, tmp_path, lambda _l: None, _runner)
    assert "exit 1" not in out[0]
    assert "daemon is not running" in out[0]


def test_a_silent_failure_still_reports_something(tmp_path: Path) -> None:
    from mosaera_api.setup.uninstall import perform

    entry = next(r for r in plan(Settings.from_env(), tmp_path) if r.key == "containers")
    out = perform(
        [entry], Settings.from_env(), tmp_path, tmp_path, lambda _l: None, lambda _a, _o: 1
    )
    assert "exit 1" in out[0]  # nothing was said; the status is all there is


def test_removing_configuration_does_not_retarget_the_steps_after_it(tmp_path: Path) -> None:
    """The project name lives in `.env`, and "Remove configuration" deletes `.env`.

    Resolved per command, every step after that one silently pointed at a project that does not
    exist — so `down --volumes` "succeeded" against nothing and reported done, while the real
    container and volume were still there. Seen live on a real teardown.
    """
    from mosaera_api.setup.uninstall import commands_for

    settings = Settings.from_env()
    # The project is passed in, resolved once, so a vanished `.env` cannot change it mid-run.
    for key in ("containers", "data"):
        argv = commands_for(key, settings, tmp_path, tmp_path, "resolved-up-front")[0]
        assert argv[argv.index("-p") + 1] == "resolved-up-front"


def test_done_is_a_checked_claim_not_a_zero_exit(tmp_path: Path) -> None:
    """A zero exit only says the command RAN. It said "done" for a teardown that removed nothing."""
    from unittest.mock import patch

    from mosaera_api.setup.uninstall import perform

    entry = next(r for r in plan(Settings.from_env(), tmp_path) if r.key == "containers")

    with patch(
        "mosaera_api.setup.uninstall._still_there", return_value="the container is still there"
    ):
        out = perform(
            [entry], Settings.from_env(), tmp_path, tmp_path, lambda _l: None, lambda _a, _o: 0
        )
    assert "done" not in out[0]
    assert "still there" in out[0]

    with patch("mosaera_api.setup.uninstall._still_there", return_value=""):
        out = perform(
            [entry], Settings.from_env(), tmp_path, tmp_path, lambda _l: None, lambda _a, _o: 0
        )
    assert out[0].endswith("done")


def test_the_named_volume_is_the_one_docker_volume_ls_shows(tmp_path: Path) -> None:
    """The row named the compose KEY (`mosaera-pgdata`), not the resolved name
    (`mosaera-5ac386_mosaera-pgdata`) — so an operator could not find on their own machine the
    thing the screen said it was about to erase. On the one row where that matters."""
    from unittest.mock import patch

    from mosaera_api.setup.uninstall import data_volume

    resolved = '{"volumes": {"mosaera-pgdata": {"name": "myinstall_mosaera-pgdata"}}}'
    with patch("mosaera_api.setup._uninstall_probe._compose_config", return_value=(0, resolved)):
        assert data_volume("docker", tmp_path) == "myinstall_mosaera-pgdata"


def test_an_unparseable_config_still_names_something(tmp_path: Path) -> None:
    """A row that names the volume imprecisely beats a row that names nothing at all, so the
    compose key remains the fallback — and a total failure degrades to the row without a name
    rather than to a crash."""
    from unittest.mock import patch

    from mosaera_api.setup.uninstall import data_volume

    calls = [(0, "not json at all"), (0, "mosaera-pgdata\n")]
    with patch("mosaera_api.setup._uninstall_probe._compose_config", side_effect=calls):
        assert data_volume("docker", tmp_path) == "mosaera-pgdata"

    with patch("mosaera_api.setup._uninstall_probe._compose_config", return_value=(-1, "")):
        assert data_volume("docker", tmp_path) == ""


def _remove_config(tmp_path: Path) -> list[str]:
    """Run just the "Remove configuration" row, with no daemon involved."""
    from mosaera_api.setup.uninstall import perform

    entry = next(r for r in plan(Settings.from_env(), tmp_path) if r.key == "config")
    return perform(
        [entry], Settings.from_env(), tmp_path, tmp_path, lambda _l: None, lambda _a, _o: 0
    )


def test_removing_configuration_keeps_what_the_wizard_never_wrote(tmp_path: Path) -> None:
    """It used to `unlink` both files whole. Neither is ours: `settings.json` is mostly the
    dashboard's — provider API keys, a GitLab token, role and model bindings, every operational knob
    the Settings page manages — and `.env` holds whatever the operator put beside our five lines.
    An uninstall removes what it installed; it does not carry those off with it.
    """
    import json

    (tmp_path / "settings.json").write_text(
        json.dumps(
            {
                "setup_installed": ["docker"],
                "setup_progress": {"step": "database"},
                "providers": {"anthropic": {"api_key": "sk-keep-me"}},
                "gitlab_token": "glpat-keep-me",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "# --- written by `mosaera-setup` ---\n"
        "COMPOSE_PROJECT_NAME=mosaera-abc123\n"
        "MOSAERA_DB_URL=postgresql://mosaera:pw@localhost:5432/mosaera\n"
        "MOSAERA_API_TOKEN=service-token\n"
        "\n"
        "# the operator's own, which they source from a shell\n"
        "export ANTHROPIC_API_KEY=sk-theirs\n",
        encoding="utf-8",
    )

    assert _remove_config(tmp_path)[0].endswith("done")

    kept = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert kept == {
        "providers": {"anthropic": {"api_key": "sk-keep-me"}},
        "gitlab_token": "glpat-keep-me",
    }

    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=sk-theirs" in env
    assert "export " in env  # and still sourceable, as it was
    assert "MOSAERA_API_TOKEN" not in env
    assert "COMPOSE_PROJECT_NAME" not in env
    assert "mosaera-setup" not in env  # our banner goes with our keys


def test_a_configuration_that_was_only_ever_ours_disappears(tmp_path: Path) -> None:
    """The other half of the same rule: an instance this wizard configured and nobody else touched
    must uninstall completely. A `.env` left behind as a husk reads as a removal that failed."""
    import json

    (tmp_path / "settings.json").write_text(
        json.dumps({"setup_installed": ["docker"], "setup_progress": {"step": "access"}}),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "# --- written by `mosaera-setup` ---\nCOMPOSE_PROJECT_NAME=mosaera-abc123\n",
        encoding="utf-8",
    )

    assert _remove_config(tmp_path)[0].endswith("done")
    assert not (tmp_path / "settings.json").exists()
    assert not (tmp_path / ".env").exists()


def test_an_unreadable_settings_file_is_left_exactly_as_it_is(tmp_path: Path) -> None:
    """Rewriting a file we cannot read is how a transient bad read becomes permanent loss — the
    lesson `settings_store.write_settings` already carries. The removal says it failed instead."""
    (tmp_path / "settings.json").write_text("{ half a file", encoding="utf-8")

    out = _remove_config(tmp_path)
    assert not out[0].endswith("done")
    assert (tmp_path / "settings.json").read_text(encoding="utf-8") == "{ half a file"


def test_uv_is_offered_only_when_the_installer_put_it_there(tmp_path: Path) -> None:
    """`install.sh` installs uv WITHOUT asking, because a script piped to a shell cannot ask
    (ADR-0117 §2). That is precisely why uninstall has to offer it back — and why it must not offer
    to remove a uv the operator installed themselves years ago."""
    from mosaera_api.setup.uninstall import plan, record_install

    settings = Settings.from_env()
    assert not [r for r in plan(settings, tmp_path, tmp_path) if r.key == "uv"]

    record_install(tmp_path, "uv")
    offered = [r for r in plan(settings, tmp_path, tmp_path) if r.key == "uv"]
    assert len(offered) == 1
    assert "other projects may also use it" in offered[0].detail


def test_removing_uv_deletes_two_named_files_and_nothing_else(monkeypatch, tmp_path: Path) -> None:
    """It deletes from the operator's HOME. Two explicit paths, at the destination `install.sh`
    passed the vendor installer — never a glob, never a directory."""
    from mosaera_api.setup.uninstall import commands_for

    monkeypatch.setenv("UV_INSTALL_DIR", str(tmp_path / "bin"))
    argv = commands_for("uv", Settings.from_env(), tmp_path, tmp_path)
    assert argv == [["rm", "-f", str(tmp_path / "bin" / "uv"), str(tmp_path / "bin" / "uvx")]]


def test_the_wizard_records_the_uv_the_installer_bootstrapped(monkeypatch, tmp_path: Path) -> None:
    """The hand-off itself: the shell states the fact, Python writes the record, so there is one
    writer of `setup_installed` and it is the module that owns that file's format."""
    from mosaera_api.setup.__main__ import _record_bootstrapped_uv
    from mosaera_api.setup.uninstall import installed_by_setup

    monkeypatch.delenv("MOSAERA_BOOTSTRAPPED_UV", raising=False)
    _record_bootstrapped_uv(tmp_path)
    assert "uv" not in installed_by_setup(tmp_path)

    monkeypatch.setenv("MOSAERA_BOOTSTRAPPED_UV", "0")  # uv was already here; we installed nothing
    _record_bootstrapped_uv(tmp_path)
    assert "uv" not in installed_by_setup(tmp_path)

    monkeypatch.setenv("MOSAERA_BOOTSTRAPPED_UV", "1")
    _record_bootstrapped_uv(tmp_path)
    assert "uv" in installed_by_setup(tmp_path)


def test_removing_mosaera_itself_is_offered_and_is_a_signal_not_a_command(tmp_path: Path) -> None:
    """The item that was always missing, and the reason it cannot be an ordinary row.

    "Stop and remove" used to leave the clone and its virtualenv — the largest single thing on
    disk — exactly where they were. It is offered now, and it is deliberately NOT a command:
    the process runs from the directory it removes, so `perform` records the intent and
    `__main__` execs a shell outside the tree once the terminal is restored.
    """
    row = next(r for r in plan(Settings.from_env(), tmp_path) if r.key == "install")
    assert row.destructive, "it takes the project data inside it"
    assert commands_for("install", Settings.from_env(), tmp_path, tmp_path) == []


def test_the_install_row_promises_on_exit_rather_than_claiming_done(tmp_path: Path) -> None:
    """An uninstall that says "removed" before removing anything is the failure this repo names
    everywhere else. The row reports what is actually true at that moment."""
    from mosaera_api.setup.uninstall import perform

    row = next(r for r in plan(Settings.from_env(), tmp_path) if r.key == "install")
    results = perform(
        [row], Settings.from_env(), tmp_path, tmp_path, lambda _l: None, lambda *_a, **_k: 0
    )
    assert "exits" in results[0], results[0]
    assert "removed as" in results[0]


def test_the_uv_cache_row_is_separate_named_and_sized(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """uv's caches are SHARED with every other uv project on the machine, so they get their own row
    carrying a measured size — never folded into "Remove uv", whose two binaries are ours alone."""
    from mosaera_api.setup import _uninstall_probe

    fake = tmp_path / "cache"
    (fake / "sub").mkdir(parents=True)
    (fake / "sub" / "blob").write_bytes(b"x" * 2048)
    monkeypatch.setattr(_uninstall_probe, "uv_shared_paths", lambda: [fake])
    monkeypatch.setattr(uninstall, "uv_shared_paths", lambda: [fake])

    record_install(tmp_path, "uv")
    rows = {r.key: r for r in plan(Settings.from_env(), tmp_path)}
    assert "uv_cache" in rows
    assert "KB" in rows["uv_cache"].label or "MB" in rows["uv_cache"].label
    assert rows["uv"].key == "uv", "the binaries stay their own row"


def test_colima_is_ours_to_remove_and_docker_config_is_not(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """ADR-0118 let the wizard install a container runtime. Without this it could not take one
    back: a Colima install is recorded as `prereq:docker`, and every `prereq:` key is handed to the
    operator with "run it yourself" — for a VM this wizard started, on a machine it chose it for."""
    monkeypatch.setattr(uninstall, "colima_profile_exists", lambda *a, **k: True)
    record_install(tmp_path, "docker")
    rows = {r.key: r for r in plan(Settings.from_env(), tmp_path)}
    assert "colima" in rows and "prereq:docker" not in rows

    argv = commands_for("colima", Settings.from_env(), tmp_path, tmp_path)
    flat = [" ".join(a) for a in argv]
    assert any("--data" in c and "--force" in c for c in flat), "default keeps images and volumes"
    # NEVER the whole of ~/.docker — it holds Desktop's config, the operator's contexts and other
    # tools' CLI plugins. Only the one symlink ADR-0118 created is ours.
    assert not any(c.rstrip("/").endswith(".docker") for c in flat)
    assert any("cli-plugins/docker-compose" in c for c in flat)


def test_every_env_key_the_wizard_writes_is_one_it_can_take_back() -> None:
    """A value this wizard chose is a value it has to be able to remove.

    `MOSAERA_DB_PORT` was missed when the port-conflict repair started writing it: an operator who
    moved the port once would have carried that number through every later install of theirs,
    including onto a machine where the original port was free all along.

    Asserted against the writers rather than a list someone remembered to update — a hand-kept
    list is exactly what went stale.
    """
    from pathlib import Path

    from mosaera_api.setup.uninstall import OUR_ENV_KEYS

    written: set[str] = set()
    setup_dir = Path(__file__).resolve().parents[2] / "api" / "mosaera_api" / "setup"
    for source in setup_dir.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        for key in re.findall(r'"(MOSAERA_[A-Z_]+|COMPOSE_PROJECT_NAME)"\s*:', text):
            written.add(key)

    # Keys the wizard READS but never writes are not its to remove.
    missing = {k for k in written if k not in OUR_ENV_KEYS}
    assert not missing, f"the wizard writes these to .env and cannot take them back: {missing}"


def _row(key: str, label: str = "x") -> Removable:
    return Removable(key=key, label=label, detail="", destructive=True)


def test_removing_the_install_without_the_data_names_the_volume_that_survives() -> None:
    """The row said "the machine is left as it was before the install command was run" while the
    Docker volume — on macOS, inside the Colima VM — stayed put. The next install adopted it and
    opened on `Accounts: 1`. Live macOS run, 2026-08-30."""
    offered = [_row("data"), _row("install")]
    note = survives([_row("install")], offered)
    assert "KEEPS the database volume" in note
    assert "Delete all project data" in note


def test_taking_both_leaves_nothing_to_warn_about() -> None:
    assert survives([_row("data"), _row("install")], [_row("data"), _row("install")]) == ""


def test_a_partial_removal_that_keeps_the_install_is_not_the_warned_case() -> None:
    """Keeping the installation keeps its database by definition — that is not a surprise."""
    assert survives([_row("containers")], [_row("data"), _row("install")]) == ""


def test_no_data_row_offered_means_no_claim_about_a_volume() -> None:
    """An external database has no bundled volume to survive, so the sentence would be false."""
    assert survives([_row("install")], [_row("install")]) == ""


def test_the_install_row_no_longer_claims_the_machine_is_restored() -> None:
    rows = {r.key: r for r in plan(Settings(), Path("/nonexistent"), Path("/nonexistent"))}
    assert "left as it was" not in rows["install"].detail
    assert "survives" in rows["install"].detail


def test_removing_the_key_while_keeping_the_data_says_what_that_costs() -> None:
    """ADR-0039: losing MOSAERA_SECRET_KEY means losing what it encrypted. Since ADR-0126 the
    wizard MINTS that key, so it is now the wizard's job to say so before taking it back while
    leaving the volume it decrypts."""
    offered = [_row("data"), _row("config"), _row("install")]
    note = survives([_row("config")], offered)
    assert "MOSAERA_SECRET_KEY" in note
    assert "cannot be read back" in note


def test_taking_the_data_too_strands_nothing() -> None:
    offered = [_row("data"), _row("config"), _row("install")]
    assert survives([_row("config"), _row("data")], offered) == ""


def test_the_secret_key_is_a_key_the_wizard_can_take_back() -> None:
    """The guard that caught this: anything written to .env must be removable."""
    from mosaera_api.setup._uninstall_probe import OUR_ENV_KEYS

    assert "MOSAERA_SECRET_KEY" in OUR_ENV_KEYS
    assert "MOSAERA_COOKIE_SECURE" in OUR_ENV_KEYS


def test_removing_the_install_implies_stopping_its_server() -> None:
    """The install directory holds `.mosaera/api.pid`, the only handle `our_pid` has on the running
    server. Removing one without the other orphans a process that no wizard can ever find again —
    it keeps port 8000, answers /healthz, and the next install concludes it is already serving.
    Stopping a server destroys nothing, so this is a precondition, not a pre-armed destructive row.
    """
    from mosaera_api.setup.uninstall_flow import _with_implied

    rows = [_row("server"), _row("config"), _row("install")]
    assert _with_implied(rows, {2}) == {0, 2}  # install ticked -> server comes along
    assert _with_implied(rows, {0, 2}) == {0, 2}  # already ticked -> unchanged
    assert _with_implied(rows, {1}) == {1}  # config alone -> untouched
    assert _with_implied([_row("config"), _row("install")], {1}) == {1}  # no server row to add


def test_a_verification_that_could_not_run_is_not_a_removal() -> None:
    """The quiet half of the uninstall's honesty. A non-zero exit from the CHECK means Docker did
    not answer — a stopped daemon, or a Colima VM slower than the 15s timeout — and reporting ""
    for that told the operator the volume was gone on the strength of a look that never happened.
    The removal COMMAND's own failure was already caught; this was not.
    """
    from mosaera_api.setup import uninstall as u

    calls: list[tuple[str, ...]] = []

    def _fake(_bin: str, *args: str) -> tuple[int, str]:
        calls.append(args)
        return 1, ""  # the check itself failed

    original = u._docker
    try:
        u._docker = _fake  # type: ignore[assignment]
        assert "could not verify" in u._still_there("data", "docker", "proj")
        assert "could not verify" in u._still_there("containers", "docker", "proj")
        u._docker = lambda _b, *a: (0, "")  # type: ignore[assignment,return-value]
        assert u._still_there("data", "docker", "proj") == ""  # checked, and gone
        u._docker = lambda _b, *a: (0, "vol-id\n")  # type: ignore[assignment,return-value]
        assert "still there" in u._still_there("data", "docker", "proj")
    finally:
        u._docker = original  # type: ignore[assignment]


def test_the_removed_screen_offers_an_independent_check() -> None:
    """Everything the removal screen lists is the wizard's account of its own work — the weakest
    evidence there is for "the machine is clean", and six controls in this repo have reported an
    outcome they never verified. The check is fetched over the network on purpose: the copy inside
    the installation went with it."""
    from mosaera_api.setup import screens

    body = screens.removed(["Remove Mosaera itself: removed as this wizard exits"]).body
    assert "residue-check.sh" in body
    assert "raw.githubusercontent.com/Mosaera/core" in body


def test_the_uninstall_is_one_question_with_everything_of_ours_selected() -> None:
    """It replaced a nine-row checklist that started EMPTY.

    Friction should match severity, and a checklist was friction without protection: it asked the
    operator to assemble the removal, and the obvious assembly was wrong — every destructive row
    arrived unticked, so ticking only "Remove Mosaera itself" left the database volume AND the
    running server behind while the screen reported a clean removal. Both were reported live.
    """
    from mosaera_api.setup.uninstall_flow import _SHARED

    rows = [_row("server"), _row("data"), _row("install"), _row("uv_cache")]
    chosen = {i for i, r in enumerate(rows) if r.key not in _SHARED}
    assert chosen == {0, 1, 2}, "everything of ours is selected without the operator assembling it"


def test_shared_artefacts_are_never_selected_and_are_named_instead() -> None:
    """ADR-0119 §3: uv's caches belong to every other uv project on this machine, so an uninstall
    that took them would be the worse failure. §5: saying nothing about them is the other way to
    get it wrong — they leave the SELECTION, not the SCREEN."""
    from mosaera_api.setup.uninstall_flow import _SHARED

    assert "uv_cache" in _SHARED
    assert "data" not in _SHARED and "install" not in _SHARED


def test_the_confirm_screen_shows_what_goes_and_what_stays() -> None:
    from mosaera_api.setup import screens

    s = screens.uninstall_confirm("  ! Delete all project data", "Left in place: uv caches", 3)
    assert s.title.endswith("?"), "a question, per the destructive-action guidance"
    assert s.choices[0] == "Cancel", "the cursor rests on the option that changes nothing"
    assert "Delete all project data" in s.table
    assert "Left in place" in s.body
