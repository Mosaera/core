"""Benchmark case registry.

A case bundles a fixed brief, a hidden acceptance grader, and the budgets the
scorecard's Efficiency dimension scores against. Cases live as versioned files
under this directory so a benchmark is reproducible across releases.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

_CASES_DIR = Path(__file__).parent
# Guided-posture cases (`#64`) live in their OWN directory, not beside the MCB cases.
# `bench --all` enumerates `available_cases()`, which globs every dir holding a `brief.md`, so a
# GMB case dropped in here would silently enlarge the suite and move the denominator of the
# standing baseline (91.7% clean-conclusion, false_ship 1.4%, n=72) — making it non-comparable
# with every figure recorded before it. Different question, different corpus, separate directory.
_GUIDED_CASES_DIR = Path(__file__).parent.parent / "guided_cases"

# Per-case overrides a case.toml may set (everything else is fixed by the harness).
_CASE_KEYS = frozenset(
    {
        "kind",
        "capability",
        "tier",
        "max_iterations",
        "budget_usd",
        "budget_tokens",
        "budget_iterations",
        "sandbox",
    }
)

# Kinds whose deliverable is Python code, so the craftsmanship/testing scorecard
# dimensions (Style/Types/Complexity/Cleanliness/Testing) apply.
_PYTHON_KINDS = frozenset({"python-cli", "python"})

# The capability taxonomy the suite rollup groups by. "greenfield" scaffolds from
# an empty repo; the rest start from a committed ``seed/`` repo the agent must read.
_CAPABILITIES = frozenset({"greenfield", "bug-fix", "feature", "refactor", "robustness"})
# Difficulty tiers (drives the suite matrix rows).
_TIERS = frozenset({"trivial", "moderate", "hard"})


def is_python_kind(kind: str) -> bool:
    return kind in _PYTHON_KINDS


@dataclass(frozen=True)
class BenchCase:
    id: str
    brief: str  # the task text handed to the governed loop
    grader_dir: Path  # hidden acceptance suite — NEVER placed in the run workspace
    seed_dir: Path  # committed starting repo; when absent the run is greenfield
    reference_dir: Path  # known-good solution — used ONLY to measure Proctor faithfulness (#57)
    kind: str = "python-cli"  # python-cli | python | static-site — scorecard applicability
    capability: str = "greenfield"  # taxonomy bucket for the suite rollup
    tier: str = "trivial"  # trivial | moderate | hard
    max_iterations: int = 6
    budget_usd: float = 1.0
    budget_tokens: int = 400_000
    budget_iterations: int = 6
    sandbox: str = "docker"

    @property
    def has_seed(self) -> bool:
        """True when the case ships a starting repo (existing-codebase task) rather
        than scaffolding greenfield from an empty repo."""
        return self.seed_dir.is_dir()


def available_cases(root: Path | None = None) -> list[str]:
    """Case ids under ``root`` (the MCB corpus by default).

    Callers that pass no root get exactly the MCB set they always got — `bench --all` depends on
    that, and so does every historical number it produced.
    """
    base = root or _CASES_DIR
    if not base.is_dir():
        return []
    return sorted(
        p.name
        for p in base.iterdir()
        if p.is_dir() and not p.name.startswith(("_", ".")) and (p / "brief.md").is_file()
    )


def available_guided_cases() -> list[str]:
    """The guided-posture corpus (`#64`) — deliberately not part of `available_cases()`."""
    return available_cases(_GUIDED_CASES_DIR)


def load_guided_case(case_id: str) -> BenchCase:
    """Load a guided-posture case (`#64`) — same format, separate corpus."""
    return load_case(case_id, root=_GUIDED_CASES_DIR)


def load_case(case_id: str, root: Path | None = None) -> BenchCase:
    """Load a case by id (e.g. ``MCB-01``). The brief is ``brief.md``, the hidden
    grader is ``grader/``, an optional ``seed/`` is the starting repo (existing-code
    cases), and an optional ``case.toml`` overrides kind/capability/tier/budgets."""
    base = root or _CASES_DIR
    case_dir = base / case_id
    brief_path = case_dir / "brief.md"
    if not brief_path.is_file():
        known = ", ".join(available_cases(base)) or "none"
        raise ValueError(f"unknown benchmark case {case_id!r}; available: {known}")
    overrides: dict[str, object] = {}
    toml_path = case_dir / "case.toml"
    if toml_path.is_file():
        overrides = {
            k: v
            for k, v in tomllib.loads(toml_path.read_text(encoding="utf-8")).items()
            if k in _CASE_KEYS
        }
    return BenchCase(
        id=case_id,
        brief=brief_path.read_text(encoding="utf-8"),
        grader_dir=case_dir / "grader",
        seed_dir=case_dir / "seed",
        reference_dir=case_dir / "reference",
        **overrides,  # type: ignore[arg-type]
    )
