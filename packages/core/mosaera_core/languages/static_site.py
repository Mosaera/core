"""StaticSitePack — HTML well-formedness + local-asset checking (the ``static-site`` type).

The checker itself is a Python ``-c`` program (``HTML_CHECK_SRC``) run on the base image; the
*result* is language-neutral. Only wins when a repo has HTML but no stronger signal.
"""

from __future__ import annotations

from mosaera_core.languages.base import CONFIDENCE_STATIC, DetectContext
from mosaera_core.testreport import TestReport
from mosaera_core.validation import ValidationOutcome, ValidationPlan, build_html_step


class StaticSitePack:
    name = "static-site"

    def interpret(self, outcome: ValidationOutcome) -> TestReport | None:
        """Always ``None`` — genuinely uncountable (#81).

        A well-formedness check answers "does this parse?", not "how many checks fail?". There is
        no per-check tally to report and inventing one would feed the best-so-far breaker a number
        that means nothing. This is one of the two packs the honest no-signal path exists for.
        """
        return None

    def detect(self, ctx: DetectContext) -> tuple[int, ValidationPlan] | None:
        html_files = sorted(e for e in ctx.listing if e.endswith((".html", ".htm")))
        if not html_files:
            return None
        step, note = build_html_step(html_files)
        return CONFIDENCE_STATIC, ValidationPlan(
            "static-site",
            [step],
            f"static site: checking {note} for well-formedness and missing local assets",
            strength="shallow",  # well-formed markup is not a correctness suite (ADR-0034)
        )
