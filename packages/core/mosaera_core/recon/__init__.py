"""The deterministic multi-dimensional recon engine (#41 / ADR-0047 §3).

Recon answers *"what is this project like?"* across eight dimensions — deps, CI,
tests, quality, cleanliness, security, structure, docs — using **deterministic tools
only**. It is the escalation ladder's largest application (ADR-0002): an LLM earns its
place at exactly one step of onboarding, **synthesis**, and that is #42. A dimension
here reaching for a model is a design smell to justify on its own MR.

**This engine is pure.** Every function *returns* a :class:`DimensionResult`; nothing
persists. The caller (#40's store) owns writing, which is what keeps this issue
parallel with it — recon has no memory/DB dependency, and ``mosaera_core.recon``
imports neither ``mosaera_memory`` nor ``mosaera_connectors``.

Three invariants hold across every dimension:

1. **Tri-state, deny-by-default** (§5). ``finding`` / ``clean`` / ``unavailable``. A
   tool that produced no verdict is named, never rounded down to clean —
   :class:`DimensionResult` raises rather than let an inconsistent state be built.
2. **Untrusted-clone discipline** (ADR-0033). Host tools go through
   :mod:`._tools`, which pins tool config by construction; scanners go through the
   sandbox; the walk is symlink-safe and bounded.
3. **Observations are data, never instruction** (§1). Every :class:`Observation`
   carries provenance; repo prose is quoted, attributed and framed as a claim.

Per-dimension fingerprints (§4) key each result to *just that dimension's inputs*, so
a lockfile edit re-recons ``deps`` and leaves the security scan alone.
"""

from __future__ import annotations

from .ci import recon_ci
from .cleanliness import recon_cleanliness
from .deps import recon_deps
from .docs import recon_docs
from .quality import recon_quality
from .security import recon_security
from .structure import recon_structure
from .tests import recon_tests
from .types import (
    DIMENSION_NAMES,
    DimensionResult,
    Observation,
    ReconStatus,
    quote_repo_text,
)

__all__ = [
    "DIMENSION_NAMES",
    "DimensionResult",
    "Observation",
    "ReconStatus",
    "quote_repo_text",
    "recon_ci",
    "recon_cleanliness",
    "recon_deps",
    "recon_docs",
    "recon_quality",
    "recon_security",
    "recon_structure",
    "recon_tests",
]
