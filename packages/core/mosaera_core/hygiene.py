"""Deterministic hygiene gate for a run's changed Python files.

Two deterministic passes, zero model tokens:
- ``autofix`` fixes the MECHANICAL issues for free — formats (``ruff format``) and applies
  SAFE lint autofixes (``ruff check --select F --fix``, e.g. drop an unused import).
- ``hygiene_findings`` reports the residual BLOCKING issues the coder must fix in-loop:
  unformatted files, ruff **F-class** real-bug lint (undefined names, …), and ``mypy``
  type errors.

Python-only, host-side static analysis. It runs against a clone of an UNTRUSTED repo, so
every tool call goes through ``_hosttools`` — which pins mypy's config (repo config
discovery honors ``plugins =``, i.e. it would execute repo code on the host) and isolates
the ruff calls that produce findings (a repo must not be able to suppress its own lint).
Formatting still honors the project's ruff config: that is style, and style is the
project's to choose.

A tool that cannot run yields ``unavailable``, NOT an empty findings list — "we learned
nothing" is never reported as "the code is clean" (see ``HygieneReport``).
"""

from __future__ import annotations

import contextlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from mosaera_core._hosttools import isolated_mypy_args, mypy_argv, run_tool
from mosaera_core.quality import changed_python_files
from mosaera_core.tools.repo import Workspace

_EXCLUDE = (".venv", "_mcb_grader", ".git", "__pycache__", "node_modules")
_MYPY_EXCLUDE = r"(\.venv|_mcb_grader|__pycache__|node_modules)/"


@dataclass(frozen=True)
class HygieneReport:
    """What the hygiene pass learned.

    ``findings`` are blocking issues the coder must fix. ``unavailable`` names the tools
    that produced no verdict at all. Both empty = genuinely clean; a non-empty
    ``unavailable`` means part of the check simply did not happen, and no caller may
    round that down to "clean".
    """

    findings: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)


def hygiene_targets(workspace: Workspace, diff: str) -> list[str]:
    """The run's changed Python files that still exist on disk (relative paths)."""
    return [f for f in changed_python_files(diff) if (workspace.root / f).is_file()]


def autofix(workspace: Workspace, files: list[str]) -> bool:
    """Deterministically format + apply SAFE lint autofixes to ``files``. Returns whether
    anything actually changed. Behavior-preserving; no model call."""
    if not files:
        return False
    root = workspace.root
    before = _snapshot(root, files)
    # --isolated: the repo must not be able to switch off the real-bug lint we fix here.
    run_tool(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--select", "F", "--fix",
         "--exclude", ",".join(_EXCLUDE), *files],
        root,
    )  # fmt: skip
    # NOT isolated: formatting honors the project's own ruff style config, by design.
    run_tool(
        [sys.executable, "-m", "ruff", "format", "--exclude", ",".join(_EXCLUDE), *files],
        root,
    )
    return _snapshot(root, files) != before


def hygiene_findings(workspace: Workspace, files: list[str]) -> HygieneReport:
    """Residual BLOCKING issues after ``autofix``, plus any tool that could not run."""
    if not files:
        return HygieneReport()
    root = workspace.root
    findings: list[str] = []
    unavailable: list[str] = []
    for tool, (msgs, ran) in (
        ("ruff format", _unformatted(root, files)),
        ("ruff", _ruff_f_messages(root, files)),
        ("mypy", _mypy_messages(root, files)),
    ):
        findings.extend(msgs)
        if not ran:
            unavailable.append(tool)
    return HygieneReport(findings=findings, unavailable=unavailable)


def _unformatted(root: Path, files: list[str]) -> tuple[list[str], bool]:
    res = run_tool(
        [sys.executable, "-m", "ruff", "format", "--check",
         "--exclude", ",".join(_EXCLUDE), *files],
        root,
    )  # fmt: skip
    if res.unavailable:
        return [], False
    out: list[str] = []
    for ln in res.stdout.splitlines():
        # ruff prints "Would reformat: <path>" per unformatted file.
        if ln.startswith("Would reformat:"):
            out.append(f"{ln.split(':', 1)[1].strip()}: not formatted — run the formatter")
    return out, True


def _ruff_f_messages(root: Path, files: list[str], limit: int = 20) -> tuple[list[str], bool]:
    res = run_tool(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--select", "F",
         "--output-format", "json", "--exclude", ",".join(_EXCLUDE), *files],
        root,
    )  # fmt: skip
    if res.unavailable:
        return [], False
    try:
        items = json.loads(res.stdout or "[]")
    except (json.JSONDecodeError, ValueError):
        return [], False
    out: list[str] = []
    for it in items[:limit]:
        loc = it.get("location") or {}
        path = it.get("filename", "")
        with contextlib.suppress(ValueError):
            # POSIX-normalise so findings read identically on Windows and Linux (see quality.py).
            path = Path(path).relative_to(root).as_posix()
        out.append(
            f"{path}:{loc.get('row', '?')} {it.get('code', '')} {it.get('message', '')}".strip()
        )
    return out, True


def _mypy_messages(root: Path, files: list[str], limit: int = 20) -> tuple[list[str], bool]:
    with isolated_mypy_args() as cfg:
        res = run_tool(
            mypy_argv(
                ["--ignore-missing-imports", "--no-color-output", "--no-error-summary",
                 "--exclude", _MYPY_EXCLUDE],
                files,
                cfg,
            ),
            root,
        )  # fmt: skip
    if res.unavailable:
        return [], False
    return [ln.strip() for ln in res.stdout.splitlines() if ": error:" in ln][:limit], True


def _snapshot(root: Path, files: list[str]) -> list[tuple[str, bytes]]:
    snap: list[tuple[str, bytes]] = []
    for f in files:
        try:
            snap.append((f, (root / f).read_bytes()))
        except OSError:
            snap.append((f, b""))
    return snap
