"""The ``deps`` dimension — parse the manifests/lockfiles (ADR-0047 §3).

Fully deterministic and stdlib-only (``tomllib`` + ``json``): this is exactly the
dimension the DNA points at when it says an LLM must earn its place. "Ask the model
what this project depends on" costs tokens per project and produces an unfalsifiable
narrative; parsing the lockfile answers it exactly.

The distinction that matters here is **"no manifest"** vs **"a manifest we could not
read"**. The first is a finding — we looked, and this project genuinely declares no
dependencies. The second is ``unavailable`` — a corrupt or exotic manifest means we
learned nothing, and reporting that as "no dependencies" would be the ADR-0033
false-green in miniature.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from . import _fingerprint, _fs
from .types import DimensionResult, Observation

DIMENSION = "deps"

# Manifests we can parse with the stdlib. yarn.lock / pnpm-lock.yaml are detected for
# the lockfile signal but deliberately not parsed — their formats need extra parsers,
# and presence alone answers the question this dimension asks of them.
_MANIFESTS = ("pyproject.toml", "package.json", "Pipfile", "requirements.txt")
_LOCKFILES = (
    "uv.lock",
    "poetry.lock",
    "Pipfile.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
)


def _pyproject_deps(raw: str) -> tuple[int, bool]:
    """(count, parsed_ok) for a pyproject.toml."""
    try:
        data: dict[str, Any] = tomllib.loads(raw)
    except (tomllib.TOMLDecodeError, ValueError, RecursionError, MemoryError):
        # A deeply-nested manifest (~6 KB of `[[[…]]]`, well under the read cap) blows
        # the parser's recursion limit. RecursionError is NOT a ValueError — left
        # uncaught it crashes the whole dimension instead of reporting unavailable
        # (ADR-0035: loud, never a hard crash). ci.py guards the identical class.
        return 0, False
    project = data.get("project")
    count = 0
    if isinstance(project, dict):
        deps = project.get("dependencies")
        if isinstance(deps, list):
            count += len(deps)
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            count += sum(len(v) for v in optional.values() if isinstance(v, list))
    return count, True


def _package_json_deps(raw: str) -> tuple[int, int, bool]:
    """(deps, devDeps, parsed_ok) for a package.json."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError, RecursionError, MemoryError):
        # See _pyproject_deps: a deeply-nested package.json crashes json.loads with
        # RecursionError, which is not a ValueError. Map it to "unparseable", not a crash.
        return 0, 0, False
    if not isinstance(data, dict):
        return 0, 0, False
    deps = data.get("dependencies")
    dev = data.get("devDependencies")
    return (
        len(deps) if isinstance(deps, dict) else 0,
        len(dev) if isinstance(dev, dict) else 0,
        True,
    )


def _requirements_deps(raw: str) -> int:
    return len(
        [
            ln
            for ln in raw.splitlines()
            if ln.strip() and not ln.strip().startswith("#") and not ln.strip().startswith("-")
        ]
    )


def recon_deps(root: Path) -> DimensionResult:
    """Observe the project's declared dependencies and whether they are pinned."""
    present_manifests = [m for m in _MANIFESTS if _fs.exists(root, m)]
    present_locks = [lock for lock in _LOCKFILES if _fs.exists(root, lock)]
    fingerprint = _fingerprint.fingerprint_files(root, [*present_manifests, *present_locks])

    if not present_manifests and not present_locks:
        return DimensionResult.finding(
            DIMENSION,
            fingerprint,
            [
                Observation(
                    text="no dependency manifest or lockfile — nothing declared",
                    provenance="tool:walk",
                    severity="medium",
                )
            ],
        )

    observations: list[Observation] = []
    unavailable: list[str] = []

    for manifest in present_manifests:
        raw = _fs.read_text(root, manifest)
        if raw is None:
            unavailable.append(f"{manifest} (unreadable)")
            continue
        if manifest == "pyproject.toml":
            count, ok = _pyproject_deps(raw)
            if not ok:
                unavailable.append(f"{manifest} (unparseable TOML)")
            else:
                observations.append(
                    Observation(text=f"declares {count} Python dependencies", provenance=manifest)
                )
        elif manifest == "package.json":
            deps, dev, ok = _package_json_deps(raw)
            if not ok:
                unavailable.append(f"{manifest} (unparseable JSON)")
            else:
                observations.append(
                    Observation(
                        text=f"declares {deps} runtime + {dev} dev npm dependencies",
                        provenance=manifest,
                    )
                )
        elif manifest == "requirements.txt":
            observations.append(
                Observation(
                    text=f"requirements.txt lists {_requirements_deps(raw)} requirements",
                    provenance=manifest,
                )
            )
        else:
            observations.append(Observation(text=f"{manifest} present", provenance=manifest))

    if present_locks:
        observations.append(
            Observation(
                text=f"lockfile(s) present: {', '.join(present_locks)}", provenance="tool:walk"
            )
        )
    elif present_manifests:
        observations.append(
            Observation(
                text="no lockfile — dependency versions are not pinned for reproducible installs",
                provenance="tool:walk",
                severity="low",
            )
        )

    return DimensionResult.from_parts(DIMENSION, fingerprint, observations, unavailable)
