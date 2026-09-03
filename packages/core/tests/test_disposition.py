"""Layer-2 park→ship disposition — the deterministic gap-closer (#76, ADR-0074).

Drives ``close_oracle_gap`` over a REAL git workspace (so the tests/-hash-diff discovery, the
diff-based source filtering, and the static assertion floor all run for real) with a fake
``author_tests`` that writes a known test file — no model. The two sandbox-dependent primitives
(``run_plan`` for the green run, ``suite_catches_a_mutation`` for the mutation catch) are
monkeypatched, exactly as ``test_oraclecheck`` does, so each verdict branch is exercised
deterministically. The ship authority is those deterministic steps — the model only authors.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import mosaera_core.disposition as disp
import pytest
from git import Repo
from mosaera_core.disposition import close_oracle_gap
from mosaera_core.tools.repo import clone_repo
from mosaera_core.validation import ValidationOutcome

_SANDBOX: Any = object()  # never used — run_plan/mutation are monkeypatched

# A committed STUB, then the DELIVERED impl written uncommitted (a park never commits) — so
# ``diff_all`` shows calc.py as the changed region the mutation check must cover.
_STUB = "def add(a, b):\n    return 0\n"
_IMPL = "def add(a, b):\n    return a + b\n"
_GOOD_TEST = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"


def _delivered_workspace(tmp_path: Path) -> Any:
    """A workspace whose committed HEAD has the stub and whose working tree has the delivered
    impl uncommitted — the on-disk shape of a parked run."""
    src = tmp_path / "src"
    src.mkdir()
    repo = Repo.init(src, initial_branch="main")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test User")
        cw.set_value("user", "email", "test@example.com")
    (src / "calc.py").write_text(_STUB, encoding="utf-8")
    repo.index.add(["calc.py"])
    repo.index.commit("init")
    ws = clone_repo(str(src), tmp_path / "ws", "disp")
    (ws.root / "calc.py").write_text(_IMPL, encoding="utf-8")  # the delivered (uncommitted) change
    return ws


def _author(ws: Any, name: str, body: str) -> disp.AuthorTestsFn:
    """A fake tester: writes ``tests/<name>`` with ``body`` when invoked. No model."""

    def author(_instruction: str) -> None:
        p = ws.root / "tests" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")

    return author


def test_verified_when_green_and_mutation_caught(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ws = _delivered_workspace(tmp_path)
    monkeypatch.setattr(disp, "run_plan", lambda *a, **k: ValidationOutcome(True, "1 passed"))
    monkeypatch.setattr(disp, "suite_catches_a_mutation", lambda *a, **k: True)
    result = close_oracle_gap(
        ws, _SANDBOX, _author(ws, "test_acc.py", _GOOD_TEST), acceptance="add returns the sum"
    )
    assert result.verdict == "verified"
    assert result.authored == ("tests/test_acc.py",)
    assert result.green is True and result.mutation_caught is True


def test_unverified_when_delivered_code_fails_the_test(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ws = _delivered_workspace(tmp_path)
    # Green run says the delivered tree FAILS the independent test → the code is actually wrong.
    monkeypatch.setattr(disp, "run_plan", lambda *a, **k: ValidationOutcome(False, "1 failed"))

    def _boom(*_a: Any, **_k: Any) -> bool:  # mutation must never run once green already failed
        raise AssertionError("mutation must not run when the green step failed")

    monkeypatch.setattr(disp, "suite_catches_a_mutation", _boom)
    result = close_oracle_gap(
        ws, _SANDBOX, _author(ws, "test_acc.py", _GOOD_TEST), acceptance="add returns the sum"
    )
    assert result.verdict == "unverified" and result.green is False


def test_unverified_when_a_mutation_survives(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ws = _delivered_workspace(tmp_path)
    monkeypatch.setattr(disp, "run_plan", lambda *a, **k: ValidationOutcome(True, "1 passed"))
    monkeypatch.setattr(disp, "suite_catches_a_mutation", lambda *a, **k: False)
    result = close_oracle_gap(
        ws, _SANDBOX, _author(ws, "test_acc.py", _GOOD_TEST), acceptance="add returns the sum"
    )
    assert result.verdict == "unverified" and result.mutation_caught is False


def test_not_measured_when_mutation_inconclusive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ws = _delivered_workspace(tmp_path)
    monkeypatch.setattr(disp, "run_plan", lambda *a, **k: ValidationOutcome(True, "1 passed"))
    monkeypatch.setattr(disp, "suite_catches_a_mutation", lambda *a, **k: None)
    result = close_oracle_gap(
        ws, _SANDBOX, _author(ws, "test_acc.py", _GOOD_TEST), acceptance="add returns the sum"
    )
    # F83/#92: an inconclusive check is `not_measured`, no longer `unverified`. Those meant
    # opposite things under one word — a rubber stamp vs. an oracle that could not form a question
    # — and 7 of 8 real declines were the latter, read as the former. It STILL DECLINES: every ship
    # test is a positive `== "verified"`, so the new verdict cannot widen anything.
    assert result.verdict == "not_measured" and result.mutation_caught is None
    # The CAUSE is measured, not named. This fixture's delivered change IS mutable, so the honest
    # reason is "no verdict though the change is mutable" — a stuck/absent test run. The first draft
    # of F83 printed "no mutable construct in the change" here, which this fixture disproves: that
    # string was asserting a branch nobody had checked, which is F83's own defect one level up.
    assert "IS mutable" in result.reason
    assert "no mutable construct" not in result.reason


def test_unavailable_when_nothing_authored(tmp_path: Path) -> None:
    ws = _delivered_workspace(tmp_path)

    def _noop(_instruction: str) -> None:  # a tester that writes nothing
        return None

    result = close_oracle_gap(ws, _SANDBOX, _noop, acceptance="add returns the sum")
    assert result.verdict == "unavailable" and result.authored == ()


def test_unavailable_when_the_authored_test_asserts_nothing_real(tmp_path: Path) -> None:
    ws = _delivered_workspace(tmp_path)
    tautology = "def test_x():\n    assert True\n"
    result = close_oracle_gap(
        ws, _SANDBOX, _author(ws, "test_taut.py", tautology), acceptance="add returns the sum"
    )
    assert result.verdict == "unavailable" and "floor" in result.reason


def test_unavailable_when_authoring_raises(tmp_path: Path) -> None:
    ws = _delivered_workspace(tmp_path)

    def _raises(_instruction: str) -> None:
        raise RuntimeError("tester crashed")

    result = close_oracle_gap(ws, _SANDBOX, _raises, acceptance="add returns the sum")
    assert result.verdict == "unavailable" and "authoring failed" in result.reason


def test_editing_a_baselined_test_is_rejected_as_tamper(tmp_path: Path) -> None:
    # A pre-existing tracked test that the tester EDITS is a tamper — the caller commits the whole
    # tree, so a laundered weakening would ship. The gap-closer must refuse (red-team agent 4 F1),
    # never merely "not count" the edit.
    ws = _delivered_workspace(tmp_path)
    baseline = ws.root / "tests" / "test_base.py"
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_text("from calc import add\n\n\ndef test_b():\n    assert add(1, 1) == 2\n")
    ws.commit_all("baseline test")  # now tracked in HEAD

    def _launder(_instruction: str) -> None:
        # Gut the baselined guard AND write a valid new test — the laundering shape.
        baseline.write_text("def test_b():\n    assert True\n")
        (ws.root / "tests" / "test_acc.py").write_text(_GOOD_TEST)

    result = close_oracle_gap(ws, _SANDBOX, _launder, acceptance="add returns the sum")
    assert result.verdict == "unavailable" and "tamper" in result.reason


def test_authored_non_test_named_file_does_not_leak_into_mutation_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Red-team agent 2 F1: a tester can author a NON-``test_``-named file under tests/ (e.g.
    # tests/check.py). It must NOT leak into the mutation `source` (else the mutation flips the
    # authored test's own assertion → a fake self-catch). The filter subtracts the authored set.
    ws = _delivered_workspace(tmp_path)
    captured: dict[str, Any] = {}

    def _capture(_ws: Any, _sb: Any, source: Any, tests: Any, **kw: Any) -> bool:
        captured["source"] = list(source)
        captured["tests"] = list(tests)
        return True

    monkeypatch.setattr(disp, "run_plan", lambda *a, **k: ValidationOutcome(True, "1 passed"))
    monkeypatch.setattr(disp, "suite_catches_a_mutation", _capture)
    body = "from calc import add\n\n\ndef test_x():\n    assert add(2, 3) == 5\n"
    result = close_oracle_gap(
        ws, _SANDBOX, _author(ws, "check.py", body), acceptance="add returns the sum"
    )
    assert result.verdict == "verified"
    assert "tests/check.py" not in captured["source"]  # the authored file never mutates itself
    assert captured["source"] == ["calc.py"]
    assert captured["tests"] == ["tests/check.py"]


def test_no_delivered_source_change_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Red-team agent 3 F2: an already-satisfied / tests-only park has no delivered NON-test source
    # change. Verifying it would ship only a test (not a delivered feature) — so it stays parked.
    src = tmp_path / "src"
    src.mkdir()
    repo = Repo.init(src, initial_branch="main")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test User")
        cw.set_value("user", "email", "test@example.com")
    (src / "calc.py").write_text(_IMPL, encoding="utf-8")  # already correct, committed
    repo.index.add(["calc.py"])
    repo.index.commit("init")
    ws = clone_repo(str(src), tmp_path / "ws", "disp")  # working tree == HEAD: no source delta

    monkeypatch.setattr(disp, "run_plan", lambda *a, **k: ValidationOutcome(True, "1 passed"))

    def _boom(*_a: Any, **_k: Any) -> bool:
        raise AssertionError("mutation must not run when there is no delivered source change")

    monkeypatch.setattr(disp, "suite_catches_a_mutation", _boom)
    result = close_oracle_gap(
        ws, _SANDBOX, _author(ws, "test_acc.py", _GOOD_TEST), acceptance="add returns the sum"
    )
    assert result.verdict == "unavailable" and "no delivered source change" in result.reason


def test_mutation_source_excludes_test_files_and_targets_the_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The mutation step must receive the changed NON-test source (calc.py) and the authored test as
    # the suite — never the test file as a mutation target.
    ws = _delivered_workspace(tmp_path)
    captured: dict[str, Any] = {}

    def _capture(_ws: Any, _sb: Any, source: Any, tests: Any, **kw: Any) -> bool:
        captured["source"] = list(source)
        captured["tests"] = list(tests)
        captured["comprehensive"] = kw.get("comprehensive")
        return True

    monkeypatch.setattr(disp, "run_plan", lambda *a, **k: ValidationOutcome(True, "1 passed"))
    monkeypatch.setattr(disp, "suite_catches_a_mutation", _capture)
    result = close_oracle_gap(
        ws,
        _SANDBOX,
        _author(ws, "test_acc.py", _GOOD_TEST),
        acceptance="add returns the sum",
        comprehensive=True,
    )
    assert result.verdict == "verified"
    assert captured["source"] == ["calc.py"]
    assert captured["tests"] == ["tests/test_acc.py"]
    assert captured["comprehensive"] is True


# --- convertible class 2: the engine-blocked give-up (#76 widening, ADR-0075) -------------------

# A terminal pytest output whose ONLY failures are the engine's authored tests.
_ENGINE_FAIL_OUTPUT = (
    "FAILED tests/test_authored.py::test_a - AssertionError\n"
    "FAILED tests/test_authored.py::test_b - AssertionError\n"
    "2 failed, 3 passed\n"
)


def _give_up_final(**over: Any) -> dict[str, Any]:
    """A qualifying engine-blocked give-up park's final state (each test overrides one field)."""
    final: dict[str, Any] = {
        "give_up_reason": "no convergence: failing count 2 -> 2 over 2 non-improving attempts",
        "stalled": False,
        "plan_unworkable_reason": "",
        "blocked_reason": "",
        "escalate_reason": "",
        "coder_escalated": False,
        "tests_modified": False,
        "outcome_verdict": None,
        "gate_decision": {"reasons": ["validation_failed", "reviewer_unknown"]},
        "authored_tests": ["tests/test_authored.py"],
        "proctor_edits": {},
        "test_output": _ENGINE_FAIL_OUTPUT,
    }
    final.update(over)
    return final


