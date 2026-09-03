"""Deterministic detection of a BEHAVIOUR-PRESERVING task (a refactor).

A refactor's contract is "change the structure, not the observable behaviour". The Proctor
handles these badly today (ADR-0066): with no ``sandbox_exec`` it HAND-COMPUTES expected values
(a weak model gets them wrong), and it over-pins the loose "decompose into helpers" requirement to
specific private names — so a CORRECT refactor fails the authored suite and the run honest-parks.

This module answers ONE deterministic question — "is this task behaviour-preserving?" — so the
engine can inject the differential-golden-master + loose-structural authoring guidance for exactly
those tasks (``graph/nodes_plan.py``). No LLM, no I/O. Deny-by-default: it fires ONLY on an EXPLICIT
behaviour-preservation phrase in the trusted spec (task/plan/design), never on the bare word
"refactor" (a feature that merely mentions refactoring in passing must not trip it)."""

from __future__ import annotations

import re

# Explicit behaviour-preservation phrases. Deny-by-default: a match means the spec itself PROMISES
# the observable behaviour/output is unchanged — the signature of a pure refactor. Both spellings
# (behaviour/behavior). Kept tight: a false POSITIVE injects refactor guidance into a feature
# task, so we require a real preservation clause, not just a structural verb.
_PRESERVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"without\s+chang\w*\s+(its|the|any|their)?\s*(observable\s+)?behaviou?r"),
    re.compile(r"without\s+chang\w*\s+(its|the|any|their)?\s*(observable\s+)?(output|result)"),
    re.compile(
        r"(preserv\w+|keep\w*|retain\w*|unchang\w+|not?\s+chang\w*)\s+"
        r"(the\s+|its\s+|any\s+|all\s+|existing\s+)*(observable\s+)?behaviou?r"
    ),
    re.compile(r"behaviou?r[\s-]*preserv\w+"),
    re.compile(r"pure\s+refactor"),
    # "same/identical output|result|behaviour" NOT followed by "as ..." — a comparison
    # clause names a referent, and only a BASELINE referent (next pattern) is a
    # preservation promise. "same output as <another input path>" is a feature
    # CONSISTENCY clause, not a refactor promise: the #53 live-drive false positive
    # (Quincy's "stdin produces the same output as the command line" armed the
    # ADR-0072 structural oracle against a feature task).
    # The lookahead sits BEFORE the optional plural and covers it (`(?!s?\s+as\b)`) — with a
    # trailing `s?(?!\s+as\b)` the engine backtracks the plural to empty and the lookahead
    # inspects "s as...", letting "same results as <endpoint>" through (red-team finding).
    re.compile(r"(same|identical)\s+(observable\s+)?(behaviou?r|output|result)(?!s?\s+as\b)s?"),
    re.compile(
        r"(same|identical)\s+(observable\s+)?(behaviou?r|output|result)s?\s+as\s+"
        r"(before\b|it\s+(did|does)\b|"
        r"the\s+(original|existing|current|old|previous|prior|legacy|unrefactored"
        r"|pre[- ]?refactor\w*)\b)"
    ),
    re.compile(
        r"(output|result|behaviou?r)s?\s+(must|should)\s+(be\s+)?(the\s+)?"
        r"(identical|unchanged|same)"
    ),
    re.compile(r"no\s+(observable\s+)?behaviou?r(al)?\s+chang\w*"),
    re.compile(r"do\s+not\s+chang\w*\s+(any\s+)?(observable\s+)?behaviou?r"),
)


def is_behavior_preserving(task: str, plan: str = "", design: str = "") -> bool:
    """True when the trusted spec EXPLICITLY promises the observable behaviour/output is unchanged
    (a refactor). Deny-by-default — no explicit preservation clause → False, so the refactor-only
    authoring guidance is never injected into a feature/bug-fix task."""
    text = f"{task}\n{plan}\n{design}".lower()
    return any(p.search(text) for p in _PRESERVE_PATTERNS)


# Does the spec ask for the code to be BROKEN UP? Deny-by-default, and deliberately narrower than
# `_PRESERVE_PATTERNS`: "behaviour-preserving" and "is a decomposition" are DIFFERENT predicates,
# and treating the first as implying the second planted an unmeetable bar on 4 runs of the
# 0.6.3 sweep (docs/engineering-history/over-park-anatomy-2026-08-30.md). A comment fix and a
# version bump both promise "No behaviour changes" and decompose nothing; the red phase asserted
# `_module_level_functions(_real) > _module_level_functions(_frozen)` anyway and produced
# `assert 2 > 2` against trees the hidden grader passed 100%.
_RESTRUCTURE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # A bare "refactor" DOES ask for structural change, and the decomposition proxy is the red
    # phase this scaffold has always used for it. What it never meant is "any task that promises
    # behaviour preservation" -- a comment fix and a version bump promise exactly that.
    re.compile(r"refactor\w*"),
    re.compile(r"decompos\w+"),
    re.compile(r"extract\w*\s+(the|a|an|its|shared|common|duplicated|repeated)\b"),
    re.compile(r"(break|split)\w*\s+(it|them|this|the|up|down|out|apart)\b"),
    re.compile(r"(helper|smaller|separate)\s+(function|method|routine)s?\b"),
    re.compile(r"orchestrat\w+"),
    re.compile(r"pull\w*\s+(it|them|the|out)\b.*\binto\b"),
)


