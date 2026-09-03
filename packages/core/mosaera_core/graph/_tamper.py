"""The tamper signals, computed in ONE place and written on EVERY branch that needs them.

These three keys — `tests_modified`, `tampered_paths`, `destroyed_paths` — are read as security
verdicts by the gate (`nodes_review`), by both disposition arms (`escalate_arm`, `eligibility`), by
the `tests_unmodified` claim oracle, and by the amendment guard. They were written by `test_node`
alone, and `implement -> capture -> supervise` never enters it.

So on the coder HAND-RAISE branch every one of those readers was consulting a key that had never
been written, and `.get()` returned falsy — which every one of them reads as *clean*. Red team
2026-08-21 found it twice: first as a vacuous exclusion (a tampering producer could reach the
operator-facing ask), then, after that was patched at the reader, as BOTH an over-block (the patch
withheld the ask on the very branch #68 exists to serve) and a still-live under-block (a verdict
from an earlier iteration, trusted after the producer tampered). Two rounds, same defect class, same
control — which is what tripped the STOP rule and escalated it here.

The lesson is the one the repo already learned for `test_output` (#75/F70, measured live twice on
LedgerCLI item 88): when a control fires on a branch, the EVIDENCE has to exist on that branch.
Hardening the reader cannot fix evidence that was never gathered. `capture_node` calls this
immediately before `supervise`, so the hand-raise branch gets a verdict that is both PRESENT and
FRESH — the over-block and the under-block close together, because they were the same bug.

One origin, two call sites: a copy in `capture_node` would be the second-origin shape (F71/F79) this
repo keeps paying for, on a signal where the two copies disagreeing is a security hole.
"""

from __future__ import annotations

import contextlib
from collections.abc import Mapping
from typing import Any

from mosaera_core.destruction import destroyed_paths
from mosaera_core.graph.context import RunContext
from mosaera_core.testintegrity import (
    INTEGRITY_ENUMERATOR,
    integrity_hash,
    is_collection_control,
    tampered_integrity,
)
from mosaera_core.tools.repo import tampered_files


def _raw_tampered_less_sanctioned(
    ctx: RunContext, tests_baseline: Mapping[str, str], operator_edits: Mapping[str, str]
) -> set[str]:
    """`tampered_files` over the run's OWN authored tests, minus what a human content-approved.

    `tampered_files` (raw-bytes space) takes no excuse parameter at all, while `operator_edits` is
    pinned in the INTEGRITY space — so a human write-gate approval of a change to a test the
    Proctor authored THIS run was flagged as tampering by a guard that could not see the sanction.
    That is F71's defect one origin over, found by the 2026-08-07 audit.

    Excused EXACTLY the way `tampered_integrity` excuses it and no wider: the current content must
    hash to the content the human approved, and collection-control paths are never excusable —
    human authority extends to a test's content, never to what gets collected (#65 round-2 rule).
    The shared helper is deliberately left alone; #75's red team showed that widening one leaks
    into the arm that ships.
    """
    flagged = set(tampered_files(ctx.workspace, tests_baseline))
    excused = {
        rel
        for rel in flagged
        if operator_edits.get(rel)
        and not is_collection_control(rel)
        and integrity_hash(ctx.workspace, rel) == operator_edits[rel]
    }
    return flagged - excused