def test_engine_blocked_give_up_qualifies() -> None:
    final = _give_up_final()
    assert disp.is_engine_blocked_give_up(final) is True
    assert disp.trapping_engine_tests(final) == ("tests/test_authored.py",)
    assert disp.convertible_park_class(final) == "engine_blocked_give_up"


def test_give_up_with_empty_failing_set_is_not_convertible() -> None:
    # The vacuous-subset hole: no derivable failing tests => nothing attributable => park stands.
    final = _give_up_final(test_output="everything exploded, no pytest summary here")
    assert disp.is_engine_blocked_give_up(final) is False
    assert disp.trapping_engine_tests(final) == ()


def test_give_up_with_a_coder_owned_failing_test_is_not_convertible() -> None:
    # One failing test OUTSIDE the engine-owned set => the code may genuinely be wrong.
    out = _ENGINE_FAIL_OUTPUT + "FAILED tests/test_coder_own.py::test_x - AssertionError\n"
    final = _give_up_final(test_output=out)
    assert disp.is_engine_blocked_give_up(final) is False


def test_give_up_without_authored_tests_is_not_convertible() -> None:
    final = _give_up_final(authored_tests=[], proctor_edits={})
    assert disp.is_engine_blocked_give_up(final) is False


def test_proctor_edited_baselined_test_is_not_convertible() -> None:
    # RED-TEAM R1 (critical false-ship): proctor_edits KEYS are pre-existing BASELINED HUMAN tests.
    # Superseding = deletion, so a proctor-edited baselined test in the deletable set would let a
    # run DELETE a human test to ship (tamper by omission — reproduced end-to-end). It must be
    # excluded from the engine-OWNED (deletable) set: only the tester's OWN authored files qualify.
    out = "FAILED tests/test_base.py::test_y - AssertionError\n1 failed\n"
    final = _give_up_final(
        authored_tests=[], proctor_edits={"tests/test_base.py": "hash"}, test_output=out
    )
    assert disp.trapping_engine_tests(final) == ()  # the baselined test is NOT deletable
    assert disp.is_engine_blocked_give_up(final) is False  # → park stands


