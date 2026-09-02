"""The ``quality`` dimension — type soundness via mypy (ADR-0047 §3).

**This is the RCE-adjacent dimension.** mypy has no ``--isolated``; with no
``--config-file`` it discovers config from its cwd — here, an untrusted clone — and
honors ``plugins =`` by *importing* the named repo file into this process. That was
verified live (ADR-0033), and this process holds the GitLab PAT and the provider keys.

The containment is that this module cannot express the unsafe call: it goes through
:func:`_tools.mypy_errors`, which pins an empty config internally and takes no config
argument. There is no argv here to get wrong.

``quality`` is split from ``cleanliness`` deliberately: this asks *"is the code
sound"* (types), cleanliness asks *"is the code tidy"* (format + lint). They fail
independently and a map that merges them cannot say which.
"""

from __future__ import annotations

from pathlib import Path

from . import _fingerprint, _fs, _tools
from .types import DimensionResult, Observation

DIMENSION = "quality"

_MAX_REPORTED = 15


def _python_files(root: Path) -> list[str]:
    return [f for f in _fs.walk(root).files if f.endswith(".py")]


def recon_quality(root: Path) -> DimensionResult:
    """Observe type-checker findings across the project's Python sources."""
    files = _python_files(root)
    fingerprint = _fingerprint.fingerprint_files(root, files)

    if not files:
        return DimensionResult.finding(
            DIMENSION,
            fingerprint,
            [Observation(text="no Python sources to type-check", provenance="tool:walk")],
        )

    errors, ran = _tools.mypy_errors(root, files)
    if not ran:
        # The ADR-0033 rule, restated: a tool that produced no verdict is named, not
        # rounded down. "mypy did not run" must never render as "the types are fine".
        return DimensionResult.could_not_run(DIMENSION, fingerprint, ["mypy"])

    if not errors:
        return DimensionResult.clean(DIMENSION, fingerprint)

    observations = [
        Observation(
            text=f"mypy reports {len(errors)} type error(s)",
            provenance="tool:mypy",
            severity="high",
        )
    ]
    observations += [
        Observation(text=line, provenance="tool:mypy", severity="high")
        for line in errors[:_MAX_REPORTED]
    ]
    return DimensionResult.finding(DIMENSION, fingerprint, observations)
