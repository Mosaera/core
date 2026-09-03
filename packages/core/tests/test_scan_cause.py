"""WHY a security scan produced no verdict (F84) — and proof that asking does not change it.

MEASURED 2026-08-09 over 193 runs: a scanner produced no verdict on **33 (17%)**, while
`security_findings` was raised **zero** times. Those 33 parked **29 deliveries the hidden grader
PASSED**, and `security_unverified` is the ONLY reason disqualifying **25** of them from Layer-2
class 2 — because class 2 admits `validation_failed` as a shortfall, which is its whole premise.
So a 17% AVAILABILITY rate, not a security judgment, is the largest single source of discarded
correct work in the corpus.

Four distinct causes collapsed into one indistinguishable `ran=False`. Naming one without measuring
it is precisely the defect F83 committed and then committed a second time inside its own fix. This
records the cause instead.

**Deny-by-default (ADR-0076) is not in question and is not touched.** "We did not look" still never
reads as "clean". The first test below is the load-bearing one: the instrumentation must be
provably INERT with respect to the verdict.
"""

from __future__ import annotations

from typing import Any

from mosaera_core.sandbox import SandboxResult
from mosaera_core.tools.scan import Finding, Scanner, run_one, run_one_with_cause, run_scan


class _Probe(Scanner):
    """A scanner whose outcome is dictated by the test, not by a real binary."""

    def __init__(self, name: str, complete: bool = True, findings: int = 0) -> None:
        self.name = name
        self._complete = complete
        self._findings = findings

    def command(self) -> list[str]:
        return ["probe"]

    def parse(self, stdout: str) -> list[Finding]:
        return [
            Finding(scanner=self.name, rule="r", path="p.py", line=1, severity="high", message="m")
            for _ in range(self._findings)
        ]

    def reported_completely(self, stdout: str) -> bool:
        return self._complete


def _result(**over: Any) -> SandboxResult:
    base: dict[str, Any] = {
        "exit_code": 0,
        "stdout": "[]",
        "stderr": "",
        "duration_s": 0.1,
        "timed_out": False,
        "network_isolated": True,
    }
    base.update(over)
    return SandboxResult(**base)


class _Sandbox:
    def __init__(self, result: SandboxResult | None = None, raises: bool = False) -> None:
        self._result = result or _result()
        self._raises = raises

    def run(self, *a: Any, **k: Any) -> SandboxResult:
        if self._raises:
            raise RuntimeError("sandbox is gone")
        return self._result


def _sandbox(result: SandboxResult | None = None, raises: bool = False) -> Any:
    """Typed `Any` on purpose: `_Sandbox` is a test double, not a `SandboxWorker` subclass, and
    only the `.run` call shape matters here."""
    return _Sandbox(result, raises)


# The four ways a scanner produces no verdict, and the cause each must record.
_CAUSES: list[tuple[str, Any, str]] = [
    ("sandbox raised", _sandbox(raises=True), "error:RuntimeError"),
    ("timed out", _sandbox(_result(timed_out=True)), "timeout"),
    ("missing binary", _sandbox(_result(exit_code=127)), "exit:127"),
    ("crashed", _sandbox(_result(exit_code=2)), "exit:2"),
]


def test_the_instrumentation_is_inert_with_respect_to_the_verdict() -> None:
    """THE load-bearing test. `scan.py` produces a security verdict, so the only safe version of
    this change is one that provably cannot alter it.

    `run_one` now delegates to `run_one_with_cause`, so a single origin decides what counts as a
    verdict and the two cannot drift. Every no-verdict path must still yield `ran=False` and every
    complete path `ran=True` — identical to before, with the cause carried alongside.
    """
    for label, sandbox, _cause in _CAUSES:
        findings, ran = run_one(_Probe("s"), sandbox)
        f2, ran2, _ = run_one_with_cause(_Probe("s"), sandbox)
        assert ran is False and ran2 is False, f"{label}: a no-verdict path reported a verdict"
        assert findings == f2

    ok = _sandbox(_result())
    assert run_one(_Probe("s", complete=True), ok)[1] is True
    assert run_one_with_cause(_Probe("s", complete=True), ok)[1] is True
    # An INCOMPLETE report is still no verdict — one unparseable file voids the whole repo's scan.
    assert run_one(_Probe("s", complete=False), ok)[1] is False