def test_give_up_with_a_baselined_test_in_the_failing_set_is_not_convertible() -> None:
    # Even alongside an authored test, a failing baselined (proctor-edited) test disqualifies the
    # whole park: the failing set is no longer a subset of the deletable allowlist → parks.
    out = (
        "FAILED tests/test_authored.py::test_a - AssertionError\n"
        "FAILED tests/test_base.py::test_y - AssertionError\n2 failed\n"
    )
    final = _give_up_final(proctor_edits={"tests/test_base.py": "hash"}, test_output=out)
    assert disp.is_engine_blocked_give_up(final) is False


def test_baselined_test_leaked_into_authored_tests_is_never_deletable() -> None:
    # RED-TEAM R2 (same critical class, new route): the run's tester can EDIT a pre-existing test
    # during its first authoring turn (no protected_paths yet), so a baselined human test can LEAK
    # into authored_tests. The positive allowlist (authored MINUS pre-existing baselined tests)
    # must still refuse to supersede it — a name-only authored_tests membership is not enough.
    out = "FAILED tests/test_base.py::test_y - AssertionError\n1 failed\n"
    final = _give_up_final(
        authored_tests=["tests/test_base.py"],  # the leaked baselined path
        proctor_edits={"tests/test_base.py": "hash"},
        integrity_baseline={"tests/test_base.py": "pristine-hash"},  # it existed at run start
        test_output=out,
    )
    assert disp.trapping_engine_tests(final) == ()  # proven-pre-existing → not deletable
    assert disp.is_engine_blocked_give_up(final) is False


