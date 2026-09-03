"""The LanguagePack seam.

The engine's workflow graph, delivery gate, ``run_plan``/``resolve_plan`` and the
``ValidationStep``/``ValidationPlan``/``ValidationOutcome`` dataclasses are all
language-agnostic (see ``validation.py``). The one thing that is genuinely language-tied
is **how to recognise a project and build its deterministic validation plan** — the
install / test / behaviour-smoke steps a sandbox actually runs. A ``LanguagePack`` owns
exactly that; everything else is reused unchanged.

Packs are tried against a registry (``languages/__init__.py``). Each ``detect`` returns a
**confidence-scored** plan or ``None`` to defer, and the highest-confidence match wins — so
a strong signal (a pytest config, a ``package.json``) beats a weak one (a stray source
file) regardless of registry order. This replaces the historical ``if/elif`` chain in
``detect_validation_plan`` whose fixed order made precedence implicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from mosaera_core.testreport import TestReport
from mosaera_core.validation import ValidationOutcome, ValidationPlan

if TYPE_CHECKING:
    from mosaera_core.tools.repo import Workspace


@dataclass(frozen=True)
class DetectContext:
    """Shared, precomputed inputs handed to every pack's ``detect`` — so packs don't each
    re-walk the workspace. Language-*specific* signals (a pytest config, a ``package.json``)
    are computed inside the owning pack from ``listing``/``workspace``, not here."""

    workspace: Workspace
    listing: list[str]
    install: bool
    install_timeout: int | None


# Confidence tiers — a stronger project signal wins over a weaker one. These reproduce the
# historical branch precedence (pytest > package.json > bare sources > html > data), now
# explicit instead of implied by if/elif order.
CONFIDENCE_SUITE = 100  # an explicit test config / suite (e.g. pytest config, a test file)
CONFIDENCE_MANIFEST = 80  # a package manifest (package.json, …)
CONFIDENCE_SOURCES = 40  # bare source files, no tests
CONFIDENCE_STATIC = 30  # html only
CONFIDENCE_DATA = 20  # config/data only


class LanguagePack(Protocol):
    """A language plugin. Supplies detection + validation-plan building **and the reading of that
    plan's result**; the engine reuses everything else. (Later stages add test-dir/glob,
    tester/coder prompt fragments, and a hygiene hook — see ADR-0032 / the plan.)"""

    name: str

    def detect(self, ctx: DetectContext) -> tuple[int, ValidationPlan] | None:
        """Return ``(confidence, plan)`` if this pack recognises the workspace, else ``None``."""
        ...

    def interpret(self, outcome: ValidationOutcome) -> TestReport | None:
        """Read this pack's own runner output into a structured result (#81).

        A pack builds the command, so a pack is the only thing that knows how to read what came
        back. Before this hook the engine regexed pytest's summary out of every language's stdout,
        so a runner that phrases things differently produced NO count — and the run fell to a
        fingerprint breaker that parks it as thrash instead of concluding honestly.

        **Return ``None`` when this pack genuinely cannot count** (a well-formedness check, a
        schema that failed to apply at all). That is an honest "no signal", NOT zero failures, and
        the graph routes it deliberately. Never fabricate a count to look measurable — a wrong
        count feeds the best-so-far breaker and can false-trip a converging run.
        """
        ...
