"""The ESCALATE arm — the producer proved it cannot meet the bar (`#64` F49).

`disposition.py` owns the CLOSE-THE-GAP arm: when the only failing tests are the engine's own new
files, it may retract them and ship. This module is its opposite number, and was named there long
before it existed — `is_engine_blocked_give_up` routes a coder hand-raise away with *"the ESCALATE
arm, not the close-the-gap arm"* and nothing was on the other end.

`#64` measured the cost: 0 corruption in 6 runs, the producer diagnosing the broken bar correctly
(twice naming the exact contradiction unprompted), and every run re-scoped back at the same
unfixable wall until the iteration cap — then recorded as though the agent had flailed.

Where the other arm SHIPS, this one STOPS and ASKS. A hand-raise is a claim that the REQUIREMENT is
wrong, and only the operator owns requirements.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NamedTuple

from mosaera_policies import ReasonClass, reasons_of_class

from mosaera_core.eligibility import (
    _failing_test_files,
    _pre_existing_tests,
    effective_test_output,
)
from mosaera_core.progress import parse_failing_tests

# The ASK arm's OWN admission policy (ADR-0107), declared with the control it governs exactly as
# `reasons_of_class` intends — *"this module classifies, it does not decide admission. Which
# classes a given control admits is that control's policy and lives with the control"*.
#
# It differs from the SHIP arm's by one member, and the difference is the whole point. The SHIP arm
# (`eligibility._ADMISSIBLE_CLASSES`) answers *may this parked run be DELIVERED?* — deleting tests,
# committing, opening an MR — so "we never looked" must disqualify it. This arm answers *may I ASK
# the operator a question?*, whose entire effect is one `set_item_clarification` call writing a
# `direction`-kind clarification onto a backlog item; ADR-0091 enforces at the store boundary that
# such a proposal can never become acceptance text. Nothing ships, nothing is edited, nothing is
# approved. Asking is not an action with blast radius — it is the ABSENCE of one.
#
# Borrowing the SHIP arm's set to answer this question is what killed the ask: the give-up path
# bypasses `scan_node` (`graph/build.py`), so a not-run security reason is STRUCTURALLY GUARANTEED
# on the only path that can reach this arm, and the ask was refused 100% of the time. Measured live
# 2026-08-21 on run `20260821-185000-08c6c2`.
#
# DERIVED, never hand-written — a literal frozenset here would be ADR-0090's stale-list defect at a
# fourth origin, and no guard would catch it. `objection` and `tamper` remain excluded by omission,
# which is also what keeps `content_destroyed` out: the `tests_modified` check below does NOT cover
# it (ADR-0099 derives it from `destroyed_paths`), so only class membership does.
_ASK_ADMISSIBLE_CLASSES: tuple[ReasonClass, ...] = ("shortfall", "incidental", "not_run")


def ask_allowed_reasons() -> frozenset[str]:
    """Gate reasons that do NOT silence the ask (ADR-0107)."""
    return reasons_of_class(*_ASK_ADMISSIBLE_CLASSES)


# --- the ESCALATE arm: the producer proved it cannot meet the bar (#64 F49) ---------------------
# The sibling of the close-the-gap arm above, and its OPPOSITE in disposition: that arm retracts the
# engine's own wrong tests and ships; this one stops and asks a human. A hand-raise is a claim that
# the REQUIREMENT is wrong, and only the operator owns requirements.
#
# The arm was named in this module before it existed — `is_engine_blocked_give_up` routes a coder
# hand-raise away with "the ESCALATE arm, not the close-the-gap arm" — and nothing was on the other
# end. `#64` measured the cost: 0 corruption in 6 runs, the producer diagnosing the broken bar
# correctly (twice naming the exact contradiction), and every run re-scoped back at the same
# unfixable wall until the iteration cap.


class _Blocking(NamedTuple):
    """The blocking set AND why it is empty — computed once, so they cannot disagree."""

    paths: tuple[str, ...]
    reason: str


def _classify_blocking(final: Mapping[str, Any]) -> _Blocking:
    """The one rule. ``blocking_protected_tests`` is its ``.paths``; the reason is its ``.reason``.

    Written as a classifier rather than a predicate plus a parallel explainer because a second
    derivation of "why was this empty?" is exactly the drift that produced F61 — the same reason
    ``deny_finalizes`` returns a string, and ``_asserts_something_real`` is ``_real_assertions()
    > 0``.
    """
    protected = _pre_existing_tests(final) | {
        str(f).replace("\\", "/") for f in (final.get("authored_tests") or [])
    }
    if not protected:
        return _Blocking((), "this run has no protected tests — nothing here is unamendable")
    # The source is named EXPLICITLY here and nowhere else. This arm STOPS and asks a human, so it
    # may read the coder's own pinned run when the engine has none; the close-the-gap arm SHIPS and
    # must not inherit that by sharing a helper (#75 red team, FIX-NOW).
    failing = _failing_test_files(final, effective_test_output(final))
    if not failing:
        # NOT the same as "nothing qualifies": we could not look. Kept distinct because reading a
        # missing observation as a clean verdict is the vacancy shape this repo keeps measuring.
        return _Blocking((), "no validation output to read yet, so no test can be shown to block")
    if not failing <= protected:
        loose = ", ".join(sorted(failing - protected)[:3])
        return _Blocking(
            (),
            f"a failing test the producer COULD fix is in the way ({loose}) — the code may "
            "simply be wrong, and this must never become a way to blame the tests",
        )
    return _Blocking(tuple(sorted(failing)), "")


def blocking_protected_tests(final: Mapping[str, Any]) -> tuple[str, ...]:
    """The failing tests the producer is FORBIDDEN to edit, or ``()`` when the run does not qualify.

    Deny-by-default, and the mirror image of ``trapping_engine_tests``: that one needs the failures
    to be the engine's own NEW files (so they may be retracted); this one needs them to be files the
    producer may not touch (so re-planning cannot possibly help). Baselined paths
    (``integrity_baseline`` + ``proctor_edits``) and the Proctor's ``authored_tests`` are both
    protected from the coder, so either qualifies.

    The failing set must be NON-EMPTY and a SUBSET of that protected set. One coder-owned or
    repo-owned failing test ⇒ ``()`` — the code may genuinely be wrong, and this must never become a
    way to blame the tests for a real defect.

    Signature deliberately unchanged: ``apps/api`` and ``bench/cli`` call this on ``session.final``
    with no RunContext, and slice the tuple. ``blocking_refusal_reason`` carries the WHY.
    """
    return _classify_blocking(final).paths


def blocking_refusal_reason(final: Mapping[str, Any]) -> str:
    """WHY nothing is amendable, or ``""`` when something is. Diagnosis only — never a decision.

    Non-empty EXACTLY when ``blocking_protected_tests`` is empty, by construction rather than by
    care. Before this, an operator at an escalation gate with no offer could not tell "the code may
    genuinely be wrong" from "the engine has not validated yet" from "there is nothing protected
    here" — three different situations wearing one blank space (#79).
    """
    return _classify_blocking(final).reason


def blocking_test_ids(final: Mapping[str, Any]) -> tuple[str, ...]:
    """The blocking failures as ``file::function`` node ids — what the OPERATOR needs to see.

    ``blocking_protected_tests`` answers the guard's question (which PATHS are involved) and
    ``_failing_test_files`` throws the function half away to get there. The amendment gate asks a
    human a different question — *may this specific test be changed?* — and a path is the wrong
    grain for it: `tests/test_report.py` may hold eight tests of which one contradicts the item.

    Scoped to the blocking FILE set, so this can only ever narrow it, never widen it. Falls back to
    the bare path when a failure has no parseable function half.
    """
    files = set(blocking_protected_tests(final))
    if not files:
        return ()
    out: list[str] = []
    # The SAME output `blocking_protected_tests` narrowed the file set from, via the one shared
    # reader — parsing a different string here would let the paths and the node ids disagree.
    for node in parse_failing_tests(effective_test_output(final), cap=10_000):
        path = node.split("::", 1)[0].replace("\\", "/").removeprefix("./")
        if path in files and node not in out:
            out.append(node)
    return tuple(out) or tuple(sorted(files))


def ask_withheld_reason(final: Mapping[str, Any]) -> str:
    """Why the ASK must stay out even though `supervise_node` recorded a conflict — "" to proceed.

    Deliberately a SECOND evaluation, and deliberately not the same question. #68's bug was one
    predicate re-run against inputs that had drifted; this asks something supervise cannot answer,
    because on the give-up path the gate runs AFTER it. A security objection or a critic veto
    recorded downstream means the park stands on its own terms and the arm keeps out of it,
    evaluated at the only point it is knowable.

    This said "exactly the exclusion ADR-0075 red-teamed twice" until 2026-08-21. It was not:
    ADR-0075 predates this module by 14 days and this function by 29, and neither of its red-team
    rounds tested a security reason riding a park — see `is_oracle_conflict_escalation`. What DOES
    hold, and is the real reason a veto or a findings-bearing objection still silences the ask, is
    that those are POSITIVE objections: something looked and objected.

    The structural question ("is every failing test one the producer may not edit?") is NOT re-asked
    here: supervise answered it while the raise was live, and its answer rides `ask_blocking_tests`.
    """
    # TAMPER, and "we did not look" is never "clean" here either (red-team R1, 2026-08-21).
    #
    # `tests_modified` and `destroyed_paths` are written ONLY by `test_node`
    # (`graph/nodes_impl.py`), and a coder HAND-RAISE routes implement -> capture -> supervise,
    # bypassing it — the very same bypass this module cites for `scan_node`. So on the branch the
    # arm is DESIGNED to serve (`effective_test_output` falls back to the coder's own output
    # precisely for it), both keys are ABSENT, `.get()` is falsy, and the gate mints no tamper
    # reason either — leaving ADR-0107's class exclusion with nothing to exclude. A producer that
    # weakened a baselined test and then raised its hand got an operator-facing ask carrying its
    # own words, which is the laundering this function exists to stop.
    #
    # Absent ⇒ UNKNOWN ⇒ withhold, mirroring `scan_attempted`. Costs a real ask on a hand-raise
    # that never validated; that is the safe direction, and `blocking_protected_tests` needs a
    # failing set anyway, so the population is small.
    if final.get("tests_modified") or final.get("destroyed_paths"):
        return "a tamper verdict"  # never re-read as "the test was wrong"
    if "tests_modified" not in final or "destroyed_paths" not in final:
        return "no tamper check ran on this branch"
    verdict = final.get("outcome_verdict")
    if isinstance(verdict, dict) and verdict.get("vetoed"):
        return "a critic veto"
    gate = final.get("gate_decision") or {}
    # The ASK arm's own admission policy (ADR-0107) — NOT the SHIP arm's. `not_run` reasons are
    # admitted here and nowhere else: "the scanner never ran" is not an objection, and on the
    # give-up path it is guaranteed, so borrowing the ship set silenced this arm unconditionally.
    if set(gate.get("reasons") or []) - ask_allowed_reasons():
        return "a gate objection"
    return ""


def is_oracle_conflict_escalation(final: Mapping[str, Any]) -> bool:
    """The producer raised its hand AND every failing test is one it may not edit.

    Answers exactly one structural question — *is it impossible for the producer to fix what is
    failing?* — with no prose matching and no model judgment. A re-scope cannot change an acceptance
    bar, so when this holds the only honest moves are to stop and to ask the operator.

    Deny-by-default: a tamper, a critic veto, or any real gate objection means the park stands on
    its own terms and this arm keeps out of it.

    NOT "the exclusions ADR-0075 red-teamed twice" — that sentence stood here until 2026-08-21 and
    was false. ADR-0075 is dated 2026-07-23, this module was built 2026-08-06, and both of its
    red-team rounds attacked a false-SHIP (supersession deleting a human test, green-by-omission,
    the who-tests-the-test residual); neither mentions a security reason on this path, and none
    could have, because absent security defaulted to "clean" until 2026-08-07. A comment that
    invents a provenance is worse than no comment: it is the F62/F58 shape, where the next reader
    re-derives from a record that misstates itself.
    """
    raised = bool(
        final.get("coder_escalated") or final.get("escalate_reason") or final.get("blocked_reason")
    )
    # A supervise give-up records WHY in `give_up_reason` and clears the hand-raise channels, so the
    # engine-controlled prefixes are how a concluded escalation is still recognisable.
    concluded = str(final.get("give_up_reason") or "").startswith(
        ("escalation unresolved:", "blocked:")
    )
    if not raised and not concluded:
        return False
    if final.get("tests_modified"):
        return False  # a tamper is never re-read as "the test was wrong"
    verdict = final.get("outcome_verdict")
    if isinstance(verdict, dict) and verdict.get("vetoed"):
        return False  # the held-out critic found a real defect in the delivered code
    gate = final.get("gate_decision") or {}
    # Evaluated at exactly ONE point: `supervise_node`, at the moment it decides, which records the
    # outcome in `ask_blocking_tests` for the ask to read (ADR-0090 MR3, #68 — FIXED 2026-08-21).
    # It used to run again in `_try_escalate_arm` against a `gate_decision` that had moved on since
    # (written in nodes_review, never cleared on the deny -> plan edge), and the halves disagreed in
    # both directions: a stale objection blocked a legitimate stop, and a stale clean permitted a
    # stop that then could not ask — F62, where the operator got an honest stop and nothing to
    # answer. Membership is derived from REASON_CLASS (ADR-0090).
    if set(gate.get("reasons") or []) - ask_allowed_reasons():
        return False  # a real objection (tamper/security/reviewer/critic) rode the park
    return bool(blocking_protected_tests(final))