def test_only_proven_new_authored_tests_are_deletable() -> None:
    # A genuinely-new authored test (not in the pristine integrity_baseline) IS the deletable set;
    # a baselined sibling in authored_tests is excluded even when only the new one is failing.
    out = "FAILED tests/test_new.py::test_a - AssertionError\n1 failed\n"
    final = _give_up_final(
        authored_tests=["tests/test_new.py", "tests/test_base.py"],
        integrity_baseline={"tests/test_base.py": "pristine-hash"},
        test_output=out,
    )
    assert disp.trapping_engine_tests(final) == ("tests/test_new.py",)
    assert disp.is_engine_blocked_give_up(final) is True


@pytest.mark.parametrize(
    "reason,coder_escalated",
    [
        ("blocked: I cannot satisfy tests/test_authored.py — it looks unsatisfiable", False),
        ("escalation unresolved: the task conflicts with a test", True),
        ("escalation unresolved: the task conflicts with a test", False),
        ("gate kept denying (oracle_unverified) across 3 re-plans", False),
    ],
)
def test_coder_handraise_and_gate_loop_give_ups_are_not_convertible(
    reason: str, coder_escalated: bool
) -> None:
    # RED-TEAM R1 F1: give_up_reason is origin-blind — supervise clears blocked_reason/
    # escalate_reason when converting a hand-raise. A coder hand-raise (blocked/escalate) or the
    # gate-loop breaker is NOT a no-progress engine-test trap; the engine-controlled prefixes +
    # coder_escalated distinguish them. Only the no-progress origin converts.
    final = _give_up_final(give_up_reason=reason, coder_escalated=coder_escalated)
    assert disp.is_engine_blocked_give_up(final) is False


