"""The project-proof aggregate must never say something its own receipts do not.

A summary of sealed records is a new artifact, and its failure mode is silent: a number that looks
authoritative while disagreeing with the receipts it claims to summarize. Each test below pins one
of the five rules in `mosaera_api.proof`.
"""

from __future__ import annotations

import json
from typing import Any

from mosaera_api.proof import project_proof


class _Mem:
    """Minimal project store: the runs list plus raw receipt JSON per run."""

    def __init__(self, runs: list[dict[str, Any]], receipts: dict[str, str]) -> None:
        self._runs = runs
        self._receipts = receipts

    def project_detail(self, project_id: str) -> dict[str, Any] | None:
        return {"id": project_id, "runs": self._runs}

    def project_receipts(self, project_id: str) -> dict[str, str]:
        return dict(self._receipts)


def _run(
    run_id: str,
    item_id: int | None = 1,
    status: str = "APPROVED",
    at: str = "2026-08-10",
    **diag: Any,
) -> dict[str, Any]:
    """A run row. Integrity and scanner-availability read from HERE, not the receipt:
    `persist.receipt_json` carries the gate's verdict, while tampering, sealing and scanner
    availability are recorded on the run. The first cut of the aggregate read them off the receipt
    and reported "not recorded" on every delivery of a project that plainly records both — the
    rules held (it refused to guess) but the axis was asking the wrong row (live, 2026-08-23)."""
    base_diag: dict[str, Any] = {"tests_modified": False}
    base_diag.update(diag)
    return {
        "id": run_id,
        "item_id": item_id,
        "status": status,
        "created_at": at,
        "receipt_id": "seal",
        "diagnosis": base_diag,
    }


def _receipt(**over: Any) -> str:
    # The REAL receipt schema (`persist.receipt_json`): no tests_modified, no receipt_id, no
    # security_status. Those live on the run row, and a fixture that invented them here is how the
    # first cut of this module passed its tests while failing on live data.
    base: dict[str, Any] = {
        "action": "deliver",
        "reasons": [],
        "tests_passed": True,
        "reviewer_verdict": "APPROVE",
        "validation_strength": "suite",
        "tests_mutation_caught": True,
        "oracle_verified": True,
        "oracle_vouched_by": "structural_claims:c1",
    }
    base.update(over)
    return json.dumps(base)


def _axis(out: dict[str, Any], key: str) -> dict[str, Any]:
    return next(a for a in out["axes"] if a["key"] == key)


def test_a_fully_evidenced_delivery_reads_proven_on_every_axis() -> None:
    out = project_proof(_Mem([_run("r1")], {"r1": _receipt()}), "p1")
    assert out["delivered"] == 1
    for axis in out["axes"]:
        assert axis["proven"] == 1, axis["key"]
        assert axis["measured"] == 1


def test_rule2_absence_is_never_synthesized_into_proof() -> None:
    """An empty receipt on a bare run records nothing. Every axis must say `unknown` — not infer a
    verdict from the run having been APPROVED, and not read the absence of an objection as an
    approval.

    SECURITY is the one recorded exception and is asserted separately below: ADR-0107/0108 made its
    reason set TOTAL, so a gate with nothing to say about security emits no token and a gate that
    could not look says so explicitly. Under a total set, absence IS the verdict — and the run page
    reads it the same way, which is the point (one interpretation, not two)."""
    bare = {"id": "r1", "item_id": 1, "status": "APPROVED", "created_at": "2026-08-10"}
    out = project_proof(_Mem([bare], {"r1": json.dumps({})}), "p1")
    for axis in out["axes"]:
        if axis["key"] == "security":
            continue
        assert axis["proven"] == 0, axis["key"]
        assert axis["failed"] == 0, axis["key"]
        assert axis["unknown"] == 1, axis["key"]
        assert axis["measured"] == 0, axis["key"]


def test_security_absence_is_the_verdict_but_an_unscanned_tree_is_not() -> None:
    """The total-reason-set exception, both directions."""
    clean = project_proof(_Mem([_run("r1")], {"r1": _receipt()}), "p1")
    assert _axis(clean, "security")["proven"] == 1

    for token in ("security_not_attempted", "security_unverified", "security_stale"):
        out = project_proof(_Mem([_run("r1")], {"r1": _receipt(reasons=[token])}), "p1")
        axis = _axis(out, "security")
        assert (axis["proven"], axis["failed"], axis["unknown"]) == (0, 0, 1), token

    found = project_proof(_Mem([_run("r1")], {"r1": _receipt(reasons=["security_findings"])}), "p1")
    assert _axis(found, "security")["failed"] == 1

    # The scanner itself being unavailable is recorded on the run, and is never "clean".
    down = project_proof(
        _Mem([_run("r1", security_unavailable_cause="scanner image missing")], {"r1": _receipt()}),
        "p1",
    )
    assert _axis(down, "security")["unknown"] == 1


def test_rule3_an_unreadable_receipt_is_unknown_on_every_axis_never_proven() -> None:
    mem = _Mem([_run("r1"), _run("r2", item_id=2)], {"r1": _receipt(), "r2": "{ truncated"})
    out = project_proof(mem, "p1")
    assert out["delivered"] == 2
    for axis in out["axes"]:
        assert axis["proven"] == 1, axis["key"]
        assert axis["unknown"] == 1, axis["key"]
    assert out["sources"]["receipts_unreadable"] == ["r2"]


