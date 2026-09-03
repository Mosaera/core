"""`scripts/install.sh`, driven against a real git remote.

WHY THIS EXISTS. The installer had never been executed by a test, and it shipped three defects that
each made a clean machine unreachable — the worst being that it ended with `uv run --no-sync
mosaera-setup` and never ran `uv sync`, so every fresh clone died as `error: Failed to spawn:
mosaera-setup`. A script nothing runs is a script nobody checks.

WHAT IS REAL AND WHAT IS NOT. The git remote is real: a bare repository with real tags, cloned over
`file://`, so tag resolution, detached checkout, re-runs and the dirty-tree refusal are exercised
against git itself rather than against a description of git. Exactly one command is stubbed — `uv`,
which records its argv — because the question these tests answer is *what the script does and in
what order*, and a real `uv sync` would add minutes, a network, and a dependency tree to every run
without changing the answer.

WHAT THIS DELIBERATELY DOES NOT COVER: that the vendor uv installer works, that `uv sync` succeeds
on a foreign distribution, and that the wizard then completes. Those are environment claims, and
ADR-0110's rule applies — they are closed by the VM matrix and the fresh-machine install, not here.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "install.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None,
    reason="needs git and bash",
)


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(  # noqa: S603 — a fixed argv of test-authored arguments
        ["git", *args],  # noqa: S607 — git from PATH is the point; this drives the real thing
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env=_GIT_ENV,
    )
    return proc.stdout.strip()


#: A hermetic git: no user config, no signing, no `init.defaultBranch` surprise from the host.
_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A bare remote with two releases, so "move to the newer tag" has somewhere to move."""
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "--quiet", "--initial-branch=main")
    (work / ".env.example").write_text("MOSAERA_EXAMPLE=1\n", encoding="utf-8")
    (work / "marker.txt").write_text("v0.1.0\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "--quiet", "-m", "first")
    _git(work, "tag", "v0.1.0")
    (work / "marker.txt").write_text("v0.2.0\n", encoding="utf-8")
    _git(work, "commit", "--quiet", "-am", "second")
    _git(work, "tag", "v0.2.0")
    # A tag that sorts above v0.2.0 lexically but below it by version, so `--sort=-v:refname`
    # is doing real work rather than accidentally agreeing with a string sort.
    _git(work, "tag", "v0.10.0")
    (work / "marker.txt").write_text("v0.10.0\n", encoding="utf-8")
    _git(work, "commit", "--quiet", "-am", "third")
    _git(work, "tag", "--force", "v0.10.0")

    bare = tmp_path / "remote.git"
    _git(tmp_path, "clone", "--quiet", "--bare", str(work), str(bare))
    return bare


class Run:
    """One invocation of the installer, and everything it left behind."""

    def __init__(self, proc: subprocess.CompletedProcess[str], install_dir: Path, uv_log: Path):
        self.proc = proc
        self.install_dir = install_dir
        self.output = proc.stdout + proc.stderr
        self.uv_calls = (
            [line for line in uv_log.read_text(encoding="utf-8").splitlines() if line]
            if uv_log.exists()
            else []
        )

    @property
    def head(self) -> str:
        return _git(self.install_dir, "describe", "--tags", "--exact-match")


@pytest.fixture
def install(tmp_path: Path, remote: Path):
    """Run the installer with a stub `uv` on PATH, and a HOME that is not the operator's."""
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    install_dir = tmp_path / "install"
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    uv_log = tmp_path / "uv-calls.log"

    uv = stub_dir / "uv"
    uv.write_text(
        f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> {uv_log}\nexit 0\n', encoding="utf-8"
    )
    uv.chmod(0o755)

    def _run(*, with_uv: bool = True, args: list[str] | None = None, **env: str) -> Run:
        # Without the stub, a PATH that has git and bash and emphatically NOT the developer's own
        # uv — otherwise "no uv on this machine" is untestable on a machine that has one.
        path = os.environ["PATH"] if with_uv else "/usr/bin:/bin"
        proc = subprocess.run(  # noqa: S603 — running the repo's own script, by design
            ["bash", str(SCRIPT), *(args or [])],  # noqa: S607 — the repo's own script
            capture_output=True,
            text=True,
            check=False,
            env={
                **_GIT_ENV,
                "HOME": str(home),
                "PATH": f"{stub_dir}:{path}" if with_uv else path,
                "MOSAERA_REPO_URL": f"file://{remote}",
                "MOSAERA_INSTALL_DIR": str(install_dir),
                "MOSAERA_NO_SETUP": "1",
                # EXPLICIT. These tests inherit pytest's controlling terminal, so `/dev/tty` is
                # readable and the destination prompt would block them forever. The prompt has its
                # own test, driven through a real pty; here it is answered up front.
                "MOSAERA_YES": "1",
                **env,
            },
        )
        return Run(proc, install_dir, uv_log)

    _run.install_dir = install_dir  # type: ignore[attr-defined]
    return _run


# --- the bug this file was written for ----------------------------------------------------------


def test_the_environment_is_built_before_anything_is_run_in_it(install) -> None:
    """THE regression. `uv run --no-sync` with no prior `uv sync` is a spawn error on every fresh
    clone, and it presented as "Failed to spawn: mosaera-setup" — a build failure wearing the mask
    of a missing program."""
    run = install()
    assert run.proc.returncode == 0, run.output
    assert run.uv_calls, "the installer never called uv at all"
    assert run.uv_calls[0].startswith("sync"), run.uv_calls
    assert (run.install_dir / ".env").is_file()


def test_a_run_with_no_terminal_is_a_success_not_a_degraded_one(install) -> None:
    """CI, a container build, a cron. The wizard was never promised without a terminal, and the
    installation it leaves behind is complete."""
    run = install()
    assert run.proc.returncode == 0
    assert "uv run mosaera-setup" in run.output


# --- what gets installed ------------------------------------------------------------------------


def test_it_installs_the_newest_release_not_the_newest_string(install) -> None:
    """`v0.10.0` sorts BELOW `v0.2.0` as a string. `sort -V` would get this right too and is GNU
    coreutils, which macOS does not have — hence git's own `--sort=-v:refname`."""
    run = install()
    assert run.head == "v0.10.0", run.output


def test_a_pinned_ref_wins(install) -> None:
    assert install(MOSAERA_REF="v0.1.0").head == "v0.1.0"


def test_a_branch_can_be_tracked_and_says_it_is_not_a_release(install) -> None:
    """The shape the pre-release stranger test uses."""
    run = install(MOSAERA_BRANCH="main")
    assert run.proc.returncode == 0
    assert "not a release" in run.output


def test_re_running_changes_nothing(install) -> None:
    first = install()
    second = install()
    assert second.proc.returncode == 0
    assert "already at v0.10.0" in second.output
    assert second.head == first.head


def test_an_older_install_moves_up_to_the_newest_release(install) -> None:
    install(MOSAERA_REF="v0.1.0")
    moved = install()
    assert moved.head == "v0.10.0"
    assert "now at v0.10.0" in moved.output


def test_uncommitted_work_is_never_moved(install) -> None:
    """Tag-pinning means a detached HEAD, so `merge --ff-only` is no longer the guard. A detached
    checkout cannot lose commits — a branch still points at them — but it can lose edits."""
    first = install(MOSAERA_REF="v0.1.0")
    (first.install_dir / "marker.txt").write_text("mine\n", encoding="utf-8")
    again = install()
    assert again.proc.returncode == 0
    assert again.head == "v0.1.0", "it moved an install with uncommitted changes"
    assert (first.install_dir / "marker.txt").read_text(encoding="utf-8") == "mine\n"
    assert "uncommitted changes" in again.output


def test_an_existing_env_is_never_overwritten(install) -> None:
    first = install()
    (first.install_dir / ".env").write_text("MOSAERA_MINE=1\n", encoding="utf-8")
    install()
    assert "MOSAERA_MINE=1" in (first.install_dir / ".env").read_text(encoding="utf-8")


# --- the two refusals -----------------------------------------------------------------------------


def test_the_uv_bootstrap_can_be_refused(install) -> None:
    """The opt-out ADR-0117 bounds the exception with. Without it there is no way to say no to the
    one thing this script installs."""
    run = install(with_uv=False, MOSAERA_NO_BOOTSTRAP="1")
    assert run.proc.returncode == 1
    assert "astral.sh" in run.output  # it still says how to do it yourself
    assert not run.uv_calls


def test_the_data_directory_is_not_mistaken_for_the_install_directory(tmp_path: Path) -> None:
    """`MOSAERA_HOME` is the application's DATA directory. An operator who set it and expected a
    clone target got their repository written into their data store."""
    proc = subprocess.run(  # noqa: S603 — running the repo's own script, by design
        ["bash", str(SCRIPT)],  # noqa: S607 — the repo's own script, run as an operator would
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "MOSAERA_HOME": str(tmp_path), "MOSAERA_NO_SETUP": "1"},
    )
    assert proc.returncode == 2
    assert "data directory" in proc.stdout + proc.stderr