def test_each_cause_is_distinguishable() -> None:
    """The whole point: the 17% must be decomposable instead of guessed at."""
    seen = set()
    for label, sandbox, expected in _CAUSES:
        _, ran, cause = run_one_with_cause(_Probe("s"), sandbox)
        assert ran is False
        assert cause == expected, f"{label}: recorded {cause!r}, expected {expected!r}"
        seen.add(cause)
    # `incomplete` — a runnable exit code whose own report says it did not finish.
    _, ran, cause = run_one_with_cause(_Probe("s", complete=False), _sandbox(_result()))
    assert ran is False and cause == "incomplete"
    seen.add(cause)
    assert len(seen) == 5, f"causes collapsed into each other: {seen}"


def test_a_complete_scan_records_no_cause() -> None:
    _, ran, cause = run_one_with_cause(_Probe("s", complete=True), _sandbox(_result()))
    assert ran is True and cause == ""


def test_status_is_computed_exactly_as_before() -> None:
    """`unavailable_detail` must never enter the status expression. Deny-by-default stands:
    unavailable > findings > clean, and a partial report's findings still ride along."""
    ok = _sandbox(_result())
    assert run_scan([_Probe("a")], ok).status == "clean"
    assert run_scan([_Probe("a", findings=1)], ok).status == "findings"
    # One scanner without a verdict makes the WHOLE run unavailable, even beside a clean one.
    out = run_scan([_Probe("a"), _Probe("b", complete=False)], ok)
    assert out.status == "unavailable"
    assert out.unavailable == ("b",)
    assert out.unavailable_detail == (("b", "incomplete"),)
    # ...and it outranks findings, which is the deny-by-default ordering.
    assert run_scan([_Probe("a", complete=False, findings=1)], ok).status == "unavailable"


def test_zero_scanners_is_still_unavailable_with_a_named_cause() -> None:
    """ "We ran nothing" reported as "the repo is clean" is the inversion this guards."""
    out = run_scan([], _sandbox(_result()))
    assert out.status == "unavailable"
    assert out.unavailable_detail == (("(no scanner ran)", "no-scanner-configured"),)


def test_scan_node_emits_the_reason_without_touching_the_status() -> None:
    """The node's contract: `security_status` decides, the reason is advisory diagnostics."""
    import inspect

    from mosaera_core.graph import nodes_scan

    src = inspect.getsource(nodes_scan.scan_node)
    assert "security_unavailable_reason" in src
    # The reason must never be consulted to pick a status — it is written, never read, here.
    for branch in ("disabled", "unavailable"):
        assert f'"security_status": "{branch}"' in src


# --- "the scan failed" vs "no scan was attempted" (2026-08-10) ---------------------------------


def test_a_gate_reached_without_scanning_says_so() -> None:
    """`security_unverified` fires on BOTH — a scanner that produced no verdict, and a run that
    never scanned at all (two edges reach the gate without `scan_node`: plan-unworkable and
    give-up). Both left the reason EMPTY, so the record could not tell them apart.

    Measured over the corpus: 73 firings, ALL with an empty reason, which only the second
    explains — and F84's instrumentation had separately measured 0 scanner failures in 112 runs.
    """
    from mosaera_core.graph.nodes_scan import NEVER_SCANNED, security_unavailable_cause

    assert security_unavailable_cause({}) == NEVER_SCANNED


def test_a_scanner_that_ran_and_failed_keeps_its_own_cause() -> None:
    """The distinction only has value if the OTHER branch survives — F84's cause, intact."""
    from mosaera_core.graph.nodes_scan import security_unavailable_cause

    final = {"security_status": "unavailable", "security_unavailable_reason": "semgrep:timeout"}
    assert security_unavailable_cause(final) == "semgrep:timeout"


def test_a_clean_scan_has_no_cause_at_all() -> None:
    from mosaera_core.graph.nodes_scan import security_unavailable_cause

    assert security_unavailable_cause({"security_status": "clean"}) == ""


