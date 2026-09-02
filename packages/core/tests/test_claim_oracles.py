"""Per-claim oracle evaluation (ADR-0079 Wave 2) — offline, no model, no docker.

The transformation contracts are the offline-validated 18/18 set (engineering-history
2026-08-02) re-pinned as unit tests over the REAL case material: seeds must fail, references
must pass. Policy tests drive `evaluate_claims` end-to-end over a real git workspace.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from git import Repo
from mosaera_core.bench.cases import load_case
from mosaera_core.claim_oracles import (
    data_driven_single_if,
    evaluate_claims,
    extract_shared_helper,
    failed_claim_ids,
    layout_preserved,
)
from mosaera_core.claims import claims_as_dicts, claims_from_acceptance
from mosaera_core.tools.repo import clone_repo

CASES = Path(__file__).resolve().parents[1] / "mosaera_core" / "bench" / "cases"


def _case_src(case: str, arm: str, name: str) -> str:
    return (CASES / case / arm / name).read_text(encoding="utf-8")


# ── the ported contracts, pinned against the real case material ──────────────
def test_single_if_contract_fails_seed_passes_reference() -> None:
    assert data_driven_single_if(_case_src("MCB-13", "seed", "grading.py"), "grade_letter") is False
    assert data_driven_single_if(_case_src("MCB-13", "reference", "grading.py"), "grade_letter")


def test_single_if_contract_is_none_on_missing_target() -> None:
    assert data_driven_single_if("x = 1\n", "grade_letter") is None
    assert data_driven_single_if("def (broken", "grade_letter") is None


def test_shared_helper_contract_fails_seed_passes_reference() -> None:
    seed = _case_src("MCB-14", "seed", "accounts.py")
    ref = _case_src("MCB-14", "reference", "accounts.py")
    assert extract_shared_helper(seed, "create_user", "update_user") is False
    assert extract_shared_helper(ref, "create_user", "update_user") is True


def test_layout_contract_passes_intact_fails_collapsed(tmp_path: Path) -> None:
    import shutil

    pkg = tmp_path / "journal"
    shutil.copytree(CASES / "MCB-21" / "seed" / "journal", pkg)
    modules = ["cli", "store", "model"]
    assert layout_preserved(tmp_path, modules) is True
    (pkg / "store.py").unlink()
    assert layout_preserved(tmp_path, modules) is False  # a named module is gone → collapsed


def test_layout_contract_is_none_when_never_locatable(tmp_path: Path) -> None:
    assert layout_preserved(tmp_path, ["cli", "store", "model"]) is None


# ── evaluate_claims policy over a real workspace ─────────────────────────────
@pytest.fixture
def workspace(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    repo = Repo.init(src, initial_branch="main")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "T")
        cw.set_value("user", "email", "t@example.com")
    (src / "grading.py").write_text(_case_src("MCB-13", "seed", "grading.py"), encoding="utf-8")
    repo.index.add(["grading.py"])
    repo.index.commit("seed")
    return clone_repo(str(src), tmp_path / "ws", "claim-oracles-test")


def _claim(cid: str, kind: str, text: str = "t", material: bool = True) -> dict[str, Any]:
    return {
        "id": cid,
        "item_id": 1,
        "text": text,
        "provenance": "ENTAILED",
        "oracle_kind": kind,
        "material": material,
    }


def test_behavioral_claims_follow_tests_passed(workspace: Any) -> None:
    claims = [_claim("1-c1", "acceptance_test")]
    assert evaluate_claims(claims, workspace, {"tests_passed": True})[0]["verdict"] == "satisfied"
    assert evaluate_claims(claims, workspace, {"tests_passed": False})[0]["verdict"] == "failed"
    assert evaluate_claims(claims, workspace, {})[0]["verdict"] == "unevaluable"


def test_tamper_claim_follows_the_integrity_guard(workspace: Any) -> None:
    claims = [_claim("1-c1", "tests_unmodified")]
    assert evaluate_claims(claims, workspace, {"tests_modified": True})[0]["verdict"] == "failed"
    assert evaluate_claims(claims, workspace, {})[0]["verdict"] == "satisfied"


def test_unbound_claim_never_fails(workspace: Any) -> None:
    row = evaluate_claims([_claim("1-c1", "none")], workspace, {"tests_passed": False})[0]
    assert row["verdict"] == "unbound"  # owner decision: intake's job, never a gate park


def test_transformation_claim_fails_on_unchanged_seed_shape(workspace: Any) -> None:
    # Deliver a change that leaves grade_letter as the if/elif ladder → the single-if
    # contract, named by the claim's own sentence, must FAIL.
    path = workspace.root / "grading.py"
    path.write_text(path.read_text(encoding="utf-8") + "\nEXTRA = 1\n", encoding="utf-8")
    claims = [
        _claim(
            "1-c1",
            "ast_transformation_contract",
            "after the change, `grade_letter` should contain a single `if` driven by a table",
        )
    ]
    rows = evaluate_claims(claims, workspace, {"task": "refactor grading"})
    assert rows[0]["verdict"] == "failed"
    assert "data_driven_single_if" in rows[0]["oracle_ref"]
    assert failed_claim_ids(rows) == ["1-c1"]


def test_transformation_claim_satisfied_by_the_reference_shape(workspace: Any) -> None:
    (workspace.root / "grading.py").write_text(
        _case_src("MCB-13", "reference", "grading.py"), encoding="utf-8"
    )
    claims = [
        _claim(
            "1-c1",
            "ast_transformation_contract",
            "after the change, `grade_letter` should contain a single `if` driven by a table",
        )
    ]
    rows = evaluate_claims(claims, workspace, {"task": "refactor grading"})
    assert rows[0]["verdict"] == "satisfied" and failed_claim_ids(rows) == []


def test_transformation_without_extractable_target_is_unevaluable(workspace: Any) -> None:
    path = workspace.root / "grading.py"
    path.write_text(path.read_text(encoding="utf-8") + "\nEXTRA = 1\n", encoding="utf-8")
    claims = [_claim("1-c1", "ast_transformation_contract", "make it a single if somehow")]
    rows = evaluate_claims(claims, workspace, {"task": "t"})
    assert rows[0]["verdict"] == "unevaluable"  # no named target → never guessed


def test_evaluator_crash_degrades_to_unevaluable(workspace: Any) -> None:
    class Boom:
        root = workspace.root

        def diff_all(self):
            raise RuntimeError("boom")

    claims = [_claim("1-c1", "ast_transformation_contract", "`grade_letter` single `if`")]
    rows = evaluate_claims(claims, Boom(), {"task": "t"})
    assert rows[0]["verdict"] == "unevaluable"  # no park, no vouch, no crash


def test_real_mcb05_claims_evaluate_without_crashing(workspace: Any) -> None:
    # Whole-brief-derived claims (the bench path) must produce a full verdict row set.
    claims = claims_as_dicts(claims_from_acceptance(None, load_case("MCB-05").brief))
    rows = evaluate_claims(claims, workspace, {"tests_passed": True, "task": "t"})
    assert len(rows) == len(claims)
    assert all(r["verdict"] in ("satisfied", "failed", "unbound", "unevaluable") for r in rows)


# ── the vacuous-vouch class (no-vacuous-verdicts pass) ───────────────────────
#
# A satisfied MATERIAL ast_transformation_contract claim is the ONE input to the #60
# refactor vouch: satisfied -> satisfied_structural_claim_ids -> structural_vouch_ids ->
# oracle_verified -> the gate drops `oracle_unverified` and can approve autonomously. So a
# structural verdict reached without executing a single predicate would be independence
# evidence manufactured from nothing. It must be `unevaluable`, which vouches for nothing.


def _shrink_claim_workspace(tmp_path: Path, *, with_baseline: bool) -> Any:
    """A workspace whose delivered `f` carries a 'short orchestrator' ask (no helper count).

    `with_baseline=False` reproduces the real precondition: the file is delivered but
    `git show HEAD:<f>` yields nothing (a new file, or a git fault suppressed at the call
    site), so the pre-refactor body is unknown and the ratio cannot be measured.
    """
    src = tmp_path / "src"
    src.mkdir()
    repo = Repo.init(src, initial_branch="main")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "T")
        cw.set_value("user", "email", "t@example.com")
    # A committed file so the clone has a HEAD; the TARGET file is delivered without one.
    (src / "seed.py").write_text("X = 1\n", encoding="utf-8")
    repo.index.add(["seed.py"])
    if with_baseline:
        (src / "m.py").write_text(
            "def f():\n" + "".join(f"    x{i} = {i}\n" for i in range(12)), encoding="utf-8"
        )
        repo.index.add(["m.py"])
    repo.index.commit("seed")
    ws = clone_repo(str(src), tmp_path / "ws", "vacuous-vouch-test")
    (ws.root / "m.py").write_text(
        "def f():\n    return helper()\n\n\ndef helper():\n    return 1\n", encoding="utf-8"
    )
    return ws


def test_a_shrink_ask_with_no_baseline_never_vouches(tmp_path: Path) -> None:
    from mosaera_core.claim_oracles import satisfied_structural_claim_ids

    claims = [
        {
            "id": "c1",
            "text": "Refactor `f` into a short orchestrator",
            "oracle_kind": "ast_transformation_contract",
            "material": True,
        }
    ]
    ws = _shrink_claim_workspace(tmp_path, with_baseline=False)
    rows = evaluate_claims(claims, ws, {"task": "Refactor `f` into a short orchestrator"})
    verdicts = {r["claim_id"]: r["verdict"] for r in rows}
    assert verdicts["c1"] != "satisfied", (
        "a structural ask with no measurable baseline reported SATISFIED — that verdict "
        f"vouches, so it may never be manufactured from zero predicates: {rows}"
    )
    # ...and therefore contributes nothing to the #60 refactor vouch.
    assert satisfied_structural_claim_ids(rows, claims) == []


def test_failed_claim_kinds_separates_the_evidence_classes() -> None:
    """ADR-0090's instrument: the failed-claim ids alone cannot tell the classes apart.

    `unsatisfied_claim` is one reason over three evidence classes. A behavioural failure restates
    `tests_passed`; a structural one is independent; a `tests_unmodified` one IS the tamper guard.
    The 2026-08-08 measurement had to proxy that split on `validation_failed` co-presence because
    nothing recorded the kind — this is what makes it a direct read.
    """
    from mosaera_core.claim_oracles import failed_claim_kinds

    claims = [
        {"id": "c1", "oracle_kind": "acceptance_test"},
        {"id": "c2", "oracle_kind": "acceptance_test"},
        {"id": "c3", "oracle_kind": "ast_transformation_contract"},
        {"id": "c4", "oracle_kind": "tests_unmodified"},
        {"id": "c5", "oracle_kind": "acceptance_test"},
    ]
    rows = [
        {"claim_id": "c1", "verdict": "failed"},
        {"claim_id": "c2", "verdict": "failed"},
        {"claim_id": "c3", "verdict": "failed"},
        {"claim_id": "c4", "verdict": "failed"},
        {"claim_id": "c5", "verdict": "satisfied"},  # must not be counted
    ]
    assert failed_claim_kinds(rows, claims) == {
        "acceptance_test": 2,
        "ast_transformation_contract": 1,
        "tests_unmodified": 1,
    }


def test_failed_claim_kinds_is_empty_when_nothing_failed() -> None:
    from mosaera_core.claim_oracles import failed_claim_kinds

    rows = [{"claim_id": "c1", "verdict": "satisfied"}, {"claim_id": "c2", "verdict": "unbound"}]
    claims = [{"id": "c1", "oracle_kind": "acceptance_test"}, {"id": "c2"}]
    assert failed_claim_kinds(rows, claims) == {}


def test_failed_claim_kinds_names_an_unmatched_claim_rather_than_dropping_it() -> None:
    """Deny-by-default applied to the instrument: a disposition with no matching claim is
    reported as `unknown`, never silently discarded — a count that quietly loses rows is how an
    instrument reads clean while the thing it measures is broken."""
    from mosaera_core.claim_oracles import failed_claim_kinds

    assert failed_claim_kinds([{"claim_id": "ghost", "verdict": "failed"}], []) == {"unknown": 1}