def tamper_verdict(ctx: RunContext, state: Mapping[str, Any]) -> dict[str, Any]:
    """`tests_modified` / `tampered_paths` (+ `operator_edits` when any sanction applies).

    Pure with respect to the caller: reads only declared state keys and the workspace, and touches
    no node-local value, which is what let it lift out of `test_node` unchanged.
    """
    # The in-process sanctions win any collision with the durable ones — a live approval must not be
    # shadowed by a stale row a rehydrate replayed.
    operator_edits = {**(state.get("operator_edits") or {}), **ctx.operator_sanctioned}
    baseline = state.get("integrity_baseline") or {}
    complete = bool(baseline) and state.get("integrity_enumerator") == INTEGRITY_ENUMERATOR
    tampered = sorted(
        _raw_tampered_less_sanctioned(ctx, state.get("tests_baseline") or {}, operator_edits)
        | set(
            tampered_integrity(
                ctx.workspace,
                state.get("integrity_baseline") or {},
                # The tester authors tests AFTER the baseline is taken; those are legitimate
                # and governed by their own protected-path guard — don't double-flag them.
                ignore=state.get("authored_tests") or [],
                # The Proctor's up-front, coder-blind repairs to PRE-EXISTING tests (#54, ADR-0058):
                # excuse EXACTLY the Proctor's post-edit content (integrity hash space). Any OTHER
                # change to those paths — a later coder re-weakening — still trips deny-by-default.
                proctor_edits=state.get("proctor_edits") or {},
                # The operator's own write-gate approvals (F63, #65) — same content-pinned rule,
                # different authority. Empty unless a HUMAN approved a write, so autonomous
                # behaviour is byte-identical.
                operator_edits=operator_edits,
                # Is this baseline COMPARABLE to what the enumerator returns now? A stamp that is
                # absent or from an older rule set means the baseline was built over a different
                # path set, so "enumerated but not baselined" stops implying "created during this
                # run". Suppresses ONLY the new-collection-control branch; the baselined-path
                # comparison above runs unchanged.
                baseline_complete=complete,
            )
        )
    )
    out: dict[str, Any] = {"tests_modified": bool(tampered), "tampered_paths": tampered}
    if baseline and not complete:
        # PRESENT ONLY WHEN RELEVANT (the `operator_edits` / `destruction_verdict` convention: an
        # empty value would read as "checked, nothing to say"). The operator is told the coverage is
        # narrowed rather than being handed either a false tamper verdict or silence.
        out["integrity_baseline_partial"] = (
            f"this run's tamper baseline predates an engine upgrade and covers {len(baseline)} "
            "paths; a collection-control file created after run start is not detected for this run"
        )
    if operator_edits:
        # Surface the operator's sanctions so the amendment is auditable — it rides the report and
        # the diagnosis rather than living only in a tool closure.
        out["operator_edits"] = dict(operator_edits)
    return out


def destruction_verdict(ctx: RunContext) -> dict[str, Any]:
    """`destroyed_paths`, or NOTHING when the tree could not be read.

    Absence is load-bearing and deliberate (`bench/cli.py` depends on it): it distinguishes
    "checked, nothing destroyed" from "could not check". The gate reads truthiness, so an
    uncheckable tree fails OPEN there — an honest limit recorded rather than hidden, and every real
    run works on a git clone that fails validation long before the gate.
    """
    out: dict[str, Any] = {}
    with contextlib.suppress(Exception):
        out["destroyed_paths"] = destroyed_paths(ctx.workspace, ctx.workspace.diff_all())
    return out


def tamper_signals_for_handraise(ctx: RunContext, state: Mapping[str, Any]) -> dict[str, Any]:
    """Both verdicts for a branch that never reaches `test_node` — or `{}` if they can't be taken.

    FAILS CLOSED, and that is the whole point of the separate entry point: `ask_withheld_reason`
    treats an absent key as UNKNOWN and withholds, so a torn clone costs a question rather than
    granting a tampering producer one.

    NOT ATOMIC, and the difference is observable (red team R3). `destruction_verdict` suppresses
    internally, so if hashing succeeds and `diff_all()` does not — a git lock, a torn index — the
    tamper keys are written and `destroyed_paths` is not. `ask_withheld_reason` then reports "no
    tamper check ran" for a branch where it ran and came back clean. The direction is right and the
    reason is wrong; recorded rather than smoothed over, because the honest limit is the point.
    """
    out: dict[str, Any] = {}
    with contextlib.suppress(Exception):
        out.update(tamper_verdict(ctx, state))
        out.update(destruction_verdict(ctx))
    return out
