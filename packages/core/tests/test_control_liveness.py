"""Control-liveness sentinels (ADR-0081) — offline, no model, no docker.

Each sentinel proves (or honestly pins the ABSENCE of) arm divergence for a knob in the liveness
registry: with the knob ON vs OFF, the fingerprint projection — nodes present, state keys
written — must differ (C4), or, for the one knob that CANNOT diverge on countable input, must be
proven identical (the instance-#4 regression pin). Plus unit tests for the fingerprint compare.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from git import Repo
from mosaera_core.bench.liveness import (
    INVALID_EXPERIMENT_IDENTICAL_EXECUTION,
    REGISTRY,
    compare_fingerprints,
    experiment_verdict,
    registry_by_knob,
)
from mosaera_core.config import Settings
from mosaera_core.graph import build_graph
from mosaera_core.graph.convergence import convergence_update
from mosaera_core.sandbox import SubprocessSandbox
from mosaera_core.tools.repo import clone_repo
from mosaera_core.validation import ValidationOutcome, ValidationPlan


@pytest.fixture
def workspace(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    repo = Repo.init(src, initial_branch="main")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test User")
        cw.set_value("user", "email", "test@example.com")
    (src / "a.py").write_text("x = 1\n", encoding="utf-8")
    repo.index.add(["a.py"])
    repo.index.commit("init")
    return clone_repo(str(src), tmp_path / "ws", "liveness-test")


# ── C4 sentinel: tester_enabled diverges the GRAPH STRUCTURE ─────────────────
def test_tester_enabled_diverges_the_graph(workspace: Any, tmp_path: Path) -> None:
    def nodes(tester: bool) -> set[str]:
        graph = build_graph(
            Settings(home=tmp_path / ".mosaera", tester_enabled=tester),
            workspace,
            SubprocessSandbox(workspace.root),
            run_id="liveness-tester",
            source="local",
        )
        return set(graph.get_graph().nodes)

    on, off = nodes(True), nodes(False)
    assert "author_tests" in on and "author_tests" not in off  # the structural divergence


# ── C4 sentinel: oracle_structural_spec diverges the STATE WRITES ────────────
def _drive_test_node(workspace: Any, monkeypatch: pytest.MonkeyPatch, structural: bool) -> dict:
    """Run the real test_node with validation stubbed green; return its result dict.

    The fingerprint projection is 'which DECLARED keys did the node write' — exactly what
    bench/harness.py captures per update — so key-presence divergence here IS C4 divergence.
    """
    import mosaera_core.graph.nodes_impl as impl

    plan = ValidationPlan(project_type="python-pytest", steps=[], reason="stub", strength="suite")
    monkeypatch.setattr(impl, "resolve_plan", lambda *a, **k: plan)
    monkeypatch.setattr(
        impl, "run_plan", lambda *a, **k: ValidationOutcome(passed=True, output="1 passed")
    )
    ctx = SimpleNamespace(
        settings=Settings(scan_enabled=False, oracle_structural_spec=structural),
        workspace=workspace,
        sandbox=None,
        test_cmd=None,
        evidence_memo={},
        max_iter=8,
        max_reason=1,
        memory=None,
        item_id=None,
        project_id=None,
        operator_sanctioned={},
    )
    state: dict[str, Any] = {"task": "refactor into a short orchestrator with three helpers"}
    return impl.test_node(ctx, state)  # type: ignore[arg-type]


def test_structural_spec_knob_diverges_state_writes(
    workspace: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    on = _drive_test_node(workspace, monkeypatch, structural=True)
    off = _drive_test_node(workspace, monkeypatch, structural=False)
    assert "structural_spec_ok" in on  # ON writes the evidence key (value may be None)
    assert "structural_spec_ok" not in off  # OFF never writes it — the arms diverge


# ── The instance-#4 pin: honest_stop_no_signal CANNOT diverge on countable input ──
def test_honest_stop_no_signal_cannot_diverge_on_countable_input() -> None:
    """The knob's only read is in the no-count branch; a countable validator never reaches it.

    This is the regression pin for liveness incident #4 (ADR-0081 context): the MCB-26 'A/B'
    ran identical code because #81 made SQL countable. If this test ever FAILS, the knob has
    become measurable on countable input and the registry entry must be revisited.
    """

    def run(knob: bool) -> dict[str, Any]:
        ctx = SimpleNamespace(
            settings=Settings(
                stall_detection_enabled=True,
                honest_stop_no_signal=knob,
                stall_limit=2,
                reason_on_stall_enabled=False,
            ),
            max_iter=8,
            max_reason=1,
        )
        plan = ValidationPlan(project_type="python-pytest", steps=[], reason="t", pack_name="")
        outcome = ValidationOutcome(passed=False, output="=== 2 failed, 1 passed in 0.1s ===")
        result: dict[str, Any] = {}
        convergence_update(ctx, {"task": "t", "iteration": 1}, outcome, plan, result)  # type: ignore[arg-type]
        return result

    on, off = run(True), run(False)
    assert on == off  # identical writes — the arms CANNOT diverge here, by construction
    assert on.get("test_failing_now") == 2  # and the input really was countable


# ── fingerprint compare + experiment verdict ─────────────────────────────────
def _fp(nodes: list, interrupts: list[str] | None = None, terminal: str = "delivered") -> dict:
    return {"schema": 1, "nodes": nodes, "interrupts": interrupts or [], "terminal": terminal}


def test_identical_fingerprints_are_invalid() -> None:
    a = _fp([["plan", ["plan"]], ["test", ["tests_passed"]]])
    d = compare_fingerprints(a, dict(a))
    assert not d.diverged and d.verdict == INVALID_EXPERIMENT_IDENTICAL_EXECUTION


def test_key_write_divergence_is_detected_and_located() -> None:
    a = _fp([["test", ["tests_passed"]]])
    b = _fp([["test", ["structural_spec_ok", "tests_passed"]]])
    d = compare_fingerprints(a, b)
    assert d.diverged and "visit 0" in d.detail


def test_terminal_divergence_is_detected() -> None:
    a = _fp([["plan", ["plan"]]], terminal="delivered")
    b = _fp([["plan", ["plan"]]], terminal="parked")
    assert compare_fingerprints(a, b).diverged


def test_experiment_verdict_requires_some_divergence() -> None:
    same = _fp([["plan", ["plan"]]])
    verdict, _ = experiment_verdict([same, dict(same)], [dict(same)])
    assert verdict == INVALID_EXPERIMENT_IDENTICAL_EXECUTION
    other = _fp([["plan", ["plan"]], ["reason", ["reason_attempts"]]])
    verdict, _ = experiment_verdict([same], [other])
    assert verdict is None  # scoreable


def test_experiment_verdict_fails_closed_on_missing_fingerprints() -> None:
    # Absence of evidence is not evidence of divergence — an unfingerprinted arm is INVALID.
    verdict, pairs = experiment_verdict([], [_fp([["plan", ["plan"]]])])
    assert verdict == INVALID_EXPERIMENT_IDENTICAL_EXECUTION and pairs == []


# ── the registry itself ──────────────────────────────────────────────────────
def test_registry_covers_every_posture_knob() -> None:
    # Every knob the autonomous posture flips must carry an honest liveness record — a knob
    # added to the posture without a registry row is exactly the unmeasured-control failure
    # ADR-0081 exists to prevent. (Mirrors test_oracle_posture._KNOBS by construction.)

    from mosaera_core.config import apply_oracle_posture

    base = Settings(
        autonomous_verified=True,
        tester_enabled=False,
        reason_on_stall_enabled=False,
        oracle_coverage=False,
        oracle_mutation_check=False,
    )
    flipped = {
        f
        for f in type(base).__dataclass_fields__
        if getattr(base, f) != getattr(apply_oracle_posture(base), f)
    }
    missing = flipped - set(registry_by_knob())
    assert not missing, f"posture knobs without a liveness record: {sorted(missing)}"


def test_registry_rungs_are_valid() -> None:
    from mosaera_core.bench.liveness import RUNGS

    assert all(r.rung in RUNGS for r in REGISTRY)


# ── C3/C4 sentinel: critic_claim_protocol diverges the critic path (#61) ─────
def test_critic_claim_protocol_diverges_the_dispose_path(
    workspace: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ON routes through critic_policy.dispose (verified rows in outcome_verdict); OFF keeps
    the legacy verdict byte-identical. Driven through the REAL critic_node with a fake bridge."""
    from types import SimpleNamespace as NS

    from mosaera_core.graph.nodes_critic import critic_node

    calls: list[dict] = []

    def fake_critic(task, plan, diff, test_output, overstrict, config=None, claims=None):
        calls.append({"claims": claims})
        if claims is not None:  # protocol path: rows the policy must dispose
            return {
                "rows": [
                    {
                        "claim_id": "1-c1",
                        "verdict": "REFUTED",
                        "requirement_quote": "prints every matching note in id order",
                        "evidence_quote": "return None  # not implemented",
                    }
                ],
                "fallback": None,
            }
        return {"vetoed": False, "reason": "legacy ship"}

    def ctx(protocol: bool):
        return NS(
            settings=NS(critic_claim_protocol=protocol, held_out_ok=lambda: True),
            workspace=NS(
                tree_hash=lambda: "t1" if protocol else "t0",
                diff_all=lambda: "+return None  # not implemented",
            ),
            agents=NS(critic=fake_critic),
            evidence_memo={},
        )

    state = {
        "tests_passed": True,
        "task": "search prints every matching note in id order",
        "claims": [
            # A claim in the critic's SURVIVING residual jurisdiction — the vetoable path this
            # sentinel exists to pin. `ast_transformation_contract` evaluates `unevaluable`
            # against this stub workspace: an oracle EXISTS and could not run, which is exactly
            # where a model judgement still adds information.
            #
            # Was `oracle_kind: "none"` until 2026-08-11, when `unbound` was removed from the
            # residual (9 vetoes in 260 runs, all 9 wrong, 8 of them on premise sentences). The
            # fixture then pinned a path that can no longer veto, so the sentinel would have gone
            # green for the wrong reason — the vacuous-fixture failure `test_doc_claims` hit on
            # 2026-08-10. Changed deliberately, not to make the suite pass.
            {
                "id": "1-c1",
                "text": "prints every matching note in id order",
                "material": True,
                "oracle_kind": "ast_transformation_contract",
            }
        ],
        "test_output": "1 passed",
        "authored_tests": [],
    }
    monkeypatch.setattr("mosaera_core.graph.nodes_critic._overstrict_evidence", lambda c, s: "")
    on = critic_node(ctx(True), dict(state), None)  # type: ignore[arg-type]
    off = critic_node(ctx(False), dict(state), None)  # type: ignore[arg-type]
    # ON: the verified REFUTED row vetoes via the deterministic policy, rows recorded.
    assert on["outcome_verdict"]["vetoed"] is True
    assert on["outcome_verdict"]["rows"][0]["verified"] is True
    # OFF: legacy shape, no rows — the arms genuinely diverge (C4 at the state-write level).
    assert off["outcome_verdict"] == {"vetoed": False, "reason": "legacy ship"}
    assert calls[0]["claims"] is not None and calls[1]["claims"] is None


