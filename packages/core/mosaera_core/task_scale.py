"""Deterministic task-scale classification — is this item small enough for the reduced lane?

**What this is NOT.** ADR-0062 built an auto-loosen that lowered the ACCEPTANCE BAR when a run
struggled; it was red-teamed and REVERTED, with the standing rule "do not rebuild it in any
disguise". Nothing here touches the bar. The acceptance class is identical on both lanes: the same
suite runs, the same gate reads the same evidence model, and the same deterministic controls fire.
What the lane changes is how much MODEL EFFORT is spent producing that evidence — which nodes make
a model call, not what counts as passing.

**Why a classifier can be deterministic here.** The signal is not "is this task easy" (a judgement)
but "does this task name a change with no behavioural surface" (a syntactic property of the plan
and the brief). The second is decidable from text without a model, and it is deny-by-default: every
unrecognised shape is ``FULL``.

**The oracle question, stated plainly.** On the reduced lane the Proctor does not author acceptance
tests. That is the point — for "fix a typo in a docstring" there is no behaviour to assert, and a
Proctor asked to invent one produces either a vacuous test or a test about something else, which is
where the protected-test deadlock comes from (#127, 27% of LedgerCLI non-deliveries). The evidence
does not disappear; it changes shape:

- the repo's EXISTING suite still runs and must stay green — the change broke nothing;
- the diff must stay inside the scope the classifier certified (``diff_within_scope``), checked
  deterministically after the fact, not promised in advance.

For a non-behavioural change that pair is a stronger oracle than an invented test, and it is
measured rather than asserted. For anything else the classifier says FULL and none of this applies.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

# Verbs that introduce or alter BEHAVIOUR. One of these anywhere in the brief forces FULL, whatever
# else the text looks like — this is the deny-by-default term and it is deliberately broad.
# `fix`/`correct`/`update` are DELIBERATELY absent: they are the natural verbs for the very shapes
# this lane exists for ("fix a typo", "correct the docstring"), and including them made the lane
# unreachable — every accept-side test failed on its own verb. They are safe to omit only because a
# recognised non-behavioural shape is a REQUIRED precondition, so `fix` alone can never reach the
# lane: "fix the parser" matches no shape and is FULL before the verbs are consulted.
_BEHAVIOUR_VERBS = re.compile(
    r"\b(add|implement|support|handle|change|switch|convert|migrate|refactor|"
    r"rename|remove|delete|drop|replace|introduce|extend|optimi[sz]e|cache|validate|parse|"
    r"raise|catch|retry|sort|filter|format)\b",
    re.IGNORECASE,
)

# Shapes with no behavioural surface. A brief must match one of these AND avoid every behaviour verb
# outside the matched phrase. Kept SHORT on purpose: each entry is a claim that this shape cannot
# change what the program does, and a wrong entry is a false TRIVIAL, which is the dangerous
# direction. Grow it only with evidence.
_NON_BEHAVIOURAL = (
    re.compile(r"\b(comment|comments)\b", re.IGNORECASE),
    re.compile(r"\bdocstring(s)?\b", re.IGNORECASE),
    re.compile(r"\btypo(s)?\b", re.IGNORECASE),
    re.compile(r"\b(version|__version__)\s+(bump|string|number)\b", re.IGNORECASE),
    re.compile(r"\bbump\s+the\s+version\b", re.IGNORECASE),
)

# A path-ish token in the plan: at least one directory separator or a known source suffix.
_PATH = re.compile(r"[\w./-]+\.(?:py|md|toml|cfg|ini|txt|json|ya?ml)\b")

_MAX_FILES = 1
_MAX_ADDED_LINES = 12


@dataclass(frozen=True)
class Scale:
    """The verdict plus the WHY, because a deny-by-default branch must record why it denied — the
    rule this repo distilled from F61/F65/F69/F71. ``paths`` is the certified scope: the reduced
    lane's after-the-fact check refuses a diff that leaves it."""

    lane: str  # "reduced" | "full"
    reason: str
    paths: tuple[str, ...] = ()

    @property
    def reduced(self) -> bool:
        return self.lane == "reduced"


def classify(task: str, plan: str, repo_files: Iterable[str]) -> Scale:
    """Which lane this item belongs on. Deterministic, no model call, deny-by-default.

    ``repo_files`` is the real file listing: a path the plan invents does not certify a scope, and
    a plan naming nothing concrete cannot be scoped at all.
    """
    brief = f"{task}\n{plan}"
    matched = next((p for p in _NON_BEHAVIOURAL if p.search(task)), None)
    if matched is None:
        return Scale("full", "the brief names no recognised non-behavioural shape")

    # The behaviour-verb sweep runs over the brief with the matched phrase REMOVED, so "fix a typo"
    # is not disqualified by its own "fix" while "fix the parser and a typo" still is.
    residual = _BEHAVIOUR_VERBS.search(matched.sub(" ", task))
    if residual:
        return Scale("full", f"the brief also names a behaviour change ({residual.group(0)!r})")

    known = set(repo_files)
    named = sorted({p for p in _PATH.findall(brief) if p in known})
    if not named:
        return Scale("full", "the plan names no existing file, so no scope can be certified")
    if len(named) > _MAX_FILES:
        return Scale("full", f"the plan spans {len(named)} files (limit {_MAX_FILES})")
    return Scale("reduced", f"non-behavioural change scoped to {named[0]}", tuple(named))


def diff_within_scope(
    scale: Scale,
    changed: Mapping[str, Any] | Iterable[str],
    engine_authored: Collection[str] = (),
) -> str:
    """``""`` when the delivered diff stayed inside the certified scope, else WHY it did not.

    The classifier predicts; this MEASURES. A prediction that turns out wrong must cost the run its
    reduced lane, not its correctness — the caller promotes to the full lane on any non-empty
    return. That asymmetry is the whole safety argument: being wrong is expensive, never unsound.
    """
    if not scale.reduced:
        return ""
    touched = sorted(changed.keys() if isinstance(changed, Mapping) else set(changed))
    allowed = set(scale.paths) | set(engine_authored)
    outside = [p for p in touched if p not in allowed]
    if outside:
        return f"the change touched {', '.join(outside[:3])}, outside the certified scope"
    return ""


def _hunks_for(diff: str, only: Collection[str]) -> list[str]:
    """The diff lines belonging to ``only``'s files. A whole-diff count would charge the coder for
    text the ENGINE wrote — the authored oracle is part of the same diff and is not the change."""
    keep: list[str] = []
    current = ""
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            parts = line.split(" b/")
            current = parts[-1] if len(parts) > 1 else ""
        elif current in only:
            keep.append(line)
    return keep


def added_lines_within_budget(diff: str, only: Collection[str] = ()) -> str:
    """``""`` when the diff is as small as a non-behavioural change should be, else why not.

    A second, independent measure of the same claim. The scope check asks WHERE the change landed;
    this asks HOW MUCH — a 400-line rewrite of the one certified file is not a comment fix, and the
    path check alone would wave it through.

    ``only`` restricts the count to the certified files. Without it the engine's OWN authored oracle
    is counted against the coder's budget: on Approach B that produced a 3/3 park reading "the
    change touched tests/test_inert_ledger.py, outside the certified scope" — the engine refusing
    its own test. Measured 2026-08-29.
    """
    lines = _hunks_for(diff, only) if only else diff.splitlines()
    added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
    if added > _MAX_ADDED_LINES:
        return (
            f"the change added {added} lines "
            f"(a non-behavioural change is capped at {_MAX_ADDED_LINES})"
        )
    return ""
