"""The ``cleanliness`` dimension — lint + formatting via ruff (ADR-0047 §3).

Asks *"is this code tidy"*: does it lint clean, is it consistently formatted. The
sibling ``quality`` dimension asks *"is it sound"* (types).

Both ruff calls run ``--isolated`` (see :mod:`._tools`): a repo must not be able to
ship a ``per-file-ignores`` that suppresses the very finding describing it, and must
not be able to declare a formatting config that guarantees its own map entry reads
clean. Partial availability is honest — if lint answers and formatting does not, this
reports ``unavailable`` **and** keeps the lint findings.
"""

from __future__ import annotations

from pathlib import Path

from . import _fingerprint, _fs, _tools
from .types import DimensionResult, Observation

DIMENSION = "cleanliness"

_MAX_REPORTED = 15


def _python_files(root: Path) -> list[str]:
    return [f for f in _fs.walk(root).files if f.endswith(".py")]


def recon_cleanliness(root: Path) -> DimensionResult:
    """Observe lint findings and formatting drift across the project's Python sources."""
    files = _python_files(root)
    fingerprint = _fingerprint.fingerprint_files(root, files)

    if not files:
        return DimensionResult.finding(
            DIMENSION,
            fingerprint,
            [Observation(text="no Python sources to lint", provenance="tool:walk")],
        )

    observations: list[Observation] = []
    unavailable: list[str] = []

    findings, lint_ran = _tools.ruff_findings(root, files)
    if not lint_ran:
        unavailable.append("ruff check")
    elif findings:
        observations.append(
            Observation(
                text=f"ruff reports {len(findings)} lint finding(s)",
                provenance="tool:ruff",
                severity="low",
            )
        )
        observations += [
            Observation(
                text=f"{f['filename']}:{f['row']} {f['code']} {f['message']}".strip(),
                provenance="tool:ruff",
                severity="low",
            )
            for f in findings[:_MAX_REPORTED]
        ]

    unformatted, fmt_ran = _tools.ruff_unformatted(root, files)
    if not fmt_ran:
        unavailable.append("ruff format")
    elif unformatted:
        observations.append(
            Observation(
                text=f"{len(unformatted)} file(s) are not consistently formatted",
                provenance="tool:ruff-format",
                severity="low",  # format drift is explicitly low-severity (see _tools docstring)
            )
        )

    return DimensionResult.from_parts(DIMENSION, fingerprint, observations, unavailable)