def test_rule3_a_missing_receipt_does_not_shrink_the_population() -> None:
    """The dishonest shortcut is to drop the delivery from the denominator — the panel then reads
    100% proven over work whose evidence nobody could find."""
    out = project_proof(_Mem([_run("r1"), _run("r2", item_id=2)], {"r1": _receipt()}), "p1")
    assert out["delivered"] == 2
    checks = _axis(out, "checks")
    assert (checks["proven"], checks["unknown"]) == (1, 1)


def test_rule4_the_source_set_is_disclosed_so_the_summary_can_be_reconciled() -> None:
    mem = _Mem([_run("r1"), _run("r2", item_id=2)], {"r1": _receipt()})
    sources = project_proof(mem, "p1")["sources"]
    assert sources["receipts_read"] == ["r1"]
    assert sources["receipts_unreadable"] == ["r2"]
    # Every delivery is accounted for in one list or the other — nothing vanishes between them.
    assert len(sources["receipts_read"]) + len(sources["receipts_unreadable"]) == 2


def test_rule5_an_unwired_instrument_is_not_a_failure() -> None:
    """`oracle_verified` and `oracle_vouched_by` were both absent before those fields were wired.
    Counting those as failures blames the engine for its own missing instrumentation."""
    out = project_proof(
        _Mem([_run("r1")], {"r1": _receipt(oracle_verified=None, oracle_vouched_by="")}), "p1"
    )
    ind = _axis(out, "independence")
    assert (ind["proven"], ind["failed"], ind["unknown"], ind["measured"]) == (0, 0, 1, 0)


def test_INDEPENDENCE_READS_THE_VERDICT_NOT_ONE_ROUTES_DIAGNOSTIC() -> None:
    """LOAD-BEARING, and this test previously asserted the BUG.

    `oracle_vouched_by` diagnoses ONE route — the structural-claims vouch (ADR-0092 §3), which
    applies only to BEHAVIOUR-PRESERVING changes. Every backlog item adds a feature, so that route
    never applies and always records `no_vouch:not_behavior_preserving`.

    Live on LedgerCLI 2026-08-24 the panel read independence **0 of 25** while every receipt carried
    `oracle_verified: true` and `oracle_legs.independent: true`. The gate said independence was
    established; the panel said nobody verified anything. It was reading one shut door and
    concluding nobody got in.

    The earlier version of this test asserted that a recorded `no_vouch` IS a failure, which is why
    the defect survived a mutation-checked suite: the pin held the wrong behaviour in place."""
    verified_but_route_not_applicable = _receipt(
        oracle_verified=True, oracle_vouched_by="no_vouch:not_behavior_preserving"
    )
    out = project_proof(_Mem([_run("r1")], {"r1": verified_but_route_not_applicable}), "p1")
    ind = _axis(out, "independence")
    assert (ind["proven"], ind["failed"], ind["measured"]) == (1, 0, 1)


def test_a_verdict_of_NOT_verified_is_still_a_failure() -> None:
    """The fix must not swing the other way: a gate that says independence was NOT established is a
    real failure, and must not be laundered into a pass."""
    out = project_proof(_Mem([_run("r1")], {"r1": _receipt(oracle_verified=False)}), "p1")
    ind = _axis(out, "independence")
    assert (ind["proven"], ind["failed"], ind["measured"]) == (0, 1, 1)


def test_proof_depth_needs_both_terms() -> None:
    """A full suite nothing was thrown at is not depth, and a caught mutation on a syntax check is
    not a suite."""
    suite_only = project_proof(
        _Mem([_run("r1")], {"r1": _receipt(tests_mutation_caught=None)}), "p1"
    )
    assert _axis(suite_only, "proof_depth")["unknown"] == 1
    shallow = project_proof(
        _Mem([_run("r1")], {"r1": _receipt(validation_strength="shallow")}), "p1"
    )
    assert _axis(shallow, "proof_depth")["failed"] == 1


def test_an_unreadable_reviewer_verdict_is_not_an_approval() -> None:
    out = project_proof(_Mem([_run("r1")], {"r1": _receipt(reviewer_verdict="UNKNOWN")}), "p1")
    review = _axis(out, "review")
    assert (review["proven"], review["failed"], review["unknown"]) == (0, 0, 1)


def test_one_entry_per_item_the_attempt_that_shipped() -> None:
    """Eight parks then a delivery is ONE delivery: remediated failures cannot colour the panel."""
    runs = [_run(f"p{i}", status="INCOMPLETE", at=f"2026-08-0{i + 1}") for i in range(8)]
    runs.append(_run("win", at="2026-08-09"))
    out = project_proof(_Mem(runs, {"win": _receipt()}), "p1")
    assert out["delivered"] == 1
    assert out["sources"]["receipts_read"] == ["win"]


def test_an_adhoc_delivery_counts_as_its_own_unit() -> None:
    out = project_proof(_Mem([_run("adhoc", item_id=None)], {"adhoc": _receipt()}), "p1")
    assert out["delivered"] == 1


def test_a_store_that_raises_yields_unknowns_not_proofs() -> None:
    class _Broken(_Mem):
        def project_receipts(self, project_id: str) -> dict[str, str]:
            raise RuntimeError("db down")

    out = project_proof(_Broken([_run("r1")], {}), "p1")
    assert out["delivered"] == 1
    for axis in out["axes"]:
        # No receipt could be read, so nothing is parsed and every axis — security included —
        # falls to the unreadable bucket. The exception above requires a receipt to read.
        assert axis["proven"] == 0, axis["key"]
        assert axis["unknown"] == 1, axis["key"]
