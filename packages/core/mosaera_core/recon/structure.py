"""The ``structure`` dimension — walk the tree (ADR-0047 §3).

Purely deterministic: no tool, no model, just a bounded symlink-safe walk. Reports the
shape of the project — size, top-level layout, language mix — as provenanced facts.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import _fingerprint, _fs
from .types import DimensionResult, Observation

DIMENSION = "structure"

_TOP_EXTENSIONS = 6


def recon_structure(root: Path) -> DimensionResult:
    """Observe the project's shape.

    A truncated walk reports ``unavailable`` **with** what it did see: the listing is
    a prefix of the repo, so "N files" would be a confidently wrong number. Keeping
    the partial observations is the ``could_not_run`` contract — a partial read is
    worth recording, it just may not read as a complete one.
    """
    result = _fs.walk(root)
    files = result.files
    fingerprint = _fingerprint.fingerprint_listing(files)

    if not files:
        return DimensionResult.finding(
            DIMENSION,
            fingerprint,
            [
                Observation(
                    text="the project contains no readable files",
                    provenance="tool:walk",
                    severity="medium",
                )
            ],
        )

    observations = [
        Observation(
            text=f"{len(files)} files (excluding VCS/build/vendor trees)", provenance="tool:walk"
        ),
    ]

    top = sorted({f.split("/", 1)[0] for f in files if "/" in f})
    if top:
        observations.append(
            Observation(
                text=f"top-level directories: {', '.join(top[:12])}", provenance="tool:walk"
            )
        )

    extensions = Counter(Path(f).suffix.lower() for f in files if Path(f).suffix)
    if extensions:
        mix = ", ".join(f"{ext} ({n})" for ext, n in extensions.most_common(_TOP_EXTENSIONS))
        observations.append(Observation(text=f"file types: {mix}", provenance="tool:walk"))

    if result.truncated:
        return DimensionResult.could_not_run(
            DIMENSION,
            fingerprint,
            [f"tree walk truncated at {_fs.MAX_FILES} files — the listing is a prefix of the repo"],
            observations,
        )
    return DimensionResult.finding(DIMENSION, fingerprint, observations)
