"""persist_run tri-state honesty: unavailable is never recorded as failed."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import mosaera_core
import pytest
from mosaera_core.config import Settings
from mosaera_core.persist import claim_rows, make_receipt_id, persist_run, receipt_json


class _FakeMemory:
    def __init__(self) -> None:
        self.ensured: list[str] = []
        self.runs: list[dict[str, Any]] = []
        self.decisions: list[tuple[str, str, str]] = []
        self.test_results: list[tuple[str, bool, str]] = []
        self.repo_changes: list[Any] = []
        self.artifacts: list[Any] = []

    def ensure_run(self, run_id: str, **kw: Any) -> None:
        self.ensured.append(run_id)

    def record_run(self, run_id: str, **kw: Any) -> None:
        self.runs.append({"run_id": run_id, **kw})

    def add_decision(self, run_id: str, kind: str, content: str) -> None:
        self.decisions.append((run_id, kind, content))

    def add_test_result(self, run_id: str, passed: bool, output: str) -> None:
        self.test_results.append((run_id, passed, output))

    def add_repo_change(self, *a: Any) -> None:
        self.repo_changes.append(a)

    def add_artifact(self, *a: Any) -> None:
        self.artifacts.append(a)

    def add_run_claims(self, run_id: str, rows: list[dict[str, Any]]) -> None:
        self.run_claims = [*getattr(self, "run_claims", []), (run_id, rows)]


def _settings() -> Settings:
    return Settings.from_env({})


def _persist(state: dict[str, Any]) -> _FakeMemory:
    mem = _FakeMemory()
    persist_run(mem, _settings(), "r1", source="src", branch="b", state=state, commit_sha="")  # type: ignore[arg-type]
    return mem


def test_unavailable_never_persists_as_failed() -> None:
    plan = {"project_type": "javascript", "reason": "no node offline", "steps": [], "results": []}
    mem = _persist({"task": "t", "tests_passed": None, "validation_plan": plan})
    assert mem.runs[0]["validation_status"] == "unavailable"
    assert mem.runs[0]["tests_passed"] is False  # back-compat boolean only
    # NO evidence row is fabricated; the plan decision carries the reason.
    assert mem.test_results == []
    kinds = [d[1] for d in mem.decisions]
    assert "validation_plan" in kinds
    stored = json.loads(next(d[2] for d in mem.decisions if d[1] == "validation_plan"))
    assert stored["reason"] == "no node offline"


def test_pass_and_fail_statuses() -> None:
    assert (
        _persist({"task": "t", "tests_passed": True, "test_output": "ok"}).runs[0][
            "validation_status"
        ]
        == "pass"
    )
    assert (
        _persist({"task": "t", "tests_passed": False, "test_output": "no"}).runs[0][
            "validation_status"
        ]
        == "failed"
    )


def test_per_step_evidence_rows() -> None:
    plan = {
        "project_type": "python-scripts",
        "reason": "syntax check only",
        "steps": [
            {"name": "py-compile", "cmd": ["python"]},
            {"name": "html-check", "cmd": ["python"]},
        ],
        "results": [
            {"name": "py-compile", "exit_code": 0, "timed_out": False, "ok": True, "output": "ok"},
            {
                "name": "html-check",
                "exit_code": 1,
                "timed_out": False,
                "ok": False,
                "output": "bad",
            },
        ],
    }
    mem = _persist(
        {"task": "t", "tests_passed": False, "test_output": "combined", "validation_plan": plan}
    )
    assert [(p, o.splitlines()[0]) for _, p, o in mem.test_results] == [
        (True, "[step py-compile: exit code 0]"),
        (False, "[step html-check: exit code 1]"),
    ]


def test_legacy_states_keep_single_row_fallback() -> None:
    mem = _persist({"task": "t", "tests_passed": True, "test_output": "[exit code 0]\nok"})
    assert mem.test_results == [("r1", True, "[exit code 0]\nok")]


def test_quality_decision_persisted_when_present() -> None:
    payload = json.dumps({"composite": 90, "dimensions": []})
    mem = _persist({"task": "t", "tests_passed": True, "quality": payload})
    assert ("r1", "quality", payload) in mem.decisions


def test_deliver_unverified_recorded_as_unverified_not_pass() -> None:
    mem = _persist({"task": "t", "tests_passed": True, "validation_unverified": True})
    assert mem.runs[0]["validation_status"] == "unverified"  # honest, not "pass"


def test_capability_limit_persisted_when_stalled() -> None:
    mem = _persist(
        {"task": "t", "tests_passed": False, "stalled": True, "stall_reason": "no progress: stuck"}
    )
    assert ("r1", "capability_limit", "no progress: stuck") in mem.decisions


def test_no_capability_limit_when_not_stalled() -> None:
    mem = _persist({"task": "t", "tests_passed": True})
    assert "capability_limit" not in [kind for _, kind, _ in mem.decisions]


def test_quality_decision_absent_for_nonpython_run() -> None:
    mem = _persist({"task": "t", "tests_passed": True})
    assert "quality" not in [kind for _, kind, _ in mem.decisions]


_GATE = {
    "action": "deny",
    "reasons": ["oracle_unverified"],
    "tests_passed": True,
    "reviewer_verdict": "APPROVE",
    "autonomous": False,
    "oracle_verified": False,
    "validation_strength": "suite",
    "unsatisfied_claims": ["c1"],
    "human_override": True,
    "oracle_vouched_by": "structural_claims:c2",
    "oracle_residual": "shape: proven · UNPROVEN: a mutation survives",
    "tests_mutation_caught": False,
    # WHICH leg refused. A realistic value, not `{}`: the receipt is the durable record a human
    # reconstructs a park from, and an empty dict would let the field exist while carrying nothing.
    "oracle_legs": {"blocked_by": ["mutation"], "mutation_raw": False, "independent": True},
}


def test_receipt_row_round_trips_all_fields() -> None:
    mem = _persist({"task": "t", "tests_passed": True, "gate_decision": dict(_GATE)})
    receipt = json.loads(next(c for _, k, c in mem.decisions if k == "receipt"))
    assert receipt == {
        "action": "deny",
        "reasons": ["oracle_unverified"],
        "reviewer_verdict": "APPROVE",
        "tests_passed": True,
        "oracle_verified": False,
        "validation_strength": "suite",
        "unsatisfied_claims": ["c1"],
        "human_override": True,
        "oracle_vouched_by": "structural_claims:c2",
        "oracle_residual": "shape: proven · UNPROVEN: a mutation survives",
        "tests_mutation_caught": False,
        "oracle_legs": {"blocked_by": ["mutation"], "mutation_raw": False, "independent": True},
    }


def test_receipt_preserves_none_as_null() -> None:
    gate = {**_GATE, "tests_passed": None, "tests_mutation_caught": None}
    payload = receipt_json({"gate_decision": gate})
    assert payload is not None
    receipt = json.loads(payload)
    # Tri-state honesty: "not measured" must survive as null, never a pass or a fail.
    assert receipt["tests_passed"] is None
    assert receipt["tests_mutation_caught"] is None


def test_receipt_absent_without_gate_decision() -> None:
    assert receipt_json({"task": "t"}) is None
    mem = _persist({"task": "t", "tests_passed": True})
    assert "receipt" not in [k for _, k, _ in mem.decisions]


def test_flat_gate_decision_string_unchanged() -> None:
    # The flat string is a parsing contract (lib/runs.ts parseGateDecision) — byte-identical.
    mem = _persist({"task": "t", "tests_passed": True, "gate_decision": dict(_GATE)})
    flat = next(c for _, k, c in mem.decisions if k == "gate_decision")
    assert flat == (
        "action=deny; reasons=oracle_unverified; verdict=APPROVE; tests_passed=True; "
        "validation_strength=suite; human_override=True"
    )


def test_claim_rows_join_and_unevaluable_default() -> None:
    claims = [
        {"id": "c1", "text": "sorts stably"},
        {"id": "c2", "text": "keeps API"},
        "not-a-dict",
    ]
    disps = [{"claim_id": "c1", "verdict": "satisfied", "oracle_ref": "pytest::test_sort"}]
    rows = claim_rows(claims, disps)
    assert [(r["claim_id"], r["verdict"], r["oracle_ref"]) for r in rows] == [
        ("c1", "satisfied", "pytest::test_sort"),
        ("c2", "unevaluable", ""),  # never silently satisfied
    ]


def test_persist_writes_claim_ledger_rows() -> None:
    mem = _persist(
        {
            "task": "t",
            "tests_passed": True,
            "claims": [{"id": "c1", "text": "x"}],
            "claim_dispositions": [{"claim_id": "c1", "verdict": "failed", "oracle_ref": "o"}],
        }
    )
    (run_id, rows) = mem.run_claims[0]
    assert run_id == "r1"
    assert rows[0]["verdict"] == "failed"


def test_make_receipt_id_is_deterministic_and_input_sensitive() -> None:
    a = make_receipt_id("r1", "sha", "0.6.0", '{"action":"deliver"}')
    assert a == make_receipt_id("r1", "sha", "0.6.0", '{"action":"deliver"}')
    assert len(a) == 64 and all(c in "0123456789abcdef" for c in a)
    # Any component change changes the seal — it is verifiable, not a surrogate key.
    assert a != make_receipt_id("r2", "sha", "0.6.0", '{"action":"deliver"}')
    assert a != make_receipt_id("r1", "sha2", "0.6.0", '{"action":"deliver"}')
    assert a != make_receipt_id("r1", "sha", "0.7.0", '{"action":"deliver"}')
    assert a != make_receipt_id("r1", "sha", "0.6.0", '{"action":"deny"}')


def test_persist_seals_the_run_when_a_receipt_exists() -> None:
    mem = _persist({"task": "t", "tests_passed": True, "gate_decision": dict(_GATE)})
    row = mem.runs[0]
    assert row["engine_version"] == mosaera_core.__version__
    expected = make_receipt_id(
        "r1", "", mosaera_core.__version__, receipt_json({"gate_decision": dict(_GATE)}) or ""
    )
    assert row["receipt_id"] == expected


def test_no_receipt_means_no_receipt_id() -> None:
    # Honest seal: a run that never carried a gate decision gets a version stamp
    # but no receipt id — there is no receipt for it to identify.
    mem = _persist({"task": "t", "tests_passed": True})
    row = mem.runs[0]
    assert row["engine_version"] == mosaera_core.__version__
    assert row["receipt_id"] is None


def test_quality_revise_trail_persisted() -> None:
    mem = _persist(
        {
            "task": "t",
            "tests_passed": True,
            "quality_revise_log": ["quality revise: Complexity 60/100 (composite 66)"],
        }
    )
    revises = [content for _, kind, content in mem.decisions if kind == "quality_revise"]
    assert revises == ["quality revise: Complexity 60/100 (composite 66)"]


def test_delivering_a_run_makes_no_embedding_call() -> None:
    """Every delivered run used to pay two Ollama embedding round-trips to fill
    `Artifact.embedding` — a column whose only readers, `similar_artifacts` and
    `similar_doctrine`, have zero production callers. Cross-run retrieval is DIRECTION
    (ADR-0084), not built, so the cost bought nothing.

    Asserted by SPYING the embedder rather than by reading the call sites: the old code swallowed
    every embedding failure in a bare `except`, so "no error" never meant "no call". The seam
    itself (`_embed`, the column, the store methods) is deliberately kept.
    """
    import mosaera_core.persist as persist_mod
    from mosaera_core.persist import persist_run

    calls: list[str] = []

    class _Mem:
        def __getattr__(self, name: str) -> Any:
            return lambda *a, **k: None

        def add_artifact(self, run_id: str, kind: str, content: str, embedding: Any = None) -> None:
            calls.append(f"artifact:{kind}:embedding={embedding is not None}")

    def _boom(settings: Any) -> Any:
        calls.append("EMBEDDER BUILT")
        raise AssertionError("the deliver path must not reach the embedder")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(persist_mod, "get_embeddings", _boom)
    try:
        persist_run(
            _Mem(),  # type: ignore[arg-type]
            SimpleNamespace(reports_dir=None),  # type: ignore[arg-type]
            "r-embed",
            source="local",
            branch="b",
            state={"diff": "--- a\n+++ b\n", "task": "t", "plan": "p", "report_path": "report.md"},
            commit_sha="abc",
        )
    finally:
        monkey.undo()

    assert "EMBEDDER BUILT" not in calls
    # …and the artifacts themselves are still written, with no embedding attached.
    assert "artifact:diff:embedding=False" in calls
    assert "artifact:report:embedding=False" in calls
