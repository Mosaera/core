"""ConfigDataPack — parse-validate a config/data-only repo (the ``config-data`` type).

Runs ``CONFIG_CHECK_SRC`` (a Python ``-c`` program) over JSON/YAML/TOML files. Weakest signal
— only wins when nothing else matches.
"""

from __future__ import annotations

from mosaera_core.languages.base import CONFIDENCE_DATA, DetectContext
from mosaera_core.testreport import TestReport
from mosaera_core.validation import ValidationOutcome, ValidationPlan, build_config_step


class ConfigDataPack:
    name = "config-data"

    def interpret(self, outcome: ValidationOutcome) -> TestReport | None:
        """Always ``None`` — genuinely uncountable (#81); see ``StaticSitePack.interpret``.

        A parse check proves the files load; it has no per-check tally.
        """
        return None

    def detect(self, ctx: DetectContext) -> tuple[int, ValidationPlan] | None:
        data_files = sorted(
            e for e in ctx.listing if e.endswith((".json", ".yaml", ".yml", ".toml"))
        )
        if not data_files:
            return None
        step, count = build_config_step(data_files)
        return CONFIDENCE_DATA, ValidationPlan(
            "config-data",
            [step],
            f"config/data project: parsing {count} JSON/YAML/TOML file(s)",
            strength="shallow",  # it parses; that is not a correctness suite (ADR-0034)
        )
