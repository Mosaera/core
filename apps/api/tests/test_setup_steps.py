"""The wizard's decisions, tested without a terminal.

The screens render these; they do not decide them. That separation is what lets the flow be verified
in CI, where there is no tty at all.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from mosaera_api.setup.env_file import read_env_file
from mosaera_api.setup.steps import (
    Image,
    access_env,
    build_image_argv,
    compose_up_argv,
    database_port,
    database_url,
    public_bind_blocked_by,
    run_streaming,
)
from mosaera_core.config import Settings

# S104 is about a SERVER choosing to listen everywhere. Here it is only the string under test.
_PUBLIC = "0.0.0.0"  # noqa: S104


def test_a_public_bind_always_carries_a_token() -> None:
    """`guard_bind` refuses to start on a public bind with no token, so the wizard may not write
    that pair."""
    env = access_env(public=True, port=8000, current={}, make_token=lambda: "tok")
    assert env["MOSAERA_API_HOST"] == "0.0.0.0"  # noqa: S104 — asserting the value
    assert env["MOSAERA_API_TOKEN"] == "tok"


def test_an_existing_token_is_kept_not_reminted() -> None:
    """The destructive re-run. Minting a fresh token on every run rewrote the live one and
    invalidated every credential already issued to a client — while the screen called it success."""
    minted = []

    def _mint() -> str:
        minted.append(1)
        return "new"

    env = access_env(
        public=True,
        port=8000,
        current={
            "MOSAERA_API_HOST": _PUBLIC,
            "MOSAERA_API_PORT": "8000",
            "MOSAERA_API_TOKEN": "live",
            # A fully-configured exposed instance, which since #123/#124 means these too — a
            # `current` missing them is not "already configured", it is the state the guard
            # refuses, and the assertion below would be about the wrong thing.
            "MOSAERA_SECRET_KEY": "k" * 44,
            "MOSAERA_COOKIE_SECURE": "0",
        },
        make_token=_mint,
        make_secret_key=lambda: "SHOULD-NOT-BE-CALLED",
    )
    assert env == {}  # nothing to change, so nothing is written
    assert minted == []  # and no token was even generated


def test_an_exposed_bind_is_given_a_key_and_a_declared_posture() -> None:
    """#123/#124 from the wizard's side. `guard_bind` refuses an exposed bind with neither, so
    writing one without them would hand the operator a configuration the server will not boot on
    — the exact failure `public_bind_blocked_by` exists to prevent, one clause later."""
    env = access_env(
        public=True,
        secure=False,
        port=8000,
        current={"MOSAERA_API_HOST": _PUBLIC, "MOSAERA_API_PORT": "8000", "MOSAERA_API_TOKEN": "t"},
        make_token=lambda: "unused",
        make_secret_key=lambda: "generated-key",
    )
    assert env["MOSAERA_SECRET_KEY"] == "generated-key"
    assert env["MOSAERA_COOKIE_SECURE"] == "0"


def test_the_https_answer_is_the_operators_and_is_carried_through() -> None:
    env = access_env(
        public=True,
        secure=True,
        port=8000,
        current={"MOSAERA_API_TOKEN": "t", "MOSAERA_SECRET_KEY": "k" * 44},
        make_token=lambda: "unused",
        make_secret_key=lambda: "unused",
    )
    assert env["MOSAERA_COOKIE_SECURE"] == "1"


def test_an_existing_secret_key_is_never_replaced() -> None:
    """Replacing it would strand every secret already encrypted under the old one — ADR-0039
    names losing the key as exactly the cost of at-rest encryption."""
    env = access_env(
        public=True,
        port=8000,
        current={
            "MOSAERA_API_TOKEN": "t",
            "MOSAERA_SECRET_KEY": "original",
            "MOSAERA_COOKIE_SECURE": "0",
        },
        make_token=lambda: "unused",
        make_secret_key=lambda: "REPLACEMENT",
    )
    assert "MOSAERA_SECRET_KEY" not in env


def test_a_loopback_bind_is_left_alone() -> None:
    """ADR-0039's zero-config posture is preserved for the box it was reasoned about: the private
    default asks nothing of the operator and writes no key."""
    env = access_env(
        public=False,
        port=8000,
        current={"MOSAERA_API_HOST": "127.0.0.1", "MOSAERA_API_PORT": "8000"},
        make_token=lambda: "unused",
        make_secret_key=lambda: "unused",
    )
    assert "MOSAERA_SECRET_KEY" not in env
    assert "MOSAERA_COOKIE_SECURE" not in env


def test_choosing_loopback_clears_a_stale_token() -> None:
    # It used to leave the old token active while the screen said "this machine only".
    env = access_env(
        public=False, port=8000, current={"MOSAERA_API_TOKEN": "live"}, make_token=lambda: "new"
    )
    assert env["MOSAERA_API_TOKEN"] == ""


def test_a_hand_set_port_is_not_overwritten_with_a_matching_one() -> None:
    env = access_env(
        public=False, port=9000, current={"MOSAERA_API_PORT": "9000"}, make_token=lambda: "t"
    )
    assert "MOSAERA_API_PORT" not in env


def test_a_public_bind_is_refused_on_the_subprocess_sandbox() -> None:
    """The other half of `guard_bind`. Writing this pair produces an instance that SystemExits at
    boot — the wizard checked only the token half."""
    import dataclasses

    from mosaera_core.config import Settings

    settings = Settings.from_env()
    assert public_bind_blocked_by(dataclasses.replace(settings, sandbox_backend="docker")) == ""
    blocked = public_bind_blocked_by(dataclasses.replace(settings, sandbox_backend="subprocess"))
    assert "may not be exposed" in blocked


def test_the_database_url_follows_the_configured_port() -> None:
    """`MOSAERA_DB_PORT` drives BOTH the published port and the DSN. The wizard hardcoded 5432 on
    both sides, so an operator who moved the port got Postgres on one number and a wizard watching
    another, forever."""
    assert database_port({"MOSAERA_DB_PORT": "5544"}) == 5544
    assert database_port({}) == 5432
    assert database_port({"MOSAERA_DB_PORT": "nonsense"}) == 5432  # never crash on a typo
    assert database_url(5544) == "postgresql://mosaera:mosaera@localhost:5544/mosaera"


def test_compose_waits_for_the_database_to_be_healthy() -> None:
    # Without --wait, `up -d` returns as soon as the container exists, the next connection is
    # refused, and a correct install reports a database failure on its first run.
    from mosaera_core.config import Settings

    assert "--wait" in compose_up_argv(Settings.from_env())


class TestTheRunnerNeverTakesTheWizardDownWithIt:
    """None of these had a test; `run_streaming` was never executed by one."""

    def test_a_missing_binary_is_a_status_not_an_exception(self) -> None:
        out: list[str] = []
        assert run_streaming(["/nonexistent/binary"], out.append) == -1
        assert out  # and the reason is reported, not swallowed

    def test_a_nonzero_exit_is_returned(self) -> None:
        assert run_streaming(["sh", "-c", "exit 3"], lambda _l: None) == 3

    def test_a_SILENT_hang_still_times_out(self) -> None:
        # The subtle one: iterating the pipe blocks until a newline, so a command that prints
        # nothing never reached the deadline check.
        assert run_streaming(["sh", "-c", "sleep 30"], lambda _l: None, timeout=1) == -2

    def test_it_can_be_cancelled(self) -> None:
        assert (
            run_streaming(["sh", "-c", "sleep 30"], lambda _l: None, should_cancel=lambda: True)
            == -3
        )

    def test_stdin_is_closed_so_a_password_prompt_cannot_deadlock(self) -> None:
        # Inherited stdin let `sudo` prompt on a terminal Textual owns in raw mode: invisible,
        # unanswerable, wedged forever. Privileged commands go through App.suspend() instead.
        assert run_streaming(["sh", "-c", "read x; echo got"], lambda _l: None, timeout=5) == 0


def test_an_image_build_is_argv_never_a_shell_string() -> None:
    settings = Settings.from_env()
    argv = build_image_argv(
        settings, Image("mosaera-sandbox:dev", "infra/docker/sandbox.Dockerfile", False)
    )
    from mosaera_api.setup.images import RECIPE_LABEL, recipe_hash

    assert argv[1:] == [
        "build",
        "-f",
        "infra/docker/sandbox.Dockerfile",
        "-t",
        "mosaera-sandbox:dev",
        # The recipe's hash, stamped so freshness can be judged from CONTENT. Judging it from
        # clocks did not work: `git pull` rewrites mtimes, so every image looked stale, the wizard
        # rebuilt, docker served the build from cache in under a second, and a cached rebuild
        # leaves `.Created` untouched — the image stayed stale and was offered again, forever.
        "--label",
        f"{RECIPE_LABEL}={recipe_hash('infra/docker/sandbox.Dockerfile')}",
        ".",
    ]
    assert all(isinstance(part, str) and " " not in part for part in argv[1:])


class TestTheDatabaseStepIsOneDecision:
    """The step offers two rows, always, whatever is wrong.

    It used to offer up to three — create the database, use the bundled one, start the bundled
    Postgres — chosen by which way the connection had failed. Those are not three choices, they are
    three PHASES of one job, and exposing them made the operator diagnose a database in order to be
    allowed to have one. Worse, the set was conditional, so one state offered a single action that
    could not work: Postgres running, database absent, and the only row said "start Postgres".
    """

    def _screen(self, *, missing_db: bool, declared: bool, reason: str = ""):
        from mosaera_api.setup import screens
        from mosaera_api.setup.steps import DatabaseState

        state = DatabaseState(False, missing_db, declared, reason, "mosaera_try")
        return screens.database(state, 5432)

    def test_the_same_two_rows_in_every_state(self) -> None:
        from mosaera_api.setup import screens

        for missing_db in (True, False):
            for declared in (True, False):
                got = self._screen(missing_db=missing_db, declared=declared)
                assert got.choices == [screens.USE_BUNDLED, screens.POINT_ELSEWHERE], (
                    missing_db,
                    declared,
                )

    def test_the_supported_engine_is_stated(self) -> None:
        # Otherwise "enter a different database URL" invites a MySQL DSN and a puzzling refusal.
        assert (
            "PostgreSQL is the only supported engine"
            in self._screen(missing_db=False, declared=False).body
        )

    def test_the_url_shown_carries_no_password(self) -> None:
        from mosaera_api.setup import screens
        from mosaera_api.setup.steps import DatabaseState, redact

        state = DatabaseState(
            False, False, True, "refused", "mosaera", redact("postgresql://u:hunter2@h:5432/m")
        )
        assert "hunter2" not in screens.database(state, 5432).body

    def test_the_body_is_a_sentence_not_a_driver_dump(self) -> None:
        raw = 'connection failed: FATAL:  database "mosaera_try" does not exist\nMultiple attempts'
        got = self._screen(missing_db=True, declared=True, reason=raw)
        assert 'The database "mosaera_try" does not exist' in got.body
        assert "Multiple attempts" not in got.body
        # AND NOT UNDER IT EITHER, once the failure is recognised. The sentence above is a faithful
        # translation of that line, so the raw text adds only alarm — a truncated
        # `OperationalError: (psycopg.OperationalError) connection failed: connection to serve…`
        # under "nothing is listening on that address" reads as a second, worse problem.
        assert got.detail == ""

    def test_an_unrecognised_failure_keeps_its_raw_text(self) -> None:
        """The other half of the same rule: where this wizard cannot translate the cause, the
        original IS the best account of it and hiding it would leave the operator with nothing."""
        got = self._screen(
            missing_db=False, declared=True, reason="glorp: the flux capacitor said no"
        )
        assert "flux capacitor" in got.detail

    def test_a_first_run_is_not_reported_as_a_failure(self) -> None:
        """Nothing is listening on 5432 on a machine where nothing has been set up yet. Reporting
        that as an error told the operator their brand-new installation was already broken."""
        got = self._screen(missing_db=False, declared=False, reason="connection refused")
        assert "No database yet" in got.body
        assert got.detail == ""
        assert "Nothing is listening" not in got.body


class TestTheAccessScreenNamesItsAddresses:
    def test_each_option_shows_where_it_binds(self) -> None:
        from mosaera_api.setup import screens

        got = screens.access(public_now=False, blocked="", port=8123, lan="192.168.1.5")
        assert any("127.0.0.1:8123" in c for c in got.choices)
        assert any("192.168.1.5:8123" in c for c in got.choices)

    def test_a_blocked_instance_is_not_offered_the_network(self) -> None:
        from mosaera_api.setup import screens

        got = screens.access(public_now=False, blocked="the subprocess sandbox", port=8000, lan="x")
        assert len(got.choices) == 1

    def test_the_address_falls_back_rather_than_inventing_one(self) -> None:
        from unittest.mock import patch

        from mosaera_api.setup.steps import lan_address

        with patch("socket.socket") as sock:
            sock.return_value.connect.side_effect = OSError("no route")
            assert "invent" not in lan_address()
            assert lan_address()  # never empty


class TestADeploymentIsScopedToItsDirectory:
    """The property a server with several Postgres containers depends on.

    Compose derives the project from the compose file's own parent directory — `infra/docker` — so
    every checkout on a machine resolved to the same project, the same container and the same
    volume. A `down --volumes` from a scratch clone erased the real install's database. Passing
    `--project-directory` makes the INSTALL DIRECTORY the identity, so each deployment owns exactly
    the resources carrying its own prefix and can neither see nor remove another's.
    """

    def test_bring_up_names_the_install_directory(self) -> None:
        from mosaera_core.config import Settings

        argv = compose_up_argv(Settings.from_env(), Path("/srv/mosaera-a"))
        assert "--project-directory" in argv
        assert argv[argv.index("--project-directory") + 1] == "/srv/mosaera-a"
        # ...and it comes BEFORE `-f`, which is where compose accepts it.
        assert argv.index("--project-directory") < argv.index("-f")

    def test_two_installs_do_not_share_an_argv(self) -> None:
        from mosaera_core.config import Settings

        s = Settings.from_env()
        assert compose_up_argv(s, Path("/srv/a")) != compose_up_argv(s, Path("/srv/b"))

    def test_teardown_is_scoped_too(self) -> None:
        """The dangerous half. `down --volumes` unscoped is what destroys somebody else's data."""
        from mosaera_api.setup.uninstall import commands_for
        from mosaera_core.config import Settings

        for key in ("containers", "data"):
            argv = commands_for(key, Settings.from_env(), Path("/home"), Path("/srv/mine"))[0]
            assert "--project-directory" in argv
            assert argv[argv.index("--project-directory") + 1] == "/srv/mine"

    def test_nothing_in_the_compose_file_is_named_absolutely(self) -> None:
        """An explicit `name:`, `container_name:` or volume `name:` ignores the project entirely —
        which would defeat the scoping above no matter what the callers pass."""
        text = (
            Path(__file__).resolve().parents[3] / "infra" / "docker" / "compose.yaml"
        ).read_text()
        code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
        assert "container_name:" not in code
        assert not any(ln.startswith("name:") for ln in code.splitlines())
        assert "name: docker_" not in code


