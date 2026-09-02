"""QMB — the PM behaviour benchmark (does Quincy answer from recorded truth?).

The third bench, and the one measuring the seat nothing measured. `bench` (MCB) grades the CODER
on a good brief. `govbench` grades the deterministic intake DETECTORS — and its harness stubs the
PM outright, saying so in its own docstring: *"this measures the ROUTING, not the proposal… It does
not measure whether the PM would have detected anything"* (`govbench/harness.py:61-68`). Every
other PM test in this repo drives a scripted fake model and asserts plumbing.

So the bar this measures is the North Star's, quoted exactly because it is the thing being scored:

    "As a project develops, Quincy continuously learns it … and answers from RECORDED TRUTH,
    NEVER GUESSWORK … the decision chain Quincy cites IS the artifact chain.
    (DIRECTION: … the answering capability is unbuilt.)"

The architecture already calls that capability unbuilt. QMB exists to say *how far* unbuilt is, in
a number that can be re-run after a change, rather than in anecdotes.

**No LLM judge.** Every dimension is a pure function of objective inputs (`bench/scorecard.py:1-17`
holds the same line), and the dimensions were chosen for what a machine can check rather than for
what would be most interesting to know. The cost is real: QMB cannot score judgement, taste, or
whether an answer was *useful* — only whether it was grounded, safe, complete, consistent and
honest about its own limits. A suite that scored more by asking a model would be a suite whose
numbers could not be cited.

**Layering.** This package lives in `core` and therefore may not import `agents` or `api`
(`scripts/check_layer_imports.py`; the three grandfathered crossings are a shrink-only ratchet).
The two steps that genuinely belong to the app — asking the PM to propose, and validating a
changeset — arrive as callables, exactly as `intake_ask.run_intake_pass` takes them and for the
reason it states: "a harness wants the exception". The real wiring lives in `apps/api`.
"""

from mosaera_core.pmbench.arms import (
    PRIMARY_DIMENSION,
    ArmComparison,
    ArmReport,
    compare_arms,
    compare_by_dimension,
)
from mosaera_core.pmbench.cases import (
    CLASSES,
    QMBCase,
    available_pm_cases,
    load_pm_case,
)
from mosaera_core.pmbench.harness import CaseObservation, PMResponse, run_pm_case
from mosaera_core.pmbench.items import (
    ItemStat,
    Verdict,
    analyse,
    dimension_totals,
    suspected_broken,
)
from mosaera_core.pmbench.score import DIMENSIONS, PMScore, broken_cases, score_pm
from mosaera_core.pmbench.stats import Interval, discordant_needed, mcnemar_exact, wilson

__all__ = [
    "CLASSES",
    "DIMENSIONS",
    "PRIMARY_DIMENSION",
    "ArmComparison",
    "ArmReport",
    "CaseObservation",
    "Interval",
    "ItemStat",
    "PMResponse",
    "PMScore",
    "QMBCase",
    "Verdict",
    "analyse",
    "available_pm_cases",
    "broken_cases",
    "compare_arms",
    "compare_by_dimension",
    "dimension_totals",
    "discordant_needed",
    "load_pm_case",
    "mcnemar_exact",
    "run_pm_case",
    "score_pm",
    "suspected_broken",
    "wilson",
]
