"""A real security finding must reach the gate and stop the run — the whole chain, in one test.

**Why this exists.** The liveness audit (2026-08-10) measured `security_findings` firing **0 times
in 2,483 runs**. Every link in the chain has a test and the chain has none:

    scanners find it       TESTED   test_scan.py plants a real PAT and a real shell=True
    scan_node -> status    TESTED   test_scan_node.py
    status -> gate reason  PARTLY   the contract sweep passes findings_count=0 for EVERY status,
                                    so the `security_findings` branch it appears to cover is
                                    never actually exercised
    findings -> refusal    UNTESTED

Link-by-link tests do not prove the chain. That is exactly how a gate reason can read zero forever
while every unit test passes — the shape this session found five times in one day.

This test is a POSITIVE CONTROL: a known-bad input the mechanism must reject. Corpus observation
can tell you a control *ran*; only a positive control tells you it can still *fire*.

No Docker and no model: the detector half is already covered by the docker-gated planted-vuln tests,
so this drives from a scanner report onward, which is the half that has never been exercised.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from mosaera_core.graph.nodes_review import scan_node
from mosaera_core.graph.state import RunState
from mosaera_core.sandbox import SandboxResult, SandboxWorker
from mosaera_core.tools.scan import GitleaksScanner
from mosaera_policies import evaluate_gate

# A well-formed gitleaks report carrying one real finding — the detector's own output shape.
_ONE_FINDING = '[{"RuleID":"aws-key","Description":"k","StartLine":1,"File":"/work/creds.py"}]'
_NO_FINDINGS = "[]"


class _Sandbox(SandboxWorker):
    def __init__(self, stdout: str) -> None:
        self._r = SandboxResult(
            exit_code=0,
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


def _ctx(stdout: str) -> Any:
    return SimpleNamespace(
        settings=SimpleNamespace(scan_enabled=True),
        scanners=[GitleaksScanner()],
        scan_sandbox=_Sandbox(stdout),
    )


def _gate_for(scan_result: dict[str, Any]) -> Any:
    """The gate, fed exactly as `nodes_review.gate_node` feeds it.

    `findings_count=len(state["findings"])` mirrors the production call site verbatim — the point
    of this test is the WIRING, so inventing a different expression here would test nothing.
    """
    return evaluate_gate(
        tests_passed=True,
        reviewer_verdict="APPROVE",
        findings_count=len(scan_result.get("findings") or []),
        iteration=1,
        max_iterations=6,
        oracle_verified=True,
        validation_strength="strong",
        security_status=str(scan_result.get("security_status") or "unavailable"),
    )


def test_a_real_finding_travels_from_the_scanner_to_a_refusal() -> None:
    """THE CHAIN. One scanner finding in, one refusal out, through the production path."""
    result = scan_node(_ctx(_ONE_FINDING), cast(RunState, {}))

    # link 1: the node classified it as findings, not clean and not unavailable
    assert result["security_status"] == "findings"
    assert len(result["findings"]) == 1, "the finding must survive into state, not just the status"

    # link 2: the gate refuses, and names the security reason
    decision = _gate_for(result)
    assert "security_findings" in decision.reasons
    assert decision.action != "deliver", "a run with a live security finding must not ship"


def test_the_same_chain_with_a_clean_scan_ships() -> None:
    """The other direction, without which the test above proves only that the gate refuses things.

    A mechanism that refuses everything scores identically to one that discriminates — the exact
    confusion the mutation-gate record warns about.
    """
    result = scan_node(_ctx(_NO_FINDINGS), cast(RunState, {}))
    assert result["security_status"] == "clean"
    assert result["findings"] == []

    decision = _gate_for(result)
    assert "security_findings" not in decision.reasons
    assert "security_unverified" not in decision.reasons
    assert decision.action == "deliver"


def test_a_finding_is_not_downgraded_by_an_approving_reviewer() -> None:
    """`security_findings` is an `objection`, so it never rides the reviewer-silence backstop.
    Pinned because the chain test above uses APPROVE — this proves that is not why it parked."""
    result = scan_node(_ctx(_ONE_FINDING), cast(RunState, {}))
    for verdict in ("APPROVE", "UNKNOWN", "REQUEST_CHANGES"):
        decision = evaluate_gate(
            tests_passed=True,
            reviewer_verdict=verdict,
            findings_count=len(result["findings"]),
            iteration=1,
            max_iterations=6,
            oracle_verified=True,
            validation_strength="strong",
            security_status=result["security_status"],
        )
        assert "security_findings" in decision.reasons, verdict
        assert decision.action != "deliver", verdict
