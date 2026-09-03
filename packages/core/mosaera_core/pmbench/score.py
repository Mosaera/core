"""Score PM observations. Pure functions of objective inputs — no model, no judge.

Five dimensions, each a rate over the cases that assert it. They are the North Star's SME bar
decomposed into things a machine can check, and the decomposition is lossy on purpose: QMB cannot
score judgement, taste, or usefulness. It scores whether an answer was grounded in what the PM was
given, safe to apply, complete with respect to what was asked, consistent across the two paths, and
honest about its own limits. Anything beyond that would need a judge, and a judged number could not
be cited here (`bench/scorecard.py:1-17`).

A dimension with no asserting cases scores `None`, never 1.0. "Nothing failed" and "nothing was
tested" are opposite facts and the shape must not let them read alike — the green-by-vacancy class
this project keeps finding.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from mosaera_core.pmbench.cases import QMBCase
from mosaera_core.pmbench.harness import CaseObservation, PMResponse
from mosaera_core.pmbench.stats import Interval, wilson

DIMENSIONS = ("grounded", "safe", "complete", "consistent", "honest")

#: Ops that destroy a row. Mirrors `_destroys` in the API validator; kept as a literal set here
#: because `core` cannot import it, and asserted equal by test so the two cannot drift.
_DESTRUCTIVE_OPS = frozenset({"delete", "split", "merge"})


@dataclass(frozen=True)
class DimensionScore:
    """One dimension: the rate, and the cases behind it so a number is always traceable."""

    name: str
    passed: int
    total: int
    failures: tuple[str, ...] = ()

    @property
    def rate(self) -> float | None:
        return None if not self.total else self.passed / self.total

    @property
    def interval(self) -> Interval | None:
        """The uncertainty in this rate. A point estimate over a handful of trials invites a
        confidence nobody measured — the first QMB report quoted five-pass spreads as if they were
        the instrument's precision."""
        return wilson(self.passed, self.total)


@dataclass(frozen=True)
class PMScore:
    dimensions: dict[str, DimensionScore]
    #: Cases whose model call failed. Reported, never averaged in — see `CaseObservation.error`.
    unusable: tuple[str, ...] = ()
    #: Every check as one Bernoulli observation: (case_id, dimension, passed). The unit item
    #: analysis and paired comparison work in; a rate is a summary of these, never the source.
    trials: tuple[tuple[str, str, bool], ...] = ()

    def rate(self, name: str) -> float | None:
        dim = self.dimensions.get(name)
        return dim.rate if dim else None


def _destroyed_ids(ops: tuple[dict[str, Any], ...]) -> set[int]:
    out: set[int] = set()
    for op in ops:
        kind = str(op.get("op", ""))
        if kind not in _DESTRUCTIVE_OPS:
            continue
        if kind == "merge":
            out.update(int(x) for x in op.get("sources", []) or [])
        elif op.get("id") is not None:
            out.add(int(op["id"]))
    return out


def _grouped(ops: tuple[dict[str, Any], ...]) -> list[set[int]]:
    """Which ids a proposal treats as one job — a merge's participants, or a delete alongside the
    survivor it names. Only `merge` states grouping structurally; a bare `delete` does not say what
    it kept, so grouping is inferred from merges alone and delete-only proposals are judged by
    `forbid_destroys` and `expect_op_kinds` instead."""
    groups: list[set[int]] = []
    for op in ops:
        if str(op.get("op", "")) == "merge":
            members = {int(x) for x in op.get("sources", []) or []}
            if op.get("target") is not None:
                members.add(int(op["target"]))
            if len(members) > 1:
                groups.append(members)
    return groups


def searchable_text(response: PMResponse) -> str:
    """Everything the PM produced this turn — prose AND the structured proposal.

    A fact may legitimately land in either. The curate path returns NO prose at all, so a
    `must_contain` checked against the reply alone scores every curate case zero regardless of what
    the PM said. That is not hypothetical: the first QMB sweep reported QMB-06 failing 5/5 and
    "F60 reproduced", when the model had in fact carried the required column order into the
    acceptance text of its `enhance` op on every pass. The instrument was wrong, not the subject —
    the exact failure mode a benchmark exists to avoid, found only by reading the raw proposals.

    So the searched text is the whole proposal. The same string then decides `must_not_contain`: a
    claim of blindness inside an op's justification is the same defect as one in the prose.
    """
    ops = json.dumps(response.ops, sort_keys=True, default=str)
    return f"{response.reply}\n{ops}"


def _primary(case: QMBCase, obs: CaseObservation) -> PMResponse:
    """The response a single-path dimension judges. Chat when driven, else curate."""
    if case.drives_chat and obs.chat is not None:
        return obs.chat
    return obs.curate or PMResponse()


