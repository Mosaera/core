"""#60 refactor vouching (Wave 3, stage 5) — offline, the MCB-14-wall fixture family.

A satisfied material structural claim joins the oracle-independence disjunction ONLY when
every guard holds: the TRUSTED task states behaviour preservation, the tamper guard is clean,
and the claim is proven-satisfied. Each test breaks exactly one guard and asserts the vouch
dies (deny-by-default), plus the reducer's kind-restriction (no double-counting existing
oracles). Drives the REAL gate_node with `request_approval` captured.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from git import Repo
from mosaera_core.claim_oracles import satisfied_structural_claim_ids
from mosaera_core.config import Settings
from mosaera_core.tools.repo import clone_repo

PRESERVING_TASK = (
    "Refactor accounts.py to remove the duplication without changing any observable behaviour."
)
FEATURE_TASK = "Add a search command that prints matching notes."


@pytest.fixture
def workspace(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    repo = Repo.init(src, initial_branch="main")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "T")
        cw.set_value("user", "email", "t@example.com")
    (src / "a.py").write_text("x = 1\n", encoding="utf-8")
    repo.index.add(["a.py"])
    repo.index.commit("init")
    return clone_repo(str(src), tmp_path / "ws", "vouch-test")


def _claim(kind: str = "ast_transformation_contract", material: bool = True) -> dict[str, Any]:
    return {
        "id": "14-c2",
        "item_id": 14,
        "text": "extract the shared validation into one module-level helper that both call",
        "provenance": "ENTAILED",
        "oracle_kind": kind,
        "material": material,
    }


def _drive_gate(
    workspace: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    task: str = PRESERVING_TASK,
    claims: list[dict[str, Any]] | None = None,
    verdict: str = "satisfied",
    tests_modified: bool = False,
) -> tuple[Any, dict[str, Any]]:
    """Run the real gate_node; return (captured GateDecision-dict, captured payload)."""
    import mosaera_core.graph.nodes_review as nr

    claims = claims if claims is not None else [_claim()]
    monkeypatch.setattr(
        nr,
        "evaluate_claims",
        lambda cs, ws, st: [
            {"claim_id": str(c["id"]), "verdict": verdict, "oracle_ref": "test"} for c in cs
        ],
    )
    captured: dict[str, Any] = {}

    def fake_approval(action: str, summary: str, payload: dict[str, Any]):
        captured.update(payload)
        return SimpleNamespace(approved=True, feedback="", actor="autonomous")

    monkeypatch.setattr(nr, "request_approval", fake_approval)
    ctx = SimpleNamespace(
        settings=Settings(oracle_coverage=False),
        workspace=workspace,
        run_id="vouch-test",
        test_cmd=None,
        max_iter=8,
    )
    state = {
        "task": task,
        "tests_passed": True,
        # strength "suite" is REQUIRED for oracle_unverified to be reachable at all —
        # without it every assertion here is vacuous (the first version of this file was).
        "validation_plan": {"strength": "suite"},
        "review": "VERDICT: APPROVE",
        "claims": claims,
        "tests_modified": tests_modified,
        "diff": "+++ b/accounts.py\n+def _validate(): ...\n",
        "iteration": 1,
    }
    out = nr.gate_node(ctx, state)  # type: ignore[arg-type]
    return out["gate_decision"], captured


def test_satisfied_structural_claim_vouches_a_detected_refactor(
    workspace: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    gd, payload = _drive_gate(workspace, monkeypatch)
    assert "oracle_unverified" not in gd["reasons"]  # the wall falls
    assert payload["oracle_vouched_by"] == "structural_claims:14-c2"  # and says why


def test_no_preservation_clause_no_vouch(workspace: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    # Guard 1: the TRUSTED task must state behaviour preservation — a feature task never
    # vouches on shape (shape is not correctness for new behaviour).
    gd, payload = _drive_gate(workspace, monkeypatch, task=FEATURE_TASK)
    assert "oracle_unverified" in gd["reasons"]
    # the field is now SELF-EXPLAINING (never empty): it names the guard that said no
    assert payload["oracle_vouched_by"] == "no_vouch:not_behavior_preserving"


def test_tampered_tests_kill_the_vouch(workspace: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    # Guard 2: a coder who weakened tests earns nothing from a pretty AST.
    gd, _ = _drive_gate(workspace, monkeypatch, tests_modified=True)
    assert "oracle_unverified" in gd["reasons"] or "tests_tampered" in gd["reasons"]


def test_unbound_claim_never_vouches(workspace: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    # Guard 3: proven-satisfied only — unbound/unevaluable grant nothing.
    for verdict in ("unbound", "unevaluable", "failed"):
        gd, _ = _drive_gate(workspace, monkeypatch, verdict=verdict)
        assert "oracle_unverified" in gd["reasons"], verdict


def test_non_structural_kinds_never_vouch(workspace: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    # The reducer's kind restriction: tests_unmodified IS the tamper guard; behavioral rows
    # ARE tests_passed — neither is NEW independence evidence (no double-counting).
    for kind in ("tests_unmodified", "acceptance_test", "none"):
        gd, _ = _drive_gate(workspace, monkeypatch, claims=[_claim(kind=kind)])
        assert "oracle_unverified" in gd["reasons"], kind


def test_non_material_claim_never_vouches(workspace: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    gd, _ = _drive_gate(workspace, monkeypatch, claims=[_claim(material=False)])
    assert "oracle_unverified" in gd["reasons"]


def test_reducer_is_pure_and_kind_scoped() -> None:
    claims = [_claim(), _claim(kind="tests_unmodified") | {"id": "14-c3"}]
    rows = [
        {"claim_id": "14-c2", "verdict": "satisfied"},
        {"claim_id": "14-c3", "verdict": "satisfied"},
    ]
    assert satisfied_structural_claim_ids(rows, claims) == ["14-c2"]


def test_preservation_style_claims_never_vouch() -> None:
    # Red-team FIX-NOW (2026-08-03): layout-style predicates are true BEFORE any work — a
    # trivial touched delivery satisfying one must NOT vouch (delta-proving claims only).
    claims = [_claim()]
    rows = [
        {"claim_id": "14-c2", "verdict": "satisfied", "oracle_ref": "layout_preserved(cli, store)"}
    ]
    assert satisfied_structural_claim_ids(rows, claims) == []
    rows2 = [
        {"claim_id": "14-c2", "verdict": "satisfied", "oracle_ref": "extract_shared_helper(a, b)"}
    ]
    assert satisfied_structural_claim_ids(rows2, claims) == ["14-c2"]


def test_vouched_but_mutation_blocked_carries_the_priced_residual(
    workspace: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ADR-0071 amendment: the park explains EXACTLY what is proven and what is not.
    import mosaera_core.graph.nodes_review as nr

    monkeypatch.setattr(
        nr,
        "evaluate_claims",
        lambda cs, ws, st: [
            {
                "claim_id": str(c["id"]),
                "verdict": "satisfied",
                "oracle_ref": "extract_shared_helper(a, b)",
            }
            for c in cs
        ],
    )
    captured: dict[str, Any] = {}

    def fake_approval(action, summary, payload):
        captured.update(payload)
        return SimpleNamespace(approved=False, feedback="", actor="autonomous")

    monkeypatch.setattr(nr, "request_approval", fake_approval)
    ctx = SimpleNamespace(
        settings=Settings(oracle_coverage=False, stall_detection_enabled=False),
        workspace=workspace,
        run_id="t",
        test_cmd=None,
        max_iter=8,
    )
    state = {
        "task": PRESERVING_TASK,
        "tests_passed": True,
        "validation_plan": {"strength": "suite"},
        "review": "VERDICT: APPROVE",
        "claims": [_claim()],
        "tests_modified": False,
        "tests_mutation_caught": False,  # the surviving mutant
        "diff": "+++ b/accounts.py\n+x\n",
        "iteration": 1,
    }
    out = nr.gate_node(ctx, state)  # type: ignore[arg-type]
    gd = out["gate_decision"]
    assert "oracle_unverified" in gd["reasons"]  # the AND stands (owner-ratified)
    assert captured["oracle_residual"].startswith("shape: proven")
    assert "UNPROVEN" in captured["oracle_residual"]
    assert gd["oracle_vouched_by"].startswith("structural_claims:")  # committed for the API line
    # The receipt is DURABLE (ADR-0071 amendment): the residual the human priced and the raw
    # mutation tri-state survive into committed gate_state, byte-identical to the live payload.
    assert gd["oracle_residual"] == captured["oracle_residual"]
    assert gd["tests_mutation_caught"] is False


def test_no_residual_committed_when_vouch_never_fired(
    workspace: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No structural vouch (feature task) → no priced residual, in payload OR committed state.
    gd, payload = _drive_gate(workspace, monkeypatch, task=FEATURE_TASK)
    assert payload["oracle_residual"] == ""
    assert gd["oracle_residual"] == ""
    assert gd["tests_mutation_caught"] is None  # not measured — honestly null, never a verdict


def test_the_record_of_WHICH_leg_refused_reaches_the_payload_and_committed_state(
    workspace: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE CHAIN, not the links. `evaluate_oracle` is unit-tested in `test_oracle_legs.py`; this
    proves its record actually travels through the real `gate_node` to both readers — the live
    payload a human sees at the park, and the committed state a scorecard is built from.

    Link-by-link coverage is how a field reads empty forever while every unit test passes: the
    same shape as `security_findings` (0 firings in 2,483 runs, every link tested, chain untested).
    """
    gd, payload = _drive_gate(workspace, monkeypatch, task=FEATURE_TASK)
    assert "oracle_unverified" in gd["reasons"]

    for where, record in (("payload", payload["oracle_legs"]), ("committed", gd["oracle_legs"])):
        assert record["verified"] is False, where
        # The real answer, pinned: all four independence routes said no, while BOTH floors were
        # fine (mutation_raw None, structural_raw None). Before this field, a reader had only
        # `vouch = "no_vouch:not_behavior_preserving"` — which describes one disjunct of the
        # structural route and says nothing about the other three, and was misread as the
        # refusal reason on 2026-08-11.
        assert record["blocked_by"] == ["independence"], f"{where}: {record}"
        assert record["mutation_ok"] is True and record["structural_ok"] is True, where
        assert record["verified"] == gd["oracle_verified"], (
            f"{where}: the record disagrees with the decision it describes — worse than absent"
        )
    assert payload["oracle_legs"] == gd["oracle_legs"], "the two readers must not diverge"


def test_a_vouched_run_blames_nothing_through_the_same_chain(
    workspace: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other direction. Without it, the test above is satisfied by a record that blames
    something on every run — which would carry no information at all."""
    gd, payload = _drive_gate(workspace, monkeypatch)
    assert "oracle_unverified" not in gd["reasons"]
    assert payload["oracle_legs"]["blocked_by"] == []
    assert payload["oracle_legs"]["verified"] is True
