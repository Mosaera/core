"""The one place that shells out to a static-analysis tool on the HOST.

``hygiene.py`` and ``quality.py`` both run ruff/mypy against a clone of an
**untrusted** repo, outside the sandbox. Two rules hold here that hold nowhere else,
and they are the reason this module exists instead of a private ``_run`` in each file:

1. **Tool config comes from us, never from the repo.** mypy has no ``--isolated``;
   with no ``--config-file`` it discovers ``mypy.ini`` / ``setup.cfg`` /
   ``pyproject.toml`` **from its cwd** — and a ``[mypy] plugins = ./evil.py`` line
   makes mypy *import and execute* that repo-committed file in this process. Config
   discovery in an untrusted cwd is remote code execution, so every mypy invocation
   goes through :func:`isolated_mypy_args`. (ruff's config is pure TOML — it cannot
   execute code — but it *can* suppress findings, so the calls that produce findings
   pass ``--isolated`` too. Formatting deliberately still honors the project's style.)

2. **"The tool could not run" is not "the code is clean."** Collapsing those two into
   an empty findings list is how a gate goes quietly green with no analysis behind it.
   :attr:`ToolResult.unavailable` keeps them distinct; callers must not merge them back.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

_TIMEOUT = 120

# Every host tool runs as ``python -m <tool>`` with ``cwd`` = the untrusted clone, and
# ``python -m`` puts the cwd at ``sys.path[0]``. So a repo committing a plain module the
# tool imports — ``mypy_extensions.py``/``tomllib.py`` for mypy, ``ruff.py`` for ruff —
# is imported and executed at tool startup, BEFORE any argv or config parsing. That is
# RCE from a normal hostile clone (verified live; red-team #41 round 2), on a lower layer
# than either config discovery or argv injection. ``PYTHONSAFEPATH`` removes the cwd from
# the child's import path; the installed tools live in site-packages and are unaffected.
# (Minimal fix. The durable answer is to stop making the untrusted clone the tool's cwd
# at all — run in a scratch cwd with absolute target paths, or in the sandbox — logged as
# a successor in ADR-0047, since two rounds found cwd-of-untrusted-clone RCEs.)


def _safe_env() -> dict[str, str]:
    """The child process env, read fresh each call, with the cwd stripped from its import
    path. See the module note above — this is the untrusted-cwd module-shadow RCE guard."""
    return {**os.environ, "PYTHONSAFEPATH": "1"}


# A tool "ran" if it exited 0 (nothing to report) or 1 (it reported findings). Anything
# else — 2 for a mypy internal error, 127 for a missing module, a timeout, an OSError —
# means we learned nothing about the code.
_RAN = (0, 1)


@dataclass(frozen=True)
class ToolResult:
    """The outcome of one host-side tool run.

    ``unavailable`` is the honest-outcome bit: True means the tool never produced a
    verdict. Reading that as "no findings" is a false green.
    """

    stdout: str = ""
    returncode: int = -1
    unavailable: bool = True


def run_tool(argv: list[str], cwd: Path) -> ToolResult:
    """Run a static-analysis tool in ``cwd`` (an untrusted clone). Never raises."""
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, our own tooling
            argv, cwd=cwd, capture_output=True, text=True, timeout=_TIMEOUT, env=_safe_env()
        )
    except (OSError, subprocess.SubprocessError):
        return ToolResult()
    if proc.returncode not in _RAN:
        return ToolResult(stdout=proc.stdout or "", returncode=proc.returncode)
    return ToolResult(stdout=proc.stdout or "", returncode=proc.returncode, unavailable=False)


@contextlib.contextmanager
def isolated_mypy_args() -> Iterator[list[str]]:
    """Flags that stop mypy reading ANY config from the repo it is analysing.

    Without these, mypy walks its cwd for a config file and honors ``plugins =`` by
    importing the named module — arbitrary code execution from a cloned repo. The
    config we hand it is empty, so no plugin can be declared. ``--cache-dir`` also
    keeps ``.mypy_cache`` out of the workspace (and so out of the delivered diff).
    """
    with tempfile.TemporaryDirectory(prefix="mosaera-mypy-") as tmp:
        cfg = Path(tmp) / "mypy.ini"
        cfg.write_text("[mypy]\n", encoding="utf-8")
        yield ["--config-file", str(cfg), "--cache-dir", str(Path(tmp) / "cache")]


def mypy_argv(args: list[str], targets: list[str], cfg: list[str]) -> list[str]:
    """``python -m mypy`` with our config pinned. ``cfg`` comes from
    :func:`isolated_mypy_args` — there is no other supported way to call mypy here.

    ``targets`` are **file paths from an untrusted repo**, and a repo can commit a file
    literally named ``--config-file=evil.py``. Since targets are also argv, such a name
    is a second ``--config-file`` — and mypy honors the LAST one, re-opening the pinned
    config we just closed and re-enabling the ``plugins =`` RCE (verified live; red-team
    #41). The ``--`` end-of-options separator makes everything after it a positional
    file, never an option, so an option-shaped filename can no longer inject flags."""
    return [sys.executable, "-m", "mypy", *cfg, *args, "--", *targets]
