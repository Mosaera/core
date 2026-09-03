"""The bench arm's standing decisions (ADR-0082 DoD-1), split out at the god-file ceiling.

One cohesive question: which ratified clauses does this bench run carry? See `_bench_clauses`.
"""

from __future__ import annotations

import os

from mosaera_core.clauses import Clause, make_clause

# The RATIFIED standing decisions the bench runs under by default (owner, 2026-08-12).
#
# `structural.body_statements=5` closes the gap ADR-0082 names with these exact cases: the briefs
# say "a short orchestrator" with no number, ADR-0072 forbids deriving the constant from prose,
# and the relative fallback accepted 13 statements where the graders demand <= 6/7. The value is
# 5, not 6, because the instruments disagree by one: `_body_stmts` excludes a leading docstring
# and the graders count it — clause=6 was MEASURED to false-ship twice through that gap (ledger
# E4), clause=5 delivered 18/20 with over-park 8→2 and 0 false ships (E5). Because the clause is
# WOVEN INTO THE BRIEF (`weave_criteria`), the agent aims at 5 and lands under both graders.
#
# Default-on is a measurement-methodology change: sweeps from this commit are not comparable to
# the 130-run 26-case baseline on refactor cases (recorded there and in the research ledger).
#
# THE SCOPE OF THAT WARNING WAS WRONG UNTIL 2026-08-24, and it cost a sweep. `weave_criteria` put
# this sentence into EVERY brief, not just the ones that left the number open, so the arm diverged
# from the baseline on all 26 cases — MCB-01 (greenfield, no structural ask anywhere in its brief)
# went 3-of-5 delivering to 0-of-5, parking at ~1.7M tokens each on trees the grader passed 8/8,
# because the reviewer enforced a criterion no oracle could ever mark satisfied. Weaving is now
# conditional on the clause actually binding (ADR-0082 amendment), so the incomparability really is
# confined to the refactor cases this comment always claimed: MCB-05 and MCB-15.
_RATIFIED_DEFAULT = "structural.body_statements=5"


def _bench_clauses() -> tuple[Clause, ...]:
    """The arm's standing decisions: the ratified default, unless the env says otherwise.

    Every clause cites `standards/module-ceiling` (repo-scoped, and it leaves exactly
    `structural.body_statements` open) — so the bench cannot express a clause the product would
    refuse. `MOSAERA_BENCH_CLAUSES` overrides for an A/B arm; the sentinel value ``none`` yields
    NO clauses (an empty string means "default" — before default-on it meant "none", and a
    silent meaning-flip is how an arm ends up measuring the wrong posture).
    """
    spec = os.environ.get("MOSAERA_BENCH_CLAUSES", "").strip()
    if spec.lower() == "none":
        return ()
    because = "bench arm (ADR-0082 DoD-1)"
    if not spec:
        spec = _RATIFIED_DEFAULT
        because = "owner ratification 2026-08-12 (ledger E5: delivered 7→18, over-park 8→2, fs 0)"
    out: list[Clause] = []
    for part in spec.split(","):
        name, _, value = part.strip().partition("=")
        if not name or not value.strip().isdigit():
            continue
        out.append(
            make_clause(
                standard_id="standards/module-ceiling",
                binds=name.strip(),
                value_kind="number",
                value_num=int(value),
                because=because,
                author="bench",
            )
        )
    return tuple(out)