# ── Decision 3, mechanised: an invalid experiment has no numbers ─────────────
#
# `experiment_verdict` had zero production callers, so nothing stopped an arm-identical
# A/B from producing effectiveness numbers that then reached a roadmap claim. That is
# ADR-0081's own instance #4. `experiment_report` runs the check FIRST.


def _card(fp: dict | None, outcome: str) -> dict:
    return {"meta": {"fingerprint": fp, "outcome": outcome}}


_FP_A = {
    "nodes": [["plan", ["plan"]], ["implement", ["diff"]]],
    "interrupts": [],
    "terminal": "delivered",
}
_FP_B = {
    "nodes": [["plan", ["plan"]], ["author_tests", ["authored"]]],
    "interrupts": [],
    "terminal": "delivered",
}


def test_identical_arms_yield_the_verdict_and_no_effect() -> None:
    from mosaera_core.bench.liveness import experiment_report

    # Both arms ran the same path — the instance-#4 shape — but the outcomes differ, which
    # is exactly the noise that would otherwise be reported as an effect.
    report = experiment_report(
        [_card(_FP_A, "clean_deliver"), _card(_FP_A, "clean_deliver")],
        [_card(_FP_A, "honest_park"), _card(_FP_A, "clean_deliver")],
    )
    assert report.verdict == INVALID_EXPERIMENT_IDENTICAL_EXECUTION
    assert report.scoreable is False
    assert report.effect is None, "an experiment that never diverged must yield no numbers"