def test_a_stray_untracked_file_does_not_freeze_the_install(install) -> None:
    """A plain `git status --porcelain` counts untracked files, and this script writes one itself
    (`.env`). With that as the guard, every re-run refused to update, forever, over a file the
    installer had created — so the check reads tracked changes only."""
    first = install(MOSAERA_REF="v0.1.0")
    (first.install_dir / "notes-to-self.txt").write_text("hello\n", encoding="utf-8")
    moved = install()
    assert moved.head == "v0.10.0", moved.output
    assert (first.install_dir / "notes-to-self.txt").is_file(), "git carries untracked files over"


def test_it_hands_over_to_the_wizard_rather_than_starting_a_server() -> None:
    """The path the whole terminal wizard was built to be the destination of.

    `install.sh` once ended with `exec make up`, naming `mosaera-setup` only in a comment, so
    `curl … | sh` started an API for an instance with no database and no account — a login form
    nobody could get past. The tty branch cannot be driven from pytest (there is no controlling
    terminal), so this reads the source; every other property of the hand-off is executed above.
    """
    body = SCRIPT.read_text(encoding="utf-8").split("hand_off() {")[1]
    code = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))
    assert "mosaera-setup" in code
    assert "make up" not in code, "starting the server is the wizard's last step, not this one's"
    # And the trick that makes it possible under `curl | sh`, where stdin is the script itself:
    # THE CHILD gets the terminal, and the script keeps its own fd 0.
    assert "< /dev/tty" in code, "the wizard needs a real stdin"
    assert "exec < /dev/tty" not in code, (
        "redirecting the SCRIPT's OWN fd 0 loses the rest of the script under `curl | sh` — bash "
        "reads a piped script FROM stdin, so everything after the redirect is read from the "
        "keyboard. That is the terminal that never came back, reported on every run, and this "
        "assertion previously pinned the broken idiom in place."
    )