def test_cap_truncation_spoof_does_not_hide_a_coder_failure() -> None:
    # RED-TEAM R1 F2: a coder printing >50 forged FAILED engine-lines before the real coder-owned
    # failure must NOT bury it — the parse is uncapped and one non-authored failure disqualifies.
    forged = "".join(f"FAILED tests/test_authored.py::t{i} - AssertionError\n" for i in range(80))
    out = forged + "FAILED tests/test_coder_own.py::test_real - AssertionError\n81 failed\n"
    final = _give_up_final(test_output=out)
    assert disp.is_engine_blocked_give_up(final) is False


@pytest.mark.parametrize(
    "channel,value",
    [
        ("stalled", True),
        ("plan_unworkable_reason", "no workable plan"),
        ("blocked_reason", "needs a human"),
        ("escalate_reason", "scope question"),
    ],
)
def test_any_other_honest_stop_channel_blocks_the_give_up_class(channel: str, value: Any) -> None:
    # ADR-0074 FIX-NOW #1 holds for every channel except the deliberate give_up signal.
    final = _give_up_final(**{channel: value})
    assert disp.is_engine_blocked_give_up(final) is False


@pytest.mark.parametrize(
    "reasons",
    [
        ["validation_failed", "tests_tampered"],
        ["validation_failed", "security_findings"],
        ["validation_failed", "reviewer_requested_changes"],
        ["validation_failed", "critic_vetoed"],
        ["validation_unavailable"],
    ],
)
def test_non_benign_gate_reasons_block_the_give_up_class(reasons: list[str]) -> None:
    final = _give_up_final(gate_decision={"reasons": reasons})
    assert disp.is_engine_blocked_give_up(final) is False