def test_diverged_arms_are_scoreable_and_carry_the_tallies() -> None:
    from mosaera_core.bench.liveness import experiment_report

    report = experiment_report([_card(_FP_A, "clean_deliver")], [_card(_FP_B, "honest_park")])
    assert report.verdict is None and report.scoreable is True
    assert report.effect == {"a": {"clean_deliver": 1}, "b": {"honest_park": 1}}


def test_an_arm_whose_capture_failed_is_not_scoreable() -> None:
    from mosaera_core.bench.liveness import experiment_report

    # Fingerprints absent (pre-capture repeats, or a capture fault): no evidence of
    # divergence is not evidence of divergence.
    report = experiment_report([_card(None, "clean_deliver")], [_card(_FP_B, "false_ship")])
    assert report.verdict == INVALID_EXPERIMENT_IDENTICAL_EXECUTION
    assert report.effect is None


def test_aggregate_cards_carry_their_fingerprint_list() -> None:
    from mosaera_core.bench.liveness import fingerprints_of

    # `average()` stores the LIST (one per repeat, None for repeats predating capture).
    agg = {"meta": {"fingerprints": [_FP_A, None, _FP_B], "outcome": "clean_deliver"}}
    assert fingerprints_of([agg]) == [_FP_A, _FP_B]


