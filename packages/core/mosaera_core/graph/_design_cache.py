"""The design cache key (ADR-0084 §3).

Extracted from `nodes_plan` when the escalate arm landed: it is a pure function about what makes a
stored design STALE, not a node, and keeping it here keeps the node module under the ceiling.
"""

from __future__ import annotations

import hashlib

from mosaera_core.graph.state import RunState


def design_cache_key(state: RunState, plan: str) -> str:
    """Fingerprint of the inputs a stored design was authored from (ADR-0084 §3).

    Covers the TASK string (`build_run_task` flattens title + description + the woven acceptance
    criteria, so this is exactly the contract the design must satisfy — and it moves when a clause
    is ratified, which raw acceptance would miss), the PLAN it elaborates, and the run's standing
    CORRECTIONS (an operator instruction that post-dates a design makes it stale by definition —
    the case measured on 2026-08-06).

    The CHARTER is deliberately absent, and this is the key's known incompleteness: it is not
    reachable from the graph today (`RunContext` carries the brief and prior-item history, not the
    charter artifact, which only decompose and the PM chat read). Adding it is ADR-0084 (a). Until
    then a charter amendment alone will still serve a stale design — recorded rather than papered
    over.

    `project_context` is excluded on purpose: it changes whenever any earlier item delivers, so
    folding it in would invalidate every design on every delivery — churn, not freshness.

    NOT `progress.fingerprint`, deliberately: that one normalises for OUTCOME comparison — it
    lowercases and DROPS DIGITS so run-to-run noise (timings, counts, line numbers) doesn't change
    a stall signature. Here digits are the content that matters: an acceptance moving 200.00 to
    300.00, or a plan from 3 files to 5, must invalidate. Caught by test, not by inspection — the
    first draft reused it and keyed "T" and "T2" identically.
    """
    corrections = [str(c) for c in (state.get("corrections") or [])]
    parts = [str(state.get("task", "")), plan, *corrections]
    # \x1f (unit separator) cannot occur in these texts, so field boundaries stay unambiguous.
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()
