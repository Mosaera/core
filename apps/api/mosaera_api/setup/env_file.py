"""Read and rewrite a `.env` file in place, preserving everything we do not own.

WHY THIS EXISTS. Bind host, port and the service token cannot live in `settings.json` — `_knobs.py`
keeps "infra / bootstrap / secret knobs (API host/port/token, admin token, db_url, sandbox backend/
image, home) ... env-only". So the wizard has to write `.env`, and until now **no Python wrote it**:
`scripts/install.sh` copies `.env.example` once and never touches it again.

THE RULE THAT SHAPES THE CODE. That file is the operator's, not ours. `.env.example` is 238 lines
of commented guidance, and a naive rewrite (parse to a dict, dump the dict) would silently discard
every comment and reorder every key — turning a file someone reads into one they cannot. So this
edits LINES: an existing assignment is replaced where it stands, a new one is appended under a
labelled block, and every other byte survives untouched.
"""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Iterable
from pathlib import Path

#: Appended above keys this wizard adds, so a later reader knows what put them there.
_BLOCK_HEADER = "# --- written by `mosaera-setup` ---"


def remove_env_keys(path: Path, keys: Iterable[str]) -> None:
    """Drop `keys` from `path`, leaving everything else exactly where it is — and delete the file
    only when nothing of the operator's is left in it.

    The counterpart to `write_env_file`, and it exists for the same reason. Uninstalling used to
    `unlink` this file whole, under a row promising to remove "the .env this wizard wrote": a
    `.env` also holds whatever the operator put there — provider keys, an admin token, anything
    they source from a shell — and none of that is ours to take away.
    """
    keys = set(keys)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    kept = [
        line
        for line in lines
        if not ((parsed := _split_assignment(line)) is not None and parsed[0] in keys)
    ]
    if not any(_split_assignment(line) is not None for line in kept):
        # Nothing live remains: what is left is our own banner and blank lines, so the file was
        # ours entirely and goes. A file the operator had never touched must not survive as a
        # husk — an uninstall that leaves a `.env` behind reads as one that failed.
        path.unlink(missing_ok=True)
        return
    text = "\n".join(_drop_our_banner(kept)).strip("\n")
    path.write_text(text + "\n", encoding="utf-8")


def _drop_our_banner(lines: list[str]) -> list[str]:
    """Take our own header out once nothing under it is ours any more."""
    return [line for line in lines if line.strip() != _BLOCK_HEADER]


def _split_assignment(line: str) -> tuple[str, str, bool] | None:
    """`("KEY", "value")` for an ACTIVE assignment, else None.

    A commented-out line is not an assignment: `.env.example` ships almost every key commented, and
    treating `#MOSAERA_API_PORT=8000` as a live value would make the wizard think the operator had
    already chosen one.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    exported = stripped.startswith("export ")
    key, _, value = stripped.removeprefix("export ").partition("=")
    key = key.strip()
    if not key or not key.replace("_", "").isalnum():
        return None
    return key, _unquote(value.strip()), exported


def _unquote(value: str) -> str:
    """`PORT="8000"` means 8000, not `"8000"`.

    Quotes were kept verbatim, and every caller then did `int(...)` on the result — so a perfectly
    ordinary quoted `.env` crashed a step entry. It also made `access_env` compare `'"8000"'` with
    `"8000"` and rewrite the key on every single run, which is the opposite of the idempotence that
    function exists to provide.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


#: The process environment as it was BEFORE `load_env` copied `.env` into it.
#:
#: This snapshot is the whole difference between "the shell exported this" and "`.env` says this".
#: `config.load_env` merges the file into `os.environ` at startup (real vars winning), so by the
#: time any screen runs there is no way to tell the two apart from `os.environ` alone — the first
#: cut of this check compared against the merged environment and warned about variables the operator
#: had never set.
_REAL_ENV: dict[str, str] | None = None


def capture_real_env(env: dict[str, str] | None = None) -> None:
    """Take the snapshot. Called once, before `load_env`."""
    global _REAL_ENV
    _REAL_ENV = dict(os.environ if env is None else env)


def _real_env() -> dict[str, str]:
    # Never captured (a test, an embedder): fall back to the merged environment, which is right for
    # `effective_env` and merely conservative for `shadowed_by_env`.
    return _REAL_ENV if _REAL_ENV is not None else dict(os.environ)