# ── the guard's own liveness ─────────────────────────────────────────────────
#
# check_control_liveness.py exists to catch controls that cannot fire, and for all of
# Wave 1 it could not fire itself: report-only, wired into nothing, returning 0 on every
# finding. These pin the two checks that now bite, so the guard cannot quietly regress to
# advisory again.


def _run_guard() -> tuple[int, str]:
    import subprocess
    import sys as _sys
    from pathlib import Path as _Path

    script = _Path(__file__).resolve().parents[3] / "scripts" / "check_control_liveness.py"
    # Fixed argv, both elements derived from this file's own location — no input.
    proc = subprocess.run(  # noqa: S603
        [_sys.executable, str(script)], capture_output=True, text=True, check=False
    )
    return proc.returncode, proc.stdout


def test_the_guard_passes_on_the_real_registry() -> None:
    code, out = _run_guard()
    assert code == 0, out
    # The backlog is REPORTED, not hidden — that visibility is the point of grandfathering.
    assert "sentinel backlog" in out


def test_the_guard_names_the_grandfathered_backlog_from_the_registry() -> None:
    # The allowlist must describe the registry, not drift from it: every grandfathered name
    # is a real posture knob that is genuinely still below C4. A stale name would silently
    # widen the ratchet's blind spot.
    import importlib.util
    from pathlib import Path as _Path

    script = _Path(__file__).resolve().parents[3] / "scripts" / "check_control_liveness.py"
    spec = importlib.util.spec_from_file_location("_guard", script)
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)

    by_knob = registry_by_knob()
    for knob in guard.GRANDFATHERED:
        assert knob in by_knob, f"{knob} is grandfathered but has no registry row"
        assert not by_knob[knob].rung.startswith(("C4", "C5")), (
            f"{knob} has reached {by_knob[knob].rung} — remove it from GRANDFATHERED so the "
            "ratchet holds the gain"
        )


def _engagement_card(
    outcome: str, fp: dict | None = None, applied: list[str] | None = None
) -> dict:
    meta: dict = {"outcome": outcome}
    if fp is not None:
        meta["fingerprint"] = fp
    if applied is not None:
        meta["clauses_applied"] = applied
    return {"meta": meta}


_SAME = {"nodes": [["plan", ["plan"]], ["gate", ["approved"]]], "interrupts": [], "terminal": "x"}


def test_result_divergence_alone_is_not_validity() -> None:
    """The correction that matters, pinned so it cannot come back.

    An input-side A/B tempts you to accept "the arms' RESULTS differed" as proof the lever worked.
    It is not: two runs of ONE configuration produce different outcomes routinely — that is model
    nondeterminism — so scoring on result-divergence licenses attributing noise to the lever,
    which is the exact failure this ladder exists to stop.
    """
    from mosaera_core.bench.liveness import (
        INVALID_EXPERIMENT_IDENTICAL_EXECUTION,
        experiment_report,
    )

    a = [_engagement_card("clean_deliver", _SAME), _engagement_card("clean_deliver", _SAME)]
    b = [_engagement_card("honest_park", _SAME), _engagement_card("clean_deliver", _SAME)]
    report = experiment_report(a, b)
    assert report.verdict == INVALID_EXPERIMENT_IDENTICAL_EXECUTION
    assert report.effect is None, "differing outcomes must not, alone, unlock the numbers"


def test_an_input_side_lever_is_scoreable_when_the_control_demonstrably_fired() -> None:
    """The second validity path: identical execution, but one arm's control CHANGED a check.

    A brief edit or a standing decision routes the graph identically — same nodes, same terminal —
    so the fingerprint is blind to it by design. `clauses_applied` is written only when a clause
    really altered the constraint that was checked, so it is engagement rather than configuration.
    """
    from mosaera_core.bench.liveness import experiment_report

    off = [_engagement_card("honest_park", _SAME, applied=[])]
    on = [_engagement_card("clean_deliver", _SAME, applied=["structural.body_statements=5"])]
    report = experiment_report(off, on)
    assert report.scoreable
    assert report.effect == {"a": {"honest_park": 1}, "b": {"clean_deliver": 1}}
    assert any("controls engaged differ" in d.detail for d in report.divergences)


def test_a_configured_but_unfired_control_is_still_invalid() -> None:
    """Configuration is not engagement. A clause loaded and never used changed nothing."""
    from mosaera_core.bench.liveness import (
        INVALID_EXPERIMENT_IDENTICAL_EXECUTION,
        experiment_report,
    )

    off = [_engagement_card("honest_park", _SAME, applied=[])]
    on = [
        _engagement_card("clean_deliver", _SAME, applied=[])
    ]  # clause present, never altered a check
    assert experiment_report(off, on).verdict == INVALID_EXPERIMENT_IDENTICAL_EXECUTION
