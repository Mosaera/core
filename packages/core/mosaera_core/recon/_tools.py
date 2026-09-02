"""Host tools against an untrusted clone — pinned **by construction**, not by convention.

``_hosttools`` supplies the primitives (:func:`run_tool`, :func:`isolated_mypy_args`,
:func:`mypy_argv`). It does not, and cannot, stop a caller running an *unpinned* tool:
``run_tool`` will happily execute a bare ``python -m mypy`` in an untrusted cwd, which
is the verified ``plugins = ./evil.py`` RCE (ADR-0033). Today that discipline holds
because two modules apply it correctly and a reviewer checks the third.

Recon adds eight more callers. Convention does not survive that, so this module exists
to make the unsafe call **unreachable**: dimensions never build argv and never see
``run_tool``. They call :func:`ruff_findings` / :func:`ruff_unformatted` /
:func:`mypy_errors`, each of which pins its own config internally. This extends the
existing ``mypy_argv`` idea — which already forces the pinned ``cfg`` positionally —
to the whole recon surface.

Every helper returns ``(value, ran)``. ``ran=False`` means the tool produced no
verdict and the caller MUST report ``unavailable``; it never means "nothing found".
A garbled parse counts as no verdict — corrupt output is not evidence of clean code.

**Targets are untrusted argv.** The paths handed to a tool come from the repo, and a
repo can commit a file named ``--isolated=x.py`` or ``--config=evil.toml``. Since those
are also argv, they are flags — and for mypy a second ``--config-file`` re-opens the
RCE the pin just closed (red-team #41). Every tool invocation puts ``--`` before its
targets so an option-shaped filename is always a positional file, never a flag.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from typing import Any

from mosaera_core._hosttools import isolated_mypy_args, mypy_argv, run_tool

# Vendored/generated trees are not the project's own code; reconning them describes
# someone else's repo. Mirrors the hygiene/quality exclude sets.
_EXCLUDE = (".venv", "venv", ".git", "__pycache__", "node_modules", "dist", "build")
_MYPY_EXCLUDE = r"(\.venv|venv|__pycache__|node_modules|dist|build)/"

# Cap what any one tool can dump into the map. Findings are attacker-influenced (a
# repo chooses how many lint errors it has); an unbounded list would let a hostile
# repo balloon a durable artifact.
MAX_ITEMS = 200


def _rel(root: Path, path: str) -> str:
    """POSIX-normalise a tool-reported path so observations read identically on
    Windows and Linux (the quality.py convention)."""
    out = path
    with contextlib.suppress(ValueError):
        out = Path(path).relative_to(root).as_posix()
    return out


def _safe_targets(targets: list[str]) -> list[str]:
    """Drop option/response-file-shaped filenames before they reach a tool's argv.

    Defense-in-depth on top of the ``--`` separator (red-team #41, round 2). ``--`` stops
    a tool's OPTION parser, but not every tool's ``@response-file`` expansion, and relying
    on each tool honoring the separator identically is a thin guarantee for a trust
    boundary. A path component beginning with ``-`` or ``@`` is never a legitimate Python
    source file (neither is an importable module name), so dropping it loses nothing real
    and removes the "filename is argv" class outright rather than per-tool."""
    return [t for t in targets if not any(part[:1] in "-@" for part in t.split("/") if part)]


def ruff_findings(
    root: Path, targets: list[str], *, select: str | None = None, limit: int = MAX_ITEMS
) -> tuple[list[dict[str, Any]], bool]:
    """ruff lint findings as ``({filename, row, code, message}, ...), ran``.

    **Always ``--isolated``.** ruff config is pure TOML and cannot execute code, but
    it *can* suppress findings — a repo that ships a ``per-file-ignores`` for the very
    rule that would describe it must not get to edit its own map entry.
    """
    argv = [
        sys.executable, "-m", "ruff", "check", "--isolated",
        "--output-format", "json", "--exclude", ",".join(_EXCLUDE),
    ]  # fmt: skip
    if select:
        argv += ["--select", select]
    res = run_tool([*argv, "--", *_safe_targets(targets)], root)
    if res.unavailable:
        return [], False
    try:
        items = json.loads(res.stdout or "[]")
    except (json.JSONDecodeError, ValueError):
        return [], False
    if not isinstance(items, list):
        return [], False
    out: list[dict[str, Any]] = []
    for it in items[:limit]:
        if not isinstance(it, dict):
            continue
        loc = it.get("location") or {}
        out.append(
            {
                "filename": _rel(root, str(it.get("filename", ""))),
                "row": loc.get("row", "?") if isinstance(loc, dict) else "?",
                "code": str(it.get("code") or ""),
                "message": str(it.get("message") or ""),
            }
        )
    return out, True


def ruff_unformatted(
    root: Path, targets: list[str], *, limit: int = MAX_ITEMS
) -> tuple[list[str], bool]:
    """Files ruff would reformat, as ``(paths, ran)``.

    **Isolated, unlike ``hygiene.autofix``** — a deliberate divergence. Hygiene
    *rewrites* the project's files, so honoring the project's own style is the point.
    Recon only *observes*, and it observes across projects: a repo that declares an
    exotic style would otherwise always read "clean" here, and a hostile one could
    declare a config that guarantees it. Recon reports against one fixed standard, and
    "formatted differently than we'd write it" is a low-severity observation, not a
    verdict on the project.
    """
    res = run_tool(
        [sys.executable, "-m", "ruff", "format", "--check", "--isolated",
         "--exclude", ",".join(_EXCLUDE), "--", *_safe_targets(targets)],
        root,
    )  # fmt: skip
    if res.unavailable:
        return [], False
    out: list[str] = []
    for ln in res.stdout.splitlines():
        # ruff prints "Would reformat: <path>" per unformatted file.
        if ln.startswith("Would reformat:"):
            out.append(_rel(root, ln.split(":", 1)[1].strip()))
    return out[:limit], True


def mypy_errors(
    root: Path, targets: list[str], *, limit: int = MAX_ITEMS
) -> tuple[list[str], bool]:
    """mypy error lines as ``(lines, ran)``.

    The config is pinned inside this function and cannot be supplied by a caller, so
    there is no code path that lets recon read the repo's ``mypy.ini`` — which is what
    makes ``plugins = ./evil.py`` inert. ``run_tool`` must stay INSIDE the context
    manager: the pinned config is a tempdir that is deleted on exit.
    """
    with isolated_mypy_args() as cfg:
        res = run_tool(
            mypy_argv(
                ["--ignore-missing-imports", "--no-color-output", "--no-error-summary",
                 "--exclude", _MYPY_EXCLUDE],
                _safe_targets(targets),
                cfg,
            ),
            root,
        )  # fmt: skip
    if res.unavailable:
        return [], False
    return [ln.strip() for ln in res.stdout.splitlines() if ": error:" in ln][:limit], True