def test_the_run_record_carries_the_cause() -> None:
    """It must reach the RECORD, not just be derivable — the bench-reader defect this session
    found in verb-arc slice 3, where a value was computed and reached no stored artifact."""
    from mosaera_core.graph.nodes_scan import NEVER_SCANNED
    from mosaera_core.run_diagnosis import build_diagnosis

    assert build_diagnosis({})["security_unavailable_cause"] == NEVER_SCANNED
    assert "security_unavailable_cause" in build_diagnosis({"security_status": "clean"})


def test_nothing_the_gate_refuses_changed() -> None:
    """RECORDING ONLY. `security_unverified` fires exactly as before — deny-by-default
    (ADR-0076) is untouched; only the record can now say which cause it was."""
    from mosaera_policies import evaluate_gate

    for status in ("clean", "findings", "unavailable", "disabled"):
        d = evaluate_gate(
            tests_passed=True,
            reviewer_verdict="APPROVE",
            findings_count=0,
            iteration=1,
            max_iterations=6,
            security_status=status,
        )
        assert ("security_unverified" in d.reasons) == (status == "unavailable"), status


# --- ADR-0107: the cause finally reaches the REASON, not just the record ------------------------
#
# Everything above measures WHY a scan produced no verdict and then deliberately keeps that
# knowledge out of the gate — "Recording only", `run_diagnosis` its one consumer. That was the right
# call while every consumer of the classification was a SHIP decision.
#
# It stopped being right when a second consumer appeared that asks a different question. The ASK arm
# (`escalate_arm`) writes a clarification onto a backlog item — it ships nothing — and it borrowed
# the ship arm's admission set. Because `route_after_supervise -> gate` bypasses `scan_node`
# entirely, an absent scan was guaranteed on the only path that can reach the arm, and the ask was
# refused 100% of the time (measured live 2026-08-21, run `20260821-185000-08c6c2`).
#
# So the reason is split the way `validation_unavailable`/`validation_not_attempted` already was for
# these same two bypass edges: the gate still parks either way — this splits a message, never a
# permission — but the two now carry different CLASSES, and each arm decides for itself.


def _security_reasons(*, status: str, attempted: bool) -> list[str]:
    """A run that would otherwise ship, varying only the security inputs."""
    from mosaera_policies import evaluate_gate

    return list(
        evaluate_gate(
            tests_passed=True,
            reviewer_verdict="APPROVE",
            findings_count=0,
            security_status=status,
            scan_attempted=attempted,
            oracle_verified=True,
            validation_strength="suite",
            iteration=1,
            max_iterations=6,
        ).reasons
    )


def test_a_bypassed_scan_says_not_attempted() -> None:
    """The give-up / plan-unworkable edges: `scan_node` never ran, so there is no verdict to have
    an opinion about. `scan_attempted` is not an inference — that node is the sole writer of
    `security_status`, so the raw key's absence is the proof (`nodes_review` passes it)."""
    assert "security_not_attempted" in _security_reasons(status="unavailable", attempted=False)


def test_a_scanner_that_ran_and_produced_nothing_still_says_unverified() -> None:
    """The narrow change: only the never-entered case moves. A scanner that RAN and returned no
    verdict is still an objection — something was expected to speak and did not, and we cannot say
    why. This is the half that must NOT be relaxed."""
    assert "security_unverified" in _security_reasons(status="unavailable", attempted=True)


def test_the_split_parks_either_way() -> None:
    """Deny-preserving by construction, exactly as F39's split was: `_resolve` is a positive
    allowlist, so a NEW reason can only ever park. If this ever passes an unscanned tree, the split
    became a permission change and ADR-0076 was quietly relaxed."""
    for attempted in (True, False):
        assert _security_reasons(status="unavailable", attempted=attempted), (
            "an unscanned tree must never reach an all-clear gate"
        )


def test_clean_and_disabled_are_untouched_by_the_split() -> None:
    """The operator opt-out and a real clean scan pass through as before, whatever `scan_attempted`
    says — the split reads only the `unavailable` branch."""
    for status in ("clean", "disabled"):
        for attempted in (True, False):
            reasons = _security_reasons(status=status, attempted=attempted)
            assert not [r for r in reasons if r.startswith("security_")], reasons
