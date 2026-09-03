"""The language-neutral shape of "what did this validation attempt actually find?" (#81).

A leaf: it imports nothing from the rest of ``mosaera_core``, so ``validation``, ``languages/``,
``progress`` and ``graph/`` can all depend on it without a cycle.

WHY THIS EXISTS. The engine's convergence machinery needs one number — how many checks are
failing right now — to answer "is this run getting closer?". Today it gets that by regexing
pytest's summary line out of raw stdout, which means a language whose runner phrases things
differently silently yields *no* signal, and the run falls to a fingerprint breaker that parks it
as thrash rather than concluding honestly (issue #81). ``bench/grade.py`` already solved the same
problem for GRADING by having every language's grader emit one uniform ``N passed, N failed``
line; this is that idea moved into the engine, but as a typed result rather than a string
convention a pack has to imitate.

DELIBERATELY MINIMAL. It carries what the breakers and the fix prompt consume, and nothing else.
``failed``/``errors`` are separate because pytest reports them separately and their SUM is the
convergence number (an errored test is not passing). ``total``/``passed`` are optional because
some runners report only failures.

``failing_ids`` is for HUMAN/agent display — it is capped by its producer and must never be used
as a security-relevant set. ``disposition._failing_test_files`` deliberately re-parses uncapped
for exactly that reason; do not wire it to this field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TestReport:
    """A structured validation result. ``None`` from a pack's ``interpret`` means "this pack
    genuinely cannot count", which is a different claim from ``TestReport(failed=0, ...)``."""

    # Not a pytest test class despite the name — without this pytest tries to COLLECT it and warns
    # on the __init__ dataclass generates. Un-annotated, so dataclass ignores it as a field.
    __test__ = False

    failed: int
    errors: int = 0
    total: int | None = None
    passed: int | None = None
    # Runner-native identifiers for the failing checks (pytest node ids, a .sql filename, …).
    # Display-capped by the producer; NOT an exhaustive set.
    failing_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def failing(self) -> int:
        """The convergence number: failures AND errors both mean "not passing"."""
        return self.failed + self.errors

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe projection for ``RunState`` (LangGraph checkpoints must serialize)."""
        return {
            "failed": self.failed,
            "errors": self.errors,
            "total": self.total,
            "passed": self.passed,
            "failing_ids": list(self.failing_ids),
            "failing": self.failing,
        }
