"""Deterministic mid-run model escalation — the DNA escalation ladder, made runtime.

Start every role on its cheapest capable model. When a run fails to DELIVER, a
deterministic diagnosis attributes the bottleneck to exactly ONE role from the
terminal run state, and that role alone is bumped one tier up its escalation
ladder (`Settings.role_escalation`) — never the whole team (cost discipline). The
benchmark harness drives the diagnose -> escalate -> re-run loop around these pure
functions; nothing here calls a model. Benchmark-driven first cut (ADR-0016).

Lives in the bench package (not core proper) as benchmark-only tooling; the
diagnosis reuses the reviewer's verdict parser (`mosaera_core.verdict`), a pure
deterministic helper core owns.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from mosaera_core.config import Role, RoleModel, Settings
from mosaera_core.verdict import parse_reviewer_verdict


def diagnose_bottleneck(
    final_state: Mapping[str, Any], settings: Settings, *, acceptance_failed: bool = False
) -> Role | None:
    """Which role's MODEL is hanging up a run — a pure function of the terminal state's
    own honest signals (the gate's ``reasons``, the reviewer verdict, the per-loop stall
    counters, the tester flag) plus, for the benchmark, ``acceptance_failed`` (the run
    DELIVERED but the hidden grader shows it fails the real acceptance suite). Returns the
    role to escalate, or ``None`` when no model is attributable (don't escalate blindly).

    The run-state signals are produced deterministically by the graph; this only reads
    them. Priority is most-specific first."""
    reasons = set((final_state.get("gate_decision") or {}).get("reasons") or [])
    verdict = parse_reviewer_verdict(str(final_state.get("review", "")))
    escalate_reason = str(final_state.get("escalate_reason") or "").lower()
    stall_kinds = set((final_state.get("stall_by_kind") or {}).keys())

    # 0. Benchmark ground truth (grader-informed): the run SHIPPED but the hidden
    #    acceptance suite fails — a too-lenient tester let wrong code through (its own
    #    suite passed and the reviewer approved, so the run saw no failure). With no
    #    tester in the loop it is the coder that shipped wrong. This is the false-POSITIVE
    #    the run cannot see for itself; only the grader catches it.
    if acceptance_failed:
        return "tester" if settings.tester_enabled else "coder"

    # 1. The planner never produced a grounded plan → the PM model is the bottleneck.
    if "grounded plan" in escalate_reason or "no plan" in escalate_reason:
        return "pm"

    # 1b. The coder tampered with the tester's protected acceptance tests (ADR-0026). A
    #     model that edits the contract instead of satisfying it is out of its depth — the
    #     strongest "escalate the CODER" signal there is, and it must be read BEFORE the
    #     tester rule below: a tampered run that the reviewer nonetheless APPROVED would
    #     otherwise be misattributed to a "weak tester" when the fault is the coder's.
    if final_state.get("tests_modified"):
        return "coder"

    # 2. Tester over-specification (the MCB signal): validation fails, yet the reviewer
    #    APPROVES the code — the tester's own suite is what's blocking a correct change.
    #    Also fires on the explicit over-specification hand-raise (ADR-0015).
    if settings.tester_enabled and (
        ("validation_failed" in reasons and verdict == "APPROVE")
        or "over-specif" in escalate_reason
    ):
        return "tester"

    # 3. Validation fails and the reviewer is NOT vouching for the code → the coder
    #    could not produce a passing implementation.
    if "validation_failed" in reasons:
        return "coder"

    # 4. The reviewer keeps blocking / requesting changes. A tripped review-stall with
    #    the reviewer stuck on BLOCK points at the reviewer; otherwise the coder never
    #    satisfied the asks. Default to the coder (the producer).
    if reasons & {"reviewer_requested_changes", "reviewer_blocked", "reviewer_unknown"}:
        if "review" in stall_kinds and verdict == "BLOCK":
            return "reviewer"
        return "coder"

    # 5. Security findings the coder couldn't clear.
    if "security_findings" in reasons:
        return "coder"

    return None


@dataclass(frozen=True)
class Escalation:
    """The result of bumping one role up its ladder: the new settings to re-run with,
    the role escalated, and a human-readable path label for the scorecard/log."""

    settings: Settings
    role: Role
    label: str  # e.g. "tester: ollama/gpt-oss:20b -> anthropic/claude-sonnet-4-6"


def _tier_index(ladder: list[RoleModel], current: RoleModel) -> int:
    """The current tier's index on the ladder, or -1 when the current binding is not on
    the ladder (so the next tier is 0 — moving the role onto the ladder)."""
    for i, tier in enumerate(ladder):
        if tier.provider == current.provider and tier.model == current.model:
            return i
    return -1


def escalate_role(settings: Settings, role: Role) -> Escalation | None:
    """Bump ``role`` one tier up its escalation ladder, returning new settings bound to
    the stronger model — or ``None`` when the role has no ladder or is already at the top
    tier (nothing left to escalate; the caller should end honestly incomplete)."""
    ladder = settings.role_escalation.get(role) or []
    if not ladder:
        return None
    current = settings.role_model_for(settings.default_cost_mode, role)
    nxt = _tier_index(ladder, current) + 1
    if nxt >= len(ladder):
        return None
    target = ladder[nxt]
    if target.provider == current.provider and target.model == current.model:
        return None  # no-op tier — don't spin
    # The dynamic `{role}_model` field name is opaque to mypy, so type the overrides as
    # Any (the role Literal guarantees the field exists).
    overrides: dict[str, Any] = {
        "role_providers": {**settings.role_providers, role: target.provider},
        f"{role}_model": target.model,
    }
    escalated = replace(settings, **overrides)
    label = f"{role}: {current.provider}/{current.model} -> {target.provider}/{target.model}"
    return Escalation(settings=escalated, role=role, label=label)
