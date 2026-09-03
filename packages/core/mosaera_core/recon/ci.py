"""The ``ci`` dimension — parse the CI configuration (ADR-0047 §3).

**Scope note.** ADR-0047 §3 describes this dimension as "parse the config + query the
API". This module does the parse only. Querying a GitLab pipeline would mean ``core``
importing ``mosaera_connectors`` — an upward import the layer guard forbids
(``scripts/check_layer_imports.py``), and punching a hole in the layer direction to
save an injected protocol would be the wrong trade. The API half belongs to the
onboarding *flow* (#6c/#42), which already sits at the layer that may talk to
connectors. Until then this dimension reports what the config declares, not whether
the last pipeline was green.

**Parsing untrusted YAML.** ``yaml.safe_load`` — never ``yaml.load`` — because the
default loader constructs arbitrary Python objects from repo-controlled input, which
is the same class of hole as mypy's ``plugins =`` (ADR-0033). ``safe_load`` closes
that, but it does **not** close alias expansion: the "billion laughs" bomb is a few
hundred bytes of YAML that expands to gigabytes and OOMs the host process — the one
holding the PAT and provider keys. A size cap does not help (the input is tiny), so
this module refuses configs with implausible anchor/alias counts *before* parsing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import _fingerprint, _fs
from .types import DimensionResult, Observation

try:  # PyYAML is a declared runtime dep; guard anyway so a broken install is HONEST.
    import yaml
except ImportError:  # pragma: no cover - exercised via monkeypatch, not a real install
    yaml = None  # type: ignore[assignment]

DIMENSION = "ci"

# A real CI config uses a handful of anchors for job templates. Orders of magnitude
# more is a bomb, not a project. Refusing is deterministic and cheap; parsing first to
# find out is the thing we cannot afford.
_MAX_ANCHORS = 64
_MAX_ALIASES = 256

# CI configs are small. This cap is not the bomb defence (see above) — it just stops a
# multi-megabyte "config" from being read at all.
_MAX_CI_BYTES = 512_000

_GITLAB_CI = ".gitlab-ci.yml"
_CIRCLE_CI = ".circleci/config.yml"
_AZURE_CI = "azure-pipelines.yml"


def _looks_like_a_yaml_bomb(raw: str) -> bool:
    """Cheap structural refusal: count anchor definitions and alias references."""
    return raw.count("&") > _MAX_ANCHORS or raw.count("*") > _MAX_ALIASES


def _safe_parse(raw: str) -> tuple[Any, str | None]:
    """``(data, reason_it_failed)``. Never raises, never runs repo code."""
    if yaml is None:
        return None, "PyYAML is not installed"
    if _looks_like_a_yaml_bomb(raw):
        return None, "refused: implausible anchor/alias count (possible YAML bomb)"
    try:
        return yaml.safe_load(raw), None
    except yaml.YAMLError:
        return None, "unparseable YAML"
    except (RecursionError, MemoryError):
        # Belt and braces: the anchor guard should have caught this first.
        return None, "refused: YAML expansion exceeded host limits"


def _ci_files(root: Path) -> list[str]:
    found = [c for c in (_GITLAB_CI, _CIRCLE_CI, _AZURE_CI) if _fs.exists(root, c)]
    workflows = root / ".github" / "workflows"
    if not workflows.is_symlink() and workflows.is_dir():
        found += sorted(
            f".github/workflows/{p.name}"
            for p in workflows.iterdir()
            if p.is_file() and not p.is_symlink() and p.suffix in (".yml", ".yaml")
        )
    return found


def _describe(rel: str, data: Any) -> list[Observation]:
    """Turn one parsed CI config into provenanced facts. Never trusts a value — the
    config is repo-authored, so these are observations about what it *declares*."""
    if not isinstance(data, dict):
        return [Observation(text="config is not a mapping", provenance=rel, severity="low")]
    if rel.startswith(".github/workflows/"):
        jobs = data.get("jobs")
        count = len(jobs) if isinstance(jobs, dict) else 0
        return [
            Observation(text=f"GitHub Actions workflow declaring {count} job(s)", provenance=rel)
        ]
    if rel == _GITLAB_CI:
        stages = data.get("stages")
        jobs = [k for k, v in data.items() if isinstance(v, dict) and not k.startswith(".")]
        obs = [Observation(text=f"GitLab CI declaring {len(jobs)} job(s)", provenance=rel)]
        if isinstance(stages, list):
            obs.append(
                Observation(
                    text=f"stages: {', '.join(str(s) for s in stages[:12])}", provenance=rel
                )
            )
        return obs
    return [Observation(text="CI configuration present", provenance=rel)]


def recon_ci(root: Path) -> DimensionResult:
    """Observe what CI the project declares."""
    files = _ci_files(root)
    fingerprint = _fingerprint.fingerprint_files(root, files)

    if not files:
        return DimensionResult.finding(
            DIMENSION,
            fingerprint,
            [Observation(text="no CI configuration found", provenance="tool:walk", severity="low")],
        )

    observations: list[Observation] = []
    unavailable: list[str] = []
    for rel in files:
        raw = _fs.read_text(root, rel, max_bytes=_MAX_CI_BYTES)
        if raw is None:
            unavailable.append(f"{rel} (unreadable or over the size cap)")
            continue
        data, reason = _safe_parse(raw)
        if reason is not None:
            unavailable.append(f"{rel} ({reason})")
            continue
        observations.extend(_describe(rel, data))

    return DimensionResult.from_parts(DIMENSION, fingerprint, observations, unavailable)
