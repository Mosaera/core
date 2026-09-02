"""Delivery report: the audit artifact each run leaves behind."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mosaera_core import __version__ as _ENGINE_VERSION

# What a green validation on this run was actually worth (ADR-0034). Spelled out in the
# report so a reader never mistakes "tests passed" on a testless repo for evidence.
_STRENGTH_NOTE = {
    "suite": "a real test suite executed",
    "shallow": "the code only PARSES (compile/parse/typecheck) — not a correctness suite",
    "none": "nothing was executed",
    "unknown": "no validation plan reached the gate",
}


def _claims_lines(state: dict[str, Any]) -> list[str]:
    """`## Acceptance claims` when the run carried structured claims (ADR-0079), else nothing."""
    claims = state.get("claims") or []
    if not claims:
        return []
    lines = ["## Acceptance claims", ""]
    for c in claims:
        if not isinstance(c, dict):
            continue
        soft = "" if c.get("material", True) else " *(quality-soft, non-gating)*"
        lines.append(
            f"- `{c.get('id', '?')}` [{c.get('provenance', '?')} → {c.get('oracle_kind', '?')}]"
            f"{soft} {c.get('text', '')}"
        )
    lines.append("")
    return lines


def _plan_lines(state: dict[str, Any]) -> list[str]:
    plan = state.get("validation_plan")
    if not isinstance(plan, dict):
        return ["(not recorded)"]
    lines = [
        f"- Project type: {plan.get('project_type', 'unknown')}",
        f"- Reason: {plan.get('reason', '')}",
    ]
    results = plan.get("results") or []
    if results:
        parts = []
        for r in results:
            status = "TIMED OUT" if r.get("timed_out") else f"exit code {r.get('exit_code')}"
            parts.append(f"{r.get('name')} [{status}]")
        lines.append(f"- Steps: {', '.join(parts)}")
    else:
        lines.append("- Steps: (none — validation unavailable)")
    return lines


def _validation_line(state: dict[str, Any]) -> str:
    tp = state.get("tests_passed")
    if tp is None:
        reason = ""
        plan = state.get("validation_plan")
        if isinstance(plan, dict) and plan.get("reason"):
            reason = f" — {plan['reason']}"
        return f"- Validation: unavailable{reason}"
    return f"- Validation: {'passed' if tp else 'failed'}"


def write_report(
    reports_dir: Path,
    run_id: str,
    *,
    source: str,
    branch: str,
    workspace_root: Path,
    state: dict[str, Any],
    commit_sha: str = "",
) -> Path:
    approved = state.get("approved", False)
    status = "APPROVED" if approved else "NOT APPROVED"
    feedback = state.get("feedback", [])
    lines = [
        f"# Mosaera delivery report — run {run_id}",
        "",
        f"- Engine: v{_ENGINE_VERSION}",
        f"- Date: {datetime.now(UTC).isoformat(timespec='seconds')}",
        f"- Source repository: {source}",
        f"- Workspace clone: {workspace_root}",
        f"- Run branch: {branch}",
        f"- Status: **{status}**",
        f"- Commit: {commit_sha or '(none — no approved changes committed)'}",
        f"- Iterations: {state.get('iteration', 0)}",
        _validation_line(state),
        "",
        "## Task",
        state.get("task", ""),
        "",
        # Claim contract (ADR-0079 Wave 1): itemize the structured acceptance claims when the
        # run carried them — the first user-visible surface of the ledger. Absent claims ⇒ no
        # section (pre-claims reports render byte-identically).
        *_claims_lines(state),
        "## Plan",
        state.get("plan", ""),
        "",
        "## Coder summary",
        state.get("coder_summary", ""),
        "",
        "## Diff",
        "```diff",
        state.get("diff", "(empty)"),
        "```",
        "",
        "## Validation plan",
        *_plan_lines(state),
        "",
        "## Test output",
        "```",
        state.get("test_output", "(none)"),
        "```",
        "",
        "## Security scan findings",
        state.get("findings_text", "No security findings."),
        "",
        "## Review",
        state.get("review", ""),
    ]
    gate = state.get("gate_decision")
    if isinstance(gate, dict):
        reasons = gate.get("reasons") or []
        strength = str(gate.get("validation_strength", "unknown"))
        lines += [
            "",
            "## Gate decision",
            f"- Action: {gate.get('action', 'not recorded')}",
            f"- Reasons: {', '.join(str(r) for r in reasons) if reasons else '(none — all clear)'}",
            f"- Reviewer verdict: {gate.get('reviewer_verdict', 'UNKNOWN')}",
            f"- Validation strength: {strength} — {_STRENGTH_NOTE.get(strength, 'not recorded')}",
        ]
        if state.get("already_satisfied"):
            # #44 (ADR-0052): the Proctor's acceptance tests passed on the UNTOUCHED tree, so the
            # task may already be done. A green-pre-impl suite can't independently confirm the
            # requirement is met (the tests could miss it), so this is a signal for a human to
            # confirm — NOT a claim that the run delivered the feature.
            lines.append(
                "- Appears already satisfied: the acceptance suite is green on the untouched code "
                "— the task may already be done, but this could not be independently confirmed; a "
                "human should confirm the requirement is met"
            )
        # HOW the tamper surface was decided. Written since 21718bf8 and read by NOTHING until now:
        # a provenance string whose entire purpose is to stop an unprotected repo looking identical
        # to a protected one, invisible on every operator surface. `check_state_keys` cannot catch
        # that — it flags undeclared READS, not unread WRITES.
        surface = str(state.get("test_surface_resolution") or "")
        # ONLY these two. "inferred" alone fires on every greenfield target — 100% of runs on the
        # live instance, caught by live-validating the deploy — and a line that always appears is a
        # line nobody reads. The state key still records every case; the REPORT decides what earns
        # the operator's attention.
        if surface.startswith("UNGUARDED") or "DRIFT" in surface:
            lines.append(f"- Test surface: {surface}")
        tampered = state.get("tampered_paths") or []
        if tampered:
            # Name what the coder weakened, so a human at the gate sees exactly why the run
            # parked and can judge it — not an anonymous "validation failed" (ADR-0036).
            names = ", ".join(str(p) for p in tampered)
            lines.append(
                f"- Test integrity: TAMPERED — the run modified {names}; "
                "a green suite obtained by weakening the tests is not evidence"
            )
        if gate.get("human_override"):
            lines.append(
                "- Human override: yes — a human approved delivery despite the reasons above"
            )
        elif reasons and state.get("approved"):
            # Approved over blocking reasons by the AUTONOMOUS policy, not a person. Say so
            # plainly: this used to be branded a human override, which put a machine's
            # riskiest decision on the operator's name (ADR-0034).
            lines.append(
                "- Autonomous delivery: the runner approved this over the reasons above — "
                "no human decided it"
            )
    if feedback:
        lines += ["", "## Human feedback during the run"]
        lines += [f"- {f}" for f in feedback]
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"run-{run_id}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