def test_an_abandoned_wizard_is_told_how_to_get_back_in(install) -> None:
    """G3: the wizard exits non-zero when the operator leaves it unfinished (`app.py:96`), and
    under `set -euo pipefail` that used to kill the INSTALLER on the same line — the one thing an
    interactive abandon needed next, the re-entry command, printed only on the no-terminal branch.

    Same limits as the test above: the tty branch cannot be driven from pytest (no controlling
    terminal to hand `hand_off` — `MOSAERA_NO_SETUP=1` short-circuits it here too), so this reads
    the source rather than executing it, and pins the shape that keeps `set -e` from swallowing
    the failure: the subshell's exit status is captured explicitly (`|| code=$?`), never let the
    `if` after it die under `-e`, and the script still ends by passing that code through.
    """
    body = SCRIPT.read_text(encoding="utf-8").split("hand_off() {")[1].split("\n}\n")[0]
    code = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))
    # Captured, not left to `-e`: a bare `exec uv run … mosaera-setup` on a non-zero exit would
    # kill the whole installer right there, before any of the lines below ever ran.
    assert "|| code=$?" in code, "the wizard's exit status must be captured, not left to `set -e`"
    assert 'if [ "$code" -ne 0 ]; then' in code
    assert "Run setup again with:" in code
    assert "cd %q && uv run mosaera-setup" in code, "the re-entry command names the install dir"
    assert 'exit "$code"' in code, "the wizard's own exit status is passed through, not swallowed"
    # And exercised with a real install, confirming a bare, unguarded install run (no wizard
    # invoked — MOSAERA_NO_SETUP=1) still reaches the successful hand-off message unharmed.
    run = install()
    assert run.proc.returncode == 0
    assert "uv run mosaera-setup" in run.output