def test_give_up_with_tamper_or_veto_is_not_convertible() -> None:
    assert disp.is_engine_blocked_give_up(_give_up_final(tests_modified=True)) is False
    assert disp.is_engine_blocked_give_up(_give_up_final(outcome_verdict={"vetoed": True})) is False


def test_the_two_classes_are_disjoint() -> None:
    # Class 1 requires give_up_reason falsy; class 2 requires it truthy.
    ou = {
        "gate_decision": {"reasons": ["oracle_unverified"]},
        "tests_passed": True,
        "tests_modified": False,
        "outcome_verdict": None,
    }
    assert disp.convertible_park_class(ou) == "oracle_unverified"
    assert disp.convertible_park_class(_give_up_final()) == "engine_blocked_give_up"
    assert disp.convertible_park_class({}) is None


def test_node_id_normalization() -> None:
    # Node-ids with backslashes / leading ./ normalize to the authored_tests path space.
    out = r"FAILED .\tests\test_authored.py::test_a - AssertionError" + "\n1 failed\n"
    final = _give_up_final(test_output=out)
    assert disp.trapping_engine_tests(final) == ("tests/test_authored.py",)


def test_supersede_refuses_paths_outside_tests(tmp_path: Path) -> None:
    ws = _delivered_workspace(tmp_path)
    (ws.root / "calc_keep.py").write_text("x = 1\n", encoding="utf-8")
    # A non-tests/ path in the trapping tuple must be skipped (belt-and-suspenders).
    removed = disp.supersede_engine_tests(ws, ("calc_keep.py", "tests/../calc_keep.py"))
    assert removed == []
    assert (ws.root / "calc_keep.py").is_file()


def test_supersede_removes_only_the_trapping_files(tmp_path: Path) -> None:
    ws = _delivered_workspace(tmp_path)
    trap = ws.root / "tests" / "test_trap.py"
    keep = ws.root / "tests" / "test_keep.py"
    trap.parent.mkdir(parents=True, exist_ok=True)
    trap.write_text("def test_t():\n    assert False\n", encoding="utf-8")
    keep.write_text("def test_k():\n    assert True\n", encoding="utf-8")
    removed = disp.supersede_engine_tests(ws, ("tests/test_trap.py",))
    assert removed == ["tests/test_trap.py"]
    assert not trap.exists() and keep.exists()