def effective_env(path: Path) -> dict[str, str]:
    """`.env` with the REAL environment layered on top.

    ADR-0005: env > stored > default. The wizard read `.env` alone, so a `MOSAERA_API_PORT` exported
    in the shell was ignored — the access screen offered the default 8000 while the process would
    have bound elsewhere, and the launcher then probed 8000, found whatever was already answering
    there, and reported it as the instance it had just set up.
    """
    stored = read_env_file(path)
    live = {k: v for k, v in _real_env().items() if k.startswith("MOSAERA_") and v.strip()}
    return {**stored, **live}


def shadowed_by_env(path: Path, *keys: str) -> list[str]:
    """Which of `keys` the SHELL is overriding, so a screen can say so.

    Writing `.env` cannot change a value the shell is exporting, and silently writing one anyway is
    how an operator ends up certain they configured something they did not.
    """
    stored = read_env_file(path)
    real = _real_env()
    return [k for k in keys if real.get(k, "").strip() and real[k].strip() != stored.get(k, "")]


def port_from(values: dict[str, str], key: str, default: int) -> int:
    """A port out of `.env`, or the default. NEVER raises.

    Three call sites did `int(values.get(key) or 8000)` on the UI thread, so a hand-edited
    `MOSAERA_API_PORT=eight-thousand` raised `ValueError` inside a step entry and Textual tore the
    wizard down with a traceback. A bad value is the operator's to fix, not the wizard's to die on.
    """
    raw = (values.get(key) or "").strip()
    try:
        port = int(raw)
    except ValueError:
        return default
    return port if 1 <= port <= 65535 else default


def read_env_file(path: Path) -> dict[str, str]:
    """The active assignments in `path`. Missing or unreadable file → `{}`."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines():
        parsed = _split_assignment(line)
        if parsed is not None:
            out[parsed[0]] = parsed[1]
    return out


def write_env_file(path: Path, updates: dict[str, str]) -> None:
    """Apply `updates` to `path`, in place, preserving comments, order and unrelated keys.

    An existing ACTIVE assignment is rewritten where it sits, so the comment above it still explains
    the line beneath it. A key present only as a commented example is left commented and the real
    value appended below — rewriting the example in place would destroy the documentation for every
    operator who reads this file next.
    """
    if not updates:
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []

    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        parsed = _split_assignment(line)
        if parsed is not None and parsed[0] in remaining:
            key, _old, exported = parsed
            # `export ` is preserved. Dropping it silently broke a `.env` the operator sources from
            # a shell, on the second run, in a file this module promises to leave otherwise intact.
            prefix = "export " if exported else ""
            out.append(f"{prefix}{key}={remaining.pop(key)}")
            continue
        out.append(line)

    if remaining:
        if out and out[-1].strip():
            out.append("")
        if _BLOCK_HEADER not in out:
            out.append(_BLOCK_HEADER)
        out.extend(f"{k}={v}" for k, v in remaining.items())

    _atomic_write(path, "\n".join(out) + "\n")


def _atomic_write(path: Path, text: str) -> None:
    """Replace `path` in one step, never leaving a half-written file behind.

    Two faults this closes. `write_text` truncates and then writes, so a crash, a full disk or an
    ENOSPC left the operator with a TRUNCATED `.env` and no backup — of the file this module's own
    docstring calls "the operator's, not ours". And the mode was set AFTER writing, so a newly
    created file held a service token at 0644 for the duration.

    Written 0600 from creation via `os.open`, then renamed over the target: on POSIX `os.replace` is
    atomic, so a reader sees either the old file or the new one, never a partial one.

    A THIRD fault, found by chmod-ing a live one to 0400: replacing needs permission on the
    DIRECTORY, not on the file, so a deliberately read-only `.env` was overwritten without a word
    and came back 0600 — the wizard both ignoring and widening a permission the operator chose.
    """
    mode = stat.S_IRUSR | stat.S_IWUSR  # 0600, unless the operator asked for less
    if path.exists():
        current = path.stat().st_mode & 0o777
        # The MODE is the question, not whether this process happens to be able to write.
        # `os.access` answers the second, and for root it answers True on a 0400 file — root
        # bypasses the permission check entirely. Asking it meant the one operator most able to
        # do damage was the one the guard did not cover: under `sudo` the refusal was a no-op.
        # Read `chmod 0400` as the instruction it is and refuse regardless of who is asking.
        if not current & stat.S_IWUSR:
            raise PermissionError(
                f"{path} is read-only ({current:04o}); change its mode or move it aside"
            )
        # Never WIDEN. A 0400 file coming back 0600 is the wizard granting itself a permission.
        mode &= current | stat.S_IRUSR
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".env.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, mode)  # set BEFORE any content exists
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