# --- the flagship pass: flags, and refusing to guess ---------------------------------------------


def test_help_answers_the_question_instead_of_installing(install) -> None:
    """`--help` used to fall straight through and perform a full install — several hundred
    megabytes for someone who asked what the options were."""
    run = install(args=["--help"])
    assert run.proc.returncode == 0
    assert "Options:" in run.proc.stdout
    assert not run.install_dir.exists(), "asking a question must not install anything"


def test_an_unknown_flag_is_refused_rather_than_ignored(install) -> None:
    """Silently ignoring an unrecognised flag and installing anyway is the same bug as `--help`
    installing: the operator asked for something specific and got something else."""
    run = install(args=["--definitely-not-a-flag"])
    assert run.proc.returncode == 2
    assert "unknown option" in run.proc.stderr
    assert "Options:" in run.proc.stderr, "say what the options ARE, not just that this is not one"
    assert not run.install_dir.exists()


def test_a_pin_that_does_not_exist_leaves_nothing_behind(install) -> None:
    """A clone we started and could not finish is ours to clean up.

    Pinning a missing ref cloned ~35 MB, failed at checkout, and left the directory with a `.git`
    in it and no mention — so the NEXT run took the update path over an install that had never
    succeeded.
    """
    run = install(MOSAERA_REF="v99.99.99")
    assert run.proc.returncode != 0
    assert "does not exist" in run.proc.stderr
    assert not run.install_dir.exists(), "a partial clone is not an install"


def test_an_existing_install_survives_a_bad_pin(install) -> None:
    """The cleanup must not reach an install that predates this run."""
    install()
    assert (install.install_dir / ".git").exists()  # type: ignore[attr-defined]
    run = install(MOSAERA_REF="v99.99.99")
    assert run.proc.returncode != 0
    assert run.install_dir.exists(), "someone else's install is not ours to remove"
    assert "untouched" in run.proc.stderr


def test_a_non_empty_destination_is_diagnosed_correctly(install) -> None:
    """It used to answer EVERY clone failure with "if the repository is private, set
    MOSAERA_REPO_URL to an authenticated remote" — sending the operator to fix authentication when
    the real cause was a directory that already had something in it."""
    install.install_dir.mkdir(parents=True)  # type: ignore[attr-defined]
    (install.install_dir / "theirs.txt").write_text("keep me")  # type: ignore[attr-defined]
    run = install()
    assert run.proc.returncode != 0
    assert "already exists and is not empty" in run.proc.stderr
    assert "authenticated remote" not in run.proc.stderr, "do not send them after the wrong cause"
    assert (install.install_dir / "theirs.txt").exists()  # type: ignore[attr-defined]