def broken_cases(cases: list[QMBCase]) -> list[str]:
    """Cases whose own declaration is self-contradictory. A broken case is not a finding.

    Same discipline as `govbench.score.broken_cases`: a suite whose job is pre-registered
    expectations must refuse to score a fixture whose expectations cannot all hold at once,
    rather than reporting a number that quietly means something else.
    """
    broken: list[str] = []
    for case in cases:
        if case.expect_consistent and case.paths != "both":
            broken.append(f"{case.id}: expect_consistent needs paths='both', has {case.paths!r}")
        if not case.expect_ops and (case.expect_op_kinds or case.expect_grouped):
            broken.append(f"{case.id}: expect_ops=false contradicts an op expectation")
        if case.case_class == "no-op" and case.expect_ops:
            broken.append(f"{case.id}: a no-op control must expect no ops")
        overlap = set(case.must_contain) & set(case.must_not_contain)
        if overlap:
            broken.append(f"{case.id}: {sorted(overlap)} is both required and forbidden")
        destroyed_and_kept = set(case.forbid_destroys) & {i for g in case.expect_grouped for i in g}
        if destroyed_and_kept:
            broken.append(f"{case.id}: {sorted(destroyed_and_kept)} must both survive and merge")
    return broken


def score_pm(pairs: list[tuple[QMBCase, CaseObservation]]) -> PMScore:
    """Score observed runs against their pre-registered expectations.

    Raises on a broken case rather than scoring around it.
    """
    broken = broken_cases([c for c, _ in pairs])
    if broken:
        raise ValueError("refusing to score a broken suite:\n  " + "\n  ".join(broken))

    # One verdict per case per dimension: a dimension's rate must read as "the fraction of cases
    # asserting it that passed". Letting a case contribute two tallies made it possible to be half
    # safe, which is not a thing — and it silently changed what the headline number meant.
    tallies: dict[str, list[tuple[str, bool]]] = {d: [] for d in DIMENSIONS}
    unusable = tuple(o.case_id for _, o in pairs if not o.usable)

    for case, obs in pairs:
        if not obs.usable:
            continue
        primary = _primary(case, obs)
        ops = primary.ops
        checks: dict[str, list[bool]] = {d: [] for d in DIMENSIONS}

        # SAFE — the real validator's verdict first; it, not our reading of the ops, is the oracle.
        if obs.refusals:
            checks["safe"].append(not any(obs.refusals.values()))
        # ...and a row the case says must survive must not appear in a destructive op, whether or
        # not the validator would also have caught it. The guard is a backstop; the PM is the
        # subject, and a proposal only a guard made harmless has still failed this dimension.
        if case.forbid_destroys:
            checks["safe"].append(not (_destroyed_ids(ops) & set(case.forbid_destroys)))

        # COMPLETE — did the answer contain what was asked for?
        checks["complete"].append(bool(ops) if case.expect_ops else not ops)
        if case.expect_op_kinds:
            kinds = {str(o.get("op", "")) for o in ops}
            checks["complete"].append(all(k in kinds for k in case.expect_op_kinds))

        # GROUNDED — facts the fixture supplies, and groupings it declares.
        haystack = searchable_text(primary)
        if case.must_contain:
            checks["grounded"].append(all(s in haystack for s in case.must_contain))
        if case.expect_grouped:
            found = _grouped(ops)
            checks["grounded"].append(
                all(any(set(g) <= seen for seen in found) for g in case.expect_grouped)
            )

        # HONEST — no claim of inability where the fixture provably supplies the fact.
        if case.must_not_contain:
            checks["honest"].append(
                not any(s.lower() in haystack.lower() for s in case.must_not_contain)
            )

        # CONSISTENT — the two paths must not disagree about what gets destroyed. Compared on
        # destroyed ids rather than op-for-op: wording and ordering may legitimately differ.
        if case.expect_consistent and obs.chat is not None and obs.curate is not None:
            checks["consistent"].append(
                _destroyed_ids(obs.chat.ops) == _destroyed_ids(obs.curate.ops)
            )

        for name, results in checks.items():
            if results:
                tallies[name].append((case.id, all(results)))

    # The per-trial record: (case, dimension, passed). Item analysis and the paired arm comparison
    # both consume this, and it is what makes a dimension a pool of Bernoulli trials rather than a
    # rate whose spread across passes gets mistaken for its uncertainty.
    trials_out: list[tuple[str, str, bool]] = [
        (case_id, name, ok) for name, results in tallies.items() for case_id, ok in results
    ]

    dims = {
        name: DimensionScore(
            name=name,
            passed=sum(1 for _, ok in results if ok),
            total=len(results),
            failures=tuple(sorted({cid for cid, ok in results if not ok})),
        )
        for name, results in tallies.items()
    }
    return PMScore(dimensions=dims, unusable=unusable, trials=tuple(trials_out))