class TestItCanOnlyEverTargetItsOwnInstall:
    """Red-team: moving the installer somewhere else must not let it reach another service.

    Three attacks were run against the live daemon before these were written. One was already safe;
    two were breaches and are fixed here.
    """

    def test_an_ambient_project_name_cannot_retarget_the_teardown(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """BREACH, demonstrated: `COMPOSE_PROJECT_NAME` exported in a shell outranks every value
        Compose reads from a file, so a leftover export — mine was `mosaera-stress` for an hour —
        pointed `down --volumes` at a different project entirely.

        `-p` is the only precedence level above it, and its value comes from the install's own
        `.env`, never from the environment.
        """
        from mosaera_api.setup.steps import compose_argv, compose_project

        (tmp_path / ".env").write_text("COMPOSE_PROJECT_NAME=mine\n")
        monkeypatch.setenv("COMPOSE_PROJECT_NAME", "somebody-elses-project")

        assert compose_project(tmp_path) == "mine"
        argv = compose_argv("docker", tmp_path, "down", "--volumes")
        assert argv[argv.index("-p") + 1] == "mine"
        assert "somebody-elses-project" not in argv

    def test_two_installs_sharing_a_directory_name_are_still_separate(self, tmp_path: Path) -> None:
        """Deriving from the basename alone collides: /srv/a/mosaera and /srv/b/mosaera would own
        the same container, network and volume. The digest is of the real path."""
        from mosaera_api.setup.steps import compose_project

        a = tmp_path / "a" / "mosaera"
        b = tmp_path / "b" / "mosaera"
        a.mkdir(parents=True)
        b.mkdir(parents=True)
        assert compose_project(a) != compose_project(b)
        assert compose_project(a).startswith("mosaera-")

    def test_a_recorded_project_is_never_silently_changed(self, tmp_path: Path) -> None:
        """An install that already knows which project owns its data keeps it."""
        from mosaera_api.setup.steps import ensure_compose_project

        (tmp_path / ".env").write_text("COMPOSE_PROJECT_NAME=legacy\n")
        assert ensure_compose_project(tmp_path) == "legacy"
        assert "legacy" in (tmp_path / ".env").read_text()

    def test_a_pid_file_is_not_proof_that_a_process_is_ours(self, tmp_path: Path) -> None:
        """BREACH, demonstrated: `api.pid` is an integer in a file, so a stale entry after a reboot
        — or a hand-edited one — named an unrelated process, and `stop` SIGTERMed it and reported
        success. A `sleep 900` was killed this way.

        The number is now checked against the process it names.
        """
        import os

        from mosaera_api.setup.launch import PID_NAME, our_pid

        # This very test process: alive, signallable, and emphatically not `mosaera-api`.
        (tmp_path / PID_NAME).write_text(str(os.getpid()))
        assert our_pid(tmp_path) == 0
        assert our_pid(tmp_path, tmp_path) == 0

        for junk in ("1", "0", "-5", "not-a-number", ""):
            (tmp_path / PID_NAME).write_text(junk)
            assert our_pid(tmp_path, tmp_path) == 0, junk


def test_a_fresh_install_is_given_a_key_to_encrypt_with(tmp_path: Path) -> None:
    """ADR-0126. ADR-0039 rejected a MANDATORY key because it would break existing installs and
    force key management on operators; a minted one does neither, and the population it reasoned
    about — "the trusted single-tenant box" — stopped describing who installs this."""
    from mosaera_api.setup.enter_steps import ensure_secret_key

    (tmp_path / ".env").write_text("MOSAERA_DB_URL=postgresql://x\n", encoding="utf-8")
    app = SimpleNamespace(repo_root=tmp_path)
    assert ensure_secret_key(app) is True  # type: ignore[arg-type]
    key = read_env_file(tmp_path / ".env")["MOSAERA_SECRET_KEY"]
    Fernet(key.encode())  # a real Fernet key, not a plausible-looking string


def test_an_existing_key_is_never_reminted(tmp_path: Path) -> None:
    """Reminting would strand every secret already encrypted under the old key."""
    from mosaera_api.setup.enter_steps import ensure_secret_key

    (tmp_path / ".env").write_text("MOSAERA_SECRET_KEY=original\n", encoding="utf-8")
    app = SimpleNamespace(repo_root=tmp_path)
    assert ensure_secret_key(app) is False  # type: ignore[arg-type]
    assert read_env_file(tmp_path / ".env")["MOSAERA_SECRET_KEY"] == "original"


def test_a_bind_is_not_offered_when_the_key_cannot_encrypt() -> None:
    """Red-team round 3, same class as the guard's own finding: PRESENCE is not USABILITY.

    `access_env` mints only when a key is ABSENT — correctly, since replacing one strands what it
    encrypted — so a present-but-unusable value would be offered a network bind, told it worked,
    and then meet a server that refuses to start. This function exists to prevent exactly that.
    """
    s = Settings()
    assert public_bind_blocked_by(s, {}) == ""
    assert public_bind_blocked_by(s, {"MOSAERA_SECRET_KEY": Fernet.generate_key().decode()}) == ""
    assert "not a valid Fernet key" in public_bind_blocked_by(s, {"MOSAERA_SECRET_KEY": "junk"})


def test_an_unreadable_tls_declaration_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Red-team round 3. `on` and `secure` passed the #124 clause and silently meant OFF — the
    declaration control accepting an answer it cannot read, which is worse than no answer because
    the operator believes they gave one."""
    from mosaera_api.__main__ import guard_bind

    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())
    for unreadable in ("on", "secure", "maybe", ""):
        monkeypatch.setenv("MOSAERA_COOKIE_SECURE", unreadable)
        with pytest.raises(SystemExit, match="readable TLS posture"):
            guard_bind("0.0.0.0", "tok")  # noqa: S104
    for readable in ("0", "1", "TRUE", "no"):
        monkeypatch.setenv("MOSAERA_COOKIE_SECURE", readable)
        guard_bind("0.0.0.0", "tok")  # noqa: S104


def test_a_key_that_could_not_be_written_is_not_silence(tmp_path: Path) -> None:
    """`return False` meant BOTH "already had a key" and "could not write one". On a read-only
    `.env` the instance then stored credentials in plaintext while ADR-0126 states every install
    encrypts at rest — and nothing on screen differed."""
    import os

    from mosaera_api.setup.enter_steps import ensure_secret_key

    # ROOT DEFEATS THE ARRANGEMENT, not the code. `chmod 0o500` does not stop uid 0 writing, so as
    # root (CI runs as root in a container) the key IS written, `ensure_secret_key` correctly
    # returns True, and the read-only case this test exists for never happens. There is no
    # portable way to build an unwritable directory for root, so the honest move is to say the
    # test could not be set up rather than assert against a situation that was never created.
    if getattr(os, "geteuid", lambda: 1)() == 0:
        pytest.skip("running as root: a read-only directory cannot be arranged")

    env = tmp_path / ".env"
    env.write_text("MOSAERA_DB_URL=x\n", encoding="utf-8")
    os.chmod(tmp_path, 0o500)  # cannot replace the file in a read-only directory
    app = SimpleNamespace(repo_root=tmp_path, _access_note="")
    try:
        assert ensure_secret_key(app) is False  # type: ignore[arg-type]
        assert "plaintext" in app._access_note
    finally:
        os.chmod(tmp_path, 0o700)


# --------------------------------------------- freshness is CONTENT, because clocks did not work


def test_a_cached_rebuild_can_clear_the_staleness_it_is_asked_to_clear(tmp_path: Path) -> None:
    """The loop this replaced. Freshness was `.Created` vs the Dockerfile's mtime, and `git pull`
    rewrites mtimes — so every image looked stale, the wizard rebuilt, DOCKER SERVED THE BUILD FROM
    CACHE IN UNDER A SECOND, and a cached rebuild leaves `.Created` exactly as it was. Still stale,
    offered again, forever. Reported as "two said they were built in under one second" and "it
    still says two sandboxes need building"; measured at 910ms with `.Created` unchanged.

    A label is part of the image config, so a rebuild that changes it produces a different image
    even when every layer is cached. The thing compared is the thing the build writes.
    """
    from mosaera_api.setup.images import _image_is_stale, recipe_hash

    recipe = tmp_path / "T.Dockerfile"
    recipe.write_text("FROM alpine:3\n", encoding="utf-8")
    stamped = recipe_hash(str(recipe))

    assert _image_is_stale("<no value>", str(recipe)), "an unlabelled image cannot be judged fresh"
    assert not _image_is_stale(stamped, str(recipe)), "and a rebuild CLEARS it — the loop is gone"

    recipe.write_text("FROM alpine:3\nRUN echo changed\n", encoding="utf-8")
    assert _image_is_stale(stamped, str(recipe)), "a changed recipe is stale again"


def test_touching_the_recipe_without_changing_it_is_not_staleness(tmp_path: Path) -> None:
    """`git pull` rewrites the mtime of files it did not change. That is exactly the case the old
    check called stale, and the case this one must not."""
    import os

    from mosaera_api.setup.images import _image_is_stale, recipe_hash

    recipe = tmp_path / "T.Dockerfile"
    recipe.write_text("FROM alpine:3\n", encoding="utf-8")
    stamped = recipe_hash(str(recipe))
    os.utime(recipe, (2_100_000_000, 2_100_000_000))  # far newer than any image
    assert not _image_is_stale(stamped, str(recipe))


def test_an_unreadable_recipe_does_not_force_a_rebuild(tmp_path: Path) -> None:
    """Rebuilding on a guess costs minutes and proves nothing."""
    from mosaera_api.setup.images import _image_is_stale

    assert not _image_is_stale("anything", str(tmp_path / "missing.Dockerfile"))