def test_the_bash_guard_precedes_the_option_it_protects() -> None:
    """`curl … | sh` runs this under /bin/sh — dash on Debian and Ubuntu — because a shebang is
    ignored when a script is piped. dash rejects `set -o pipefail`, so the guard is worthless
    unless it comes FIRST, and it must itself be POSIX to run at all.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    guard = text.index("BASH_VERSION")
    assert guard < text.index("set -euo pipefail"), "the guard must run before the option it saves"
    # CODE only. The comment above the guard discusses `[[` in order to say there is none, and a
    # check that reads its own prose is a check that fails on being explained.
    preamble = "\n".join(
        line for line in text[:guard].splitlines() if not line.strip().startswith("#")
    )
    for bashism in ("[[", "local ", "<<<"):
        assert bashism not in preamble, f"the guard's own preamble must be POSIX ({bashism})"


def test_the_vendor_fetches_are_transport_hardened() -> None:
    """A piped-to-shell install is trust-on-first-use either way (ADR-0117 records that), but
    refusing a redirect off HTTPS and refusing ancient TLS costs nothing, and is rustup's
    standard."""
    text = SCRIPT.read_text(encoding="utf-8")
    in_heredoc = False
    for line in text.splitlines():
        stripped = line.strip()
        # The help text quotes the public one-liner, which is deliberately short.
        if stripped.startswith("cat <<"):
            in_heredoc = True
            continue
        if in_heredoc:
            in_heredoc = stripped != "USAGE"
            continue
        # Comments, and lines that PRINT a command rather than run one. What this asserts is that
        # nothing the script itself EXECUTES fetches over an unconstrained transport.
        if stripped.startswith(("#", "printf", "say ", "echo", "warn", "die")):
            continue
        if "curl" in stripped and "http" in stripped:
            assert "--proto '=https'" in stripped and "--tlsv1.2" in stripped, stripped
        if "wget" in stripped and stripped.startswith("wget"):
            assert "--https-only" in stripped, stripped


def test_the_residue_check_never_modifies_the_machine() -> None:
    """It reports; it does not repair. A checker that also fixes cannot be trusted to say a
    machine was already clean, because it may have made it so."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[3] / "scripts" / "residue-check.sh"
    text = src.read_text(encoding="utf-8")
    for destructive in ("rm ", "rm -", "docker volume rm", "docker rm", "kill ", "pkill", "unlink"):
        assert destructive not in text, f"residue-check must not {destructive.strip()!r}"


def test_the_residue_check_treats_an_unrunnable_check_as_inconclusive() -> None:
    """The distinction the whole file exists for: a query that could not run is NOT a clean
    result. Its first draft used one docker --format for three kinds, which errors for each, and
    `2>/dev/null` turned that into 'nothing found' while four mosaera images sat on the machine.
    """
    from pathlib import Path

    src = Path(__file__).resolve().parents[3] / "scripts" / "residue-check.sh"
    text = src.read_text(encoding="utf-8")
    assert "INCONCLUSIVE" in text
    assert "exit 2" in text, "an unrunnable check needs an exit status of its own"
    assert text.count("unknown ") >= 4, "each check that can fail must be able to say so"


