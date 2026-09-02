"""scan_node's deny-by-default security_status (ADR-0076), in isolation.

scan_node must NEVER emit a false "clean": an operator opt-out is "disabled", a scan that
was EXPECTED but could not run is "unavailable" (which the gate parks on), and only a real
scan forwards run_scan's tri-state verdict.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast, get_args

from mosaera_core.graph.nodes_review import scan_node
from mosaera_core.graph.state import RunState
from mosaera_core.sandbox import SandboxResult, SandboxWorker
from mosaera_core.tools.scan import GitleaksScanner, SecurityStatus
from mosaera_policies import evaluate_gate

_STATE = cast(RunState, {})
_GITLEAKS_JSON = '[{"RuleID":"aws-key","Description":"k","StartLine":1,"File":"/work/a.py"}]'


class _FakeSandbox(SandboxWorker):
    def __init__(self, exit_code: int, stdout: str) -> None:
        self._r = SandboxResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr="",
            duration_s=0.0,
            timed_out=False,
            network_isolated=True,
        )

    def run(
        self,
        cmd: Sequence[str],
        cwd: Path | None = None,
        timeout: int | None = None,
        image: str | None = None,
        readonly_work: bool = False,
    ) -> SandboxResult:
        return self._r

    def run_setup(
        self,
        cmd: Sequence[str],
        cwd: Path | None = None,
        timeout: int | None = None,
        image: str | None = None,
    ) -> SandboxResult:
        return self._r


def _ctx(*, scan_enabled: bool, scanners: Any, scan_sandbox: Any) -> Any:
    return SimpleNamespace(
        settings=SimpleNamespace(scan_enabled=scan_enabled),
        scanners=scanners,
        scan_sandbox=scan_sandbox,
    )


def test_scan_disabled_when_operator_opts_out() -> None:
    # scan_enabled=False → honest "disabled" (no gate deny), NOT a false "clean" — even
    # though scanners + a sandbox are present.
    ctx = _ctx(scan_enabled=False, scanners=[GitleaksScanner()], scan_sandbox=_FakeSandbox(0, "[]"))
    out = scan_node(ctx, _STATE)
    assert out["security_status"] == "disabled"
    assert out["findings"] == []


def test_scan_unavailable_when_expected_but_nothing_to_run_it() -> None:
    # scan_enabled=True but no scan sandbox → UNVERIFIED (the gate parks on this).
    no_sandbox = _ctx(scan_enabled=True, scanners=[GitleaksScanner()], scan_sandbox=None)
    assert scan_node(no_sandbox, _STATE)["security_status"] == "unavailable"
    # scan_enabled=True but no allowed scanner → likewise UNVERIFIED.
    no_scanner = _ctx(scan_enabled=True, scanners=[], scan_sandbox=_FakeSandbox(0, "[]"))
    assert scan_node(no_scanner, _STATE)["security_status"] == "unavailable"


def test_scan_forwards_the_run_scan_verdict() -> None:
    clean = _ctx(
        scan_enabled=True, scanners=[GitleaksScanner()], scan_sandbox=_FakeSandbox(0, "[]")
    )
    assert scan_node(clean, _STATE)["security_status"] == "clean"

    hit = _ctx(
        scan_enabled=True,
        scanners=[GitleaksScanner()],
        scan_sandbox=_FakeSandbox(1, _GITLEAKS_JSON),
    )
    out = scan_node(hit, _STATE)
    assert out["security_status"] == "findings"
    assert len(out["findings"]) == 1


def test_producer_to_gate_status_contract() -> None:
    # ADR-0076 red-team C: the gate (packages/policies) matches the string literal
    # "unavailable" while the producer vocabulary lives here (packages/core). Pin the
    # contract so a NEW producer status can't silently round to clean at the gate: (1) the
    # producer Literal is exactly what the gate was written against, and (2) across every
    # status scan_node can emit, ONLY "unavailable" adds the security_unverified deny.
    assert set(get_args(SecurityStatus)) == {"clean", "findings", "unavailable"}
    # Swept over findings_count too, added 2026-08-10. Before that this loop passed
    # findings_count=0 for EVERY status, so the `security_findings` branch it appears to cover was
    # never exercised — and the liveness audit then measured that reason firing 0 times in 2,483
    # runs with no test able to say whether it still worked. A sweep that pins one axis at its
    # inert value covers the other axis only in appearance.
    for status in {"clean", "findings", "unavailable", "disabled"}:  # + scan_node's "disabled"
        for count in (0, 1):
            d = evaluate_gate(
                tests_passed=True,
                reviewer_verdict="APPROVE",
                findings_count=count,
                iteration=1,
                max_iterations=3,
                security_status=status,
            )
            unverified = "security_unverified" in d.reasons
            assert unverified == (status == "unavailable"), (status, count)
            assert ("security_findings" in d.reasons) == (count > 0), (status, count)


# --- the branches that never enter this node at all (2026-08-07 audit) -------------------------


def test_a_gate_reached_WITHOUT_scanning_reports_unavailable_never_clean() -> None:
    """`scan_node` is the sole writer of `security_status`, and TWO edges reach the gate without
    it: `route_after_plan → gate` on `plan_unworkable_reason`, and `route_after_supervise → gate`
    on a give-up. The gate defaulted the absent key to `"clean"`, so ADR-0076's deny-by-default
    control reported a clean scan on a run that never scanned — *"we did not look"* spelled
    *"we looked and it was fine"*.

    Asserted on the ARGUMENT the gate builds, which is where the default lives. The neighbouring
    `validation_attempted` got this exact treatment on the same two branches the same day; this
    one had the opposite.
    """
    from mosaera_policies import evaluate_gate

    # A plan-unworkable stop: no scan_node, no findings, nothing else objectionable.
    blocked = evaluate_gate(
        tests_passed=True,
        reviewer_verdict="APPROVE",
        findings_count=0,
        autonomous=False,
        iteration=1,
        max_iterations=8,
        security_status="unavailable",
    )
    assert "security_unverified" in blocked.reasons

    # And the control still distinguishes a real clean scan.
    scanned = evaluate_gate(
        tests_passed=True,
        reviewer_verdict="APPROVE",
        findings_count=0,
        autonomous=False,
        iteration=1,
        max_iterations=8,
        security_status="clean",
    )
    assert "security_unverified" not in scanned.reasons