def test_give_up_end_to_end_supersede_then_verified(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The full class-2 flow on a real git workspace: the trapping authored test is deleted, the
    # fresh independent test is authored, and the deterministic gate returns verified. The deleted
    # trapping file rides the diff as a deletion (staged by git add -A at commit time).
    ws = _delivered_workspace(tmp_path)
    trap = ws.root / "tests" / "test_trap.py"
    trap.parent.mkdir(parents=True, exist_ok=True)
    trap.write_text("from calc import add\n\n\ndef test_wrong():\n    assert add(2, 3) == 6\n")
    removed = disp.supersede_engine_tests(ws, ("tests/test_trap.py",))
    assert removed == ["tests/test_trap.py"]
    monkeypatch.setattr(disp, "run_plan", lambda *a, **k: ValidationOutcome(True, "1 passed"))
    monkeypatch.setattr(disp, "suite_catches_a_mutation", lambda *a, **k: True)
    result = close_oracle_gap(
        ws, _SANDBOX, _author(ws, "test_acc.py", _GOOD_TEST), acceptance="add returns the sum"
    )
    assert result.verdict == "verified"
    assert result.authored == ("tests/test_acc.py",)


# --- Why a park was NOT converted -------------------------------------------------------------
#
# The 2026-08-05 over-park sweep hit a park with gate reasons ['oracle_unverified'] alone — the
# exact class-1 shape — that Layer 2 refused. Nothing recorded why; the run's final state was gone
# by the time anyone asked, so the cause is permanently unrecoverable. These pin the diagnosis.


def test_a_convertible_park_has_no_decline_reason() -> None:
    final = {"gate_decision": {"reasons": ["oracle_unverified"]}, "tests_passed": True}
    assert disp.convertible_park_class(final) == "oracle_unverified"
    assert disp.convertible_decline_reason(final) == ""


def test_the_decline_reason_names_the_allowlist_gap() -> None:
    """The finding this whole arc turned on: `unsatisfied_claim` (ADR-0079 Wave 2, 2026-08-02) is
    absent from `_GIVE_UP_ALLOWED_REASONS` (ADR-0075, 2026-07-23), so class 2 cannot fire on the
    dominant over-park shape — 7 of 18 stored over-parks, and 3 cases live. One recorded line would
    have made that visible on day one instead of ten days later."""
    final = {
        "gate_decision": {
            "reasons": ["validation_failed", "reviewer_unknown", "unsatisfied_claim"]
        },
        "give_up_reason": "no convergence: failing count 4 -> 4 -> 4",
        "tests_passed": False,
    }
    assert disp.convertible_park_class(final) is None
    reason = disp.convertible_decline_reason(final)
    assert "unsatisfied_claim" in reason, reason
    assert "allowlist" in reason, reason


def test_a_give_up_is_not_reported_as_a_safety_stop() -> None:
    """`give_up_reason` is REQUIRED on the class-2 path, so naming it a safety stop would hide the
    real cause. The first draft of this diagnosis did exactly that and masked the allowlist gap
    behind a plausible-sounding wrong answer — the predicate skips it, so the diagnosis must too."""
    final = {
        "gate_decision": {"reasons": ["validation_failed", "unsatisfied_claim"]},
        "give_up_reason": "no progress",
    }
    assert "honest_stop" not in disp.convertible_decline_reason(final)


def test_tamper_and_veto_are_named_before_anything_else() -> None:
    tampered = {
        "gate_decision": {"reasons": ["oracle_unverified"]},
        "tests_passed": True,
        "tests_modified": True,
    }
    assert "tamper" in disp.convertible_decline_reason(tampered)
    vetoed = {
        "gate_decision": {"reasons": ["oracle_unverified"]},
        "tests_passed": True,
        "outcome_verdict": {"vetoed": True},
    }
    assert "critic_vetoed" in disp.convertible_decline_reason(vetoed)


def test_the_diagnosis_cannot_drift_from_the_predicates() -> None:
    """The invariant that keeps this honest: a decline reason exists EXACTLY when the park is not
    convertible. Without this, the diagnosis and the decision could disagree — and a diagnosis that
    disagrees with the decision is worse than none, because it is believed."""
    reasons_sets = [
        [],
        ["oracle_unverified"],
        ["validation_failed"],
        ["validation_failed", "unsatisfied_claim"],
        ["oracle_unverified", "reviewer_requested_changes"],
        ["tests_tampered", "validation_failed"],
        ["iteration_limit", "reviewer_unknown", "oracle_unverified"],
    ]
    extras: list[dict] = [
        {},
        {"tests_passed": True},
        {"tests_passed": False},
        {"tests_modified": True},
        {"coder_escalated": True},
        {"blocked_reason": "blocked"},
        {"escalate_reason": "escalate"},
        {"stalled": True, "stall_reason": "no convergence"},
        {"outcome_verdict": {"vetoed": True}},
        {"give_up_reason": "no progress"},
        {"give_up_reason": "no progress", "authored_tests": ["tests/t.py"]},
        {
            "give_up_reason": "no progress",
            "authored_tests": ["tests/t.py"],
            "test_output": "FAILED tests/t.py::x - assert 1 == 2",
        },
    ]
    checked = 0
    for reasons in reasons_sets:
        for extra in extras:
            final = {"gate_decision": {"reasons": reasons}, **extra}
            convertible = disp.convertible_park_class(final) is not None
            declined = bool(disp.convertible_decline_reason(final))
            assert convertible != declined, f"disagreement on {final}"
            checked += 1
    assert checked == len(reasons_sets) * len(extras)