def test_the_installer_exits_rather_than_reading_past_itself() -> None:
    """Under `curl … | bash` the script IS stdin, and bash keeps READING it after the last
    command. With no `exit`, that final read blocks until the writer closes the pipe — so a server
    slow to finish the response leaves the terminal hung after setup has already exited, and only
    Ctrl-C returns the prompt. Reported on every run.

    Separate from the `exec < /dev/tty` fault: that one LOST the rest of the script, this one waits
    for a script already fully read. Fixing the first did not fix the second.
    """
    lines = [ln for ln in SCRIPT.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines[-1].strip() == "exit $?", (
        "the last statement must be an explicit exit, so bash stops reading the script; "
        f"found {lines[-1]!r}"
    )
    body_at = max(i for i, ln in enumerate(lines) if ln.strip() == 'main "$@"')
    assert body_at < len(lines) - 1, "and the exit must come AFTER the body actually runs"


def test_a_piped_script_without_an_explicit_exit_blocks(tmp_path: Path) -> None:
    """The mechanism itself, so the rule above has a reason rather than being a habit."""
    import subprocess

    def blocks(body: str) -> bool:
        script = tmp_path / "s.sh"
        script.write_text(body, encoding="utf-8")
        # `sleep` after the body is a writer that outlives the script — the shape of an HTTP
        # response whose connection has not closed yet.
        done = subprocess.run(  # noqa: S603 — argv built here; the path is this test's own
            [  # noqa: S607 — bash by name is the point: this asserts POSIX shell behaviour
                "bash",
                "-c",
                f'( cat "{script}"; sleep 5 ) | timeout 2 bash >/dev/null 2>&1',
            ],
            capture_output=True,
            text=True,
        )
        return done.returncode == 124

    assert blocks("true\n"), "no exit: bash blocks on one more read of stdin"
    assert not blocks("true\nexit 0\n"), "explicit exit: bash stops reading and returns"


def test_uv_is_asked_for_rather_than_installed_silently() -> None:
    """ADR-0117 §2 waived ADR-0116's consent rule for uv on the grounds that "a piped script cannot
    obtain consent". That premise was false — this script already prompts for the install directory
    through `/dev/tty`, the same terminal a uv prompt needs. The waiver bought nothing and cost the
    property the section spends five bullets defending."""
    body = SCRIPT.read_text(encoding="utf-8")
    ask = body[body.index("ensure_uv()") : body.index("ensure_uv()") + 3000]
    assert "Install uv? [Y/n]" in ask, "uv must be asked for, not announced after the fact"
    assert "read -r reply < /dev/tty" in ask, "and asked on the TERMINAL, since stdin is the script"
    # Declining is an answer, not a failure of the script — it says how to do it by hand.
    assert "astral.sh/uv/install.sh" in ask


def test_the_target_prompt_offers_a_path_instead_of_ending_the_run() -> None:
    """Answering "no" used to end the run with an environment variable to copy and a curl pipe to
    re-type. The operator has a terminal open and has just said the path is wrong; asking for the
    right one is the whole of the fix."""
    body = SCRIPT.read_text(encoding="utf-8")
    fn = body[body.index("confirm_target()") : body.index("confirm_target()") + 2500]
    assert "1) here" in fn, "the current directory is offered, with the path shown"
    assert '"$PWD/mosaera"' in fn
    assert "2) somewhere else" in fn and "Path:" in fn
    assert "3) cancel" in fn
    # `read` does not expand `~`; without this, "~/apps" made a directory literally named "~".
    assert '"~/"*) typed="$HOME/${typed#"~/"}"' in fn


def test_an_already_installed_machine_is_not_asked_where_to_install() -> None:
    """Re-running the one-liner on a configured machine asked where to install every time, and the
    only true answer was the directory it was already in — a question whose wrong answer would
    strand the existing install."""
    body = SCRIPT.read_text(encoding="utf-8")
    fn = body[body.index("confirm_target()") : body.index("confirm_target()") + 1200]
    assert '[ -d "$INSTALL_DIR/.git" ] && return 0' in fn


# ------------------------------------------------------------------ the second origin


def _endpoint_check() -> str:
    return (SCRIPT.parent / "check-install-endpoint.sh").read_text(encoding="utf-8")


def test_the_endpoint_check_compares_bytes_not_opinions() -> None:
    """`install.mosaera.dev` is a SECOND ORIGIN for install.sh, and on 2026-09-02 it was six
    commits and 8,832 bytes behind: four installer fixes had shipped, been verified against the
    mirror, and been reported as delivered, while every operator ran a script from 28 August.
    "It is fixed" and "it is still broken" were both true — about different files."""
    t = _endpoint_check()
    assert "sha256sum" in t or "shasum" in t, "it compares the fetched bytes"
    # It must ask neither origin what it believes it is serving.
    assert "Last-Modified" not in t and "ETag" not in t


def test_the_endpoint_check_has_three_answers() -> None:
    """A fetch that FAILED is not "in sync". Folding could-not-tell into either of the other two is
    the defect this repo has now measured seven times."""
    t = _endpoint_check()
    assert "INCONCLUSIVE" in t
    assert "exit 2" in t
    assert t.count('This is NOT "in sync": nothing was compared.') == 2, (
        "both fetches — endpoint AND mirror — must be able to say they could not tell"
    )


def test_the_endpoint_check_never_changes_anything() -> None:
    """It reports. A checker that also repairs cannot be trusted to say a thing was already right,
    because it may have made it so."""
    t = _endpoint_check()
    for destructive in ("mv ", "rm -rf /srv", "systemctl", "nginx -s", "> /srv"):
        assert destructive not in t, f"the check must not {destructive.strip()!r}"


def test_the_endpoint_check_names_which_fixes_are_missing() -> None:
    """ "The bytes are unequal" sends someone hunting; the missing lines say what an operator is
    actually running without."""
    t = _endpoint_check()
    for marker in ("exit $?", ") < /dev/tty", "Install uv? [Y/n]"):
        assert marker in t, f"{marker!r} is a fix worth naming when it is absent"
    assert "docs/runbooks/install-endpoint.md" in t, "and it points at the fix"