def requests_restructuring(task: str) -> bool:
    """True when the TRUSTED TASK asks for the code's STRUCTURE to change.

    Deny-by-default. Reads the task ONLY — never the PM's plan/design paraphrase, the same
    ADR-0066 contract `scaffold_if_refactor` holds: a lossy restatement must not be able to arm a
    structural bar the brief never asked for.

    Exists because a correct refactor need not add MODULE-LEVEL functions at all — it may extract a
    method, nest a helper, move code to another module, or simplify without extracting — so the
    scaffold's `>` assertion is unsound as a universal red phase. When this returns False the
    scaffold declines and the Proctor authors as usual, which is the deny-by-default contract that
    module already states for every other uncertainty.
    """
    low = task.lower()
    return any(p.search(low) for p in _RESTRUCTURE_PATTERNS)


def preservation_matches(text: str) -> list[str]:
    """The preservation spans matched in ``text`` (first match per pattern, deduped; empty list =
    not behaviour-preserving). A read-only accessor for callers that need to QUOTE what tripped
    the detector (the spec-lint, ADR-0073) — same patterns, so it can never drift from
    ``is_behavior_preserving``."""
    low = text.lower()
    spans: list[str] = []
    for pattern in _PRESERVE_PATTERNS:
        m = pattern.search(low)
        if m and m.group(0) not in spans:
            spans.append(m.group(0))
    return spans


# The differential golden-master + loose-structural authoring guidance for a REFACTOR (ADR-0066).
# Prompt-led: the Proctor authors with judgment (no mechanical rewrite — the reverted-auto-rewriter
# lesson). Injected into the authoring/repair instruction by the graph only when the guard is on AND
# the detector fires. Uses stdlib random/parametrize (hypothesis is not in the sandbox image).
_REFACTOR_GUIDANCE = """

## This is a behaviour-PRESERVING task (a refactor)
The contract is "change the structure, NOT the observable behaviour". Author the acceptance suite as
TWO complementary tests, and DO NOT hand-compute expected output values (you cannot run the code, so
you WILL get numbers/strings wrong and fail a correct refactor):

1. A DIFFERENTIAL golden-master (proves behaviour is PRESERVED). While the original code still
   exists (it does — you run before the coder), FREEZE it: `read_file` the module under change and
   `write_file` a VERBATIM copy to `tests/_frozen_<module>.py`. Then author a test that imports BOTH
   the real module (which the coder will change) AND the frozen copy, and asserts they return EQUAL
   results — for a spread of inputs generated with the stdlib `random` module (use a FIXED seed) or
   `@pytest.mark.parametrize`, PLUS every edge case the task names. Assert `real.fn(x) ==
   frozen.fn(x)`; NEVER a hand-computed literal. Do NOT use `hypothesis` (not installed) — use only
   stdlib `random`/`parametrize`.

2. A LOOSE STRUCTURAL test (proves the required change HAPPENED, so a do-nothing run fails). Assert
   the PROPERTY the task states — e.g. the entry function is now a short orchestrator and there are
   >= N module-level helper functions — via `ast`/`inspect`, which read STRUCTURE. Never assert on
   the source TEXT (a literal appearing in the file): the engine runs `ruff format` over the
   delivered source AFTER you author, so quotes/whitespace/import spelling are rewritten out
   from under you and such a test fails a CORRECT refactor. Assert the loose
   property; NEVER pin a specific private helper NAME (a correct refactor may name its helpers
   anything, so a name pin fails correct code). This structural test is what FAILS on the original
   code — it gives the suite its required red phase."""


def refactor_authoring_guidance(
    task: str, plan: str = "", design: str = "", *, enabled: bool
) -> str:
    """The refactor authoring guidance block, or "" when it does not apply. Empty unless ``enabled``
    (the ``behavior_preservation_guard`` knob) AND the task is detected behaviour-preserving — so a
    feature/bug-fix never sees refactor-only guidance."""
    if not enabled or not is_behavior_preserving(task, plan, design):
        return ""
    return _REFACTOR_GUIDANCE
