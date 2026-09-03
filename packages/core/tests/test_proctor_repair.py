"""#54 (ADR-0058) — the Proctor's up-front validate/repair wiring. Driven with a fake workspace +
fake agents (no graph, no models, no sandbox for the proactive helper). The reactive
diagnose-and-park was removed in #56 (ADR-0060) — the honest-stop's deterministic diagnosis
replaced the LLM park-note.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from mosaera_core.graph._proctor_authoring import baseline_test_sources
from mosaera_core.graph.nodes_plan import _proctor_validate_repair
from mosaera_core.testintegrity import integrity_baseline, integrity_hash
from mosaera_core.tools.repo import Workspace, hash_files


def _ws(root: Any) -> Any:
    """A REAL `Workspace`, git-init'd. The fake it replaces is why this bug survived the suite.

    This was `SimpleNamespace(root=root, file_listing=lambda: <uncapped local glob>)`. The real
    `file_listing` caps at 300 and the fake did not, so every test here exercised a workspace that
    does not exist — and the protected-set blindness (empty above the cap, and empty on any repo
    without a root `tests/`) stayed invisible behind a green suite. A fake more capable than the
    real object proves nothing about production.
    """
    import subprocess

    subprocess.run(("git", "init", "-q"), cwd=root, check=True, capture_output=True)  # noqa: S607 — git from PATH, no shell; test fixture
    return Workspace(root=root, run_id="t", branch="b")


# --- Proactive validate/repair wiring (_proctor_validate_repair) ---


def test_repair_of_a_preexisting_test_is_recorded_as_a_proctor_edit(tmp_path: Any) -> None:
    (tmp_path / "tests").mkdir()
    t = tmp_path / "tests" / "test_a.py"
    t.write_text("def test_a():\n    assert compute() == 2\n", encoding="utf-8")
    ws = _ws(tmp_path)
    baseline = integrity_baseline(ws)
    before = hash_files(ws, ws.file_listing())

    def repair(instruction: str, config: Any, corrections: Any = ()) -> None:
        # The Proctor loosens an over-strict pre-existing test (task said "non-zero", not "== 2").
        t.write_text("def test_a():\n    assert compute() != 0\n", encoding="utf-8")

    ctx: Any = SimpleNamespace(
        workspace=ws,
        agents=SimpleNamespace(validate_and_repair_tests=repair),
        settings=SimpleNamespace(
            proctor_faithfulness_guard=False,
            behavior_preservation_guard=False,
        ),
    )
    state: Any = {"task": "t", "plan": "", "design": "", "integrity_baseline": baseline}
    authored_out, proctor_edits = _proctor_validate_repair(ctx, state, {}, [], before)

    # The pre-existing edit is recorded in the integrity hash space, NOT folded into authored.
    assert proctor_edits == {"tests/test_a.py": integrity_hash(ws, "tests/test_a.py")}
    assert authored_out == []


def test_a_new_test_file_is_authored_not_a_proctor_edit(tmp_path: Any) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(
        "def test_a():\n    assert compute() == 2\n", encoding="utf-8"
    )
    ws = _ws(tmp_path)
    baseline = integrity_baseline(ws)
    before = hash_files(ws, ws.file_listing())

    def repair(instruction: str, config: Any, corrections: Any = ()) -> None:
        # The Proctor strengthens by ADDING a new edge-case test file (new authorship).
        (tmp_path / "tests" / "test_edge.py").write_text(
            "def test_edge():\n    assert compute() != 0\n", encoding="utf-8"
        )

    ctx: Any = SimpleNamespace(
        workspace=ws,
        agents=SimpleNamespace(validate_and_repair_tests=repair),
        settings=SimpleNamespace(
            proctor_faithfulness_guard=False,
            behavior_preservation_guard=False,
        ),
    )
    state: Any = {"task": "t", "plan": "", "design": "", "integrity_baseline": baseline}
    authored_out, proctor_edits = _proctor_validate_repair(ctx, state, {}, [], before)

    assert authored_out == ["tests/test_edge.py"]  # a NEW file → authored
    assert proctor_edits == {}  # no pre-existing test changed


def test_a_faithful_suite_left_untouched_yields_no_edits(tmp_path: Any) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(
        "def test_a():\n    assert compute() != 0\n", encoding="utf-8"
    )
    ws = _ws(tmp_path)
    baseline = integrity_baseline(ws)
    before = hash_files(ws, ws.file_listing())

    def repair(instruction: str, config: Any, corrections: Any = ()) -> None:
        return None  # the Proctor judges the suite faithful → changes nothing

    ctx: Any = SimpleNamespace(
        workspace=ws,
        agents=SimpleNamespace(validate_and_repair_tests=repair),
        settings=SimpleNamespace(
            proctor_faithfulness_guard=False,
            behavior_preservation_guard=False,
        ),
    )
    state: Any = {"task": "t", "plan": "", "design": "", "integrity_baseline": baseline}
    authored_out, proctor_edits = _proctor_validate_repair(ctx, state, {}, [], before)

    assert authored_out == [] and proctor_edits == {}


def test_emptying_a_preexisting_test_is_not_recorded_as_an_excuse(tmp_path: Any) -> None:
    # Red-team #54 FN1: a repair that EMPTIES / guts a pre-existing test drops its requirement — it
    # must NOT be recorded as a sanctioned proctor_edit (else the tamper guard would excuse it and a
    # dropped requirement could ship). The builder-side assertion-floor gate keeps it out.
    (tmp_path / "tests").mkdir()
    t = tmp_path / "tests" / "test_a.py"
    t.write_text("def test_a():\n    assert compute() == 2\n", encoding="utf-8")
    ws = _ws(tmp_path)
    baseline = integrity_baseline(ws)
    before = hash_files(ws, ws.file_listing())

    def repair(instruction: str, config: Any, corrections: Any = ()) -> None:
        t.write_text("", encoding="utf-8")  # emptied — requirement gone

    ctx: Any = SimpleNamespace(
        workspace=ws,
        agents=SimpleNamespace(validate_and_repair_tests=repair),
        settings=SimpleNamespace(
            proctor_faithfulness_guard=False,
            behavior_preservation_guard=False,
        ),
    )
    state: Any = {"task": "t", "plan": "", "design": "", "integrity_baseline": baseline}
    _, proctor_edits = _proctor_validate_repair(ctx, state, {}, [], before)
    assert proctor_edits == {}  # NOT excused → tampered_integrity will park the run


def test_gutting_a_preexisting_test_to_no_assertion_is_not_excused(tmp_path: Any) -> None:
    # Same, for a gut-to-`pass` (non-empty, so it dodges a naive empty-check, but asserts nothing).
    (tmp_path / "tests").mkdir()
    t = tmp_path / "tests" / "test_a.py"
    t.write_text("def test_a():\n    assert compute() == 2\n", encoding="utf-8")
    ws = _ws(tmp_path)
    baseline = integrity_baseline(ws)
    before = hash_files(ws, ws.file_listing())

    def repair(instruction: str, config: Any, corrections: Any = ()) -> None:
        t.write_text("def test_a():\n    pass\n", encoding="utf-8")  # asserts nothing

    ctx: Any = SimpleNamespace(
        workspace=ws,
        agents=SimpleNamespace(validate_and_repair_tests=repair),
        settings=SimpleNamespace(
            proctor_faithfulness_guard=False,
            behavior_preservation_guard=False,
        ),
    )
    state: Any = {"task": "t", "plan": "", "design": "", "integrity_baseline": baseline}
    _, proctor_edits = _proctor_validate_repair(ctx, state, {}, [], before)
    assert proctor_edits == {}  # a repair that no longer asserts real is not a legitimate repair


def test_gutting_via_an_unreachable_assert_is_not_excused(tmp_path: Any) -> None:
    # Red-team #54 R2: the assertion floor was reachability-blind — a gut that hides the assert in a
    # nested uncalled helper (or a dead branch / lambda / empty parametrize) cleared the floor and
    # got excused. The reachability-aware floor now rejects it → not recorded → tamper park.
    (tmp_path / "tests").mkdir()
    t = tmp_path / "tests" / "test_a.py"
    t.write_text("def test_a():\n    assert compute() == 2\n", encoding="utf-8")
    ws = _ws(tmp_path)
    baseline = integrity_baseline(ws)
    before = hash_files(ws, ws.file_listing())

    def repair(instruction: str, config: Any, corrections: Any = ()) -> None:
        # assert present but inside a nested helper that is never called → never runs
        t.write_text("def test_a():\n    def _inner():\n        assert compute() == 2\n", "utf-8")

    ctx: Any = SimpleNamespace(
        workspace=ws,
        agents=SimpleNamespace(validate_and_repair_tests=repair),
        settings=SimpleNamespace(
            proctor_faithfulness_guard=False,
            behavior_preservation_guard=False,
        ),
    )
    state: Any = {"task": "t", "plan": "", "design": "", "integrity_baseline": baseline}
    _, proctor_edits = _proctor_validate_repair(ctx, state, {}, [], before)
    assert proctor_edits == {}  # reachability-blind gut is no longer excused


# --- Faithfulness guard: over-strict findings reach the repair instruction (#57, ADR-0062) ---


def test_faithfulness_guard_names_overstrict_findings_in_the_repair_instruction(
    tmp_path: Any,
) -> None:
    (tmp_path / "tests").mkdir()
    # An authored test pinning exact stdout whitespace the spec leaves open.
    (tmp_path / "tests" / "test_cli.py").write_text(
        "def test_list(result):\n"
        '    lines = result.stdout.strip().split("\\n")\n'
        '    assert lines[0] == "1 [ ] Buy milk"\n',
        encoding="utf-8",
    )
    ws = _ws(tmp_path)
    before = hash_files(ws, ws.file_listing())
    seen: list[str] = []

    def repair(instruction: str, config: Any, corrections: Any = ()) -> None:
        seen.append(instruction)

    ctx: Any = SimpleNamespace(
        workspace=ws,
        agents=SimpleNamespace(validate_and_repair_tests=repair),
        settings=SimpleNamespace(
            proctor_faithfulness_guard=True,
            behavior_preservation_guard=False,
        ),
    )
    state: Any = {"task": "list the tasks", "plan": "", "design": "", "integrity_baseline": {}}
    _proctor_validate_repair(ctx, state, {}, ["tests/test_cli.py"], before)

    assert len(seen) == 1
    assert "Assertions to repair" in seen[0]
    assert "exact_output_equality" in seen[0]
    assert "tests/test_cli.py" in seen[0]


def test_faithfulness_guard_off_appends_nothing(tmp_path: Any) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_cli.py").write_text(
        "def test_list(result):\n"
        '    lines = result.stdout.strip().split("\\n")\n'
        '    assert lines[0] == "1 [ ] Buy milk"\n',
        encoding="utf-8",
    )
    ws = _ws(tmp_path)
    before = hash_files(ws, ws.file_listing())
    seen: list[str] = []

    def repair(instruction: str, config: Any, corrections: Any = ()) -> None:
        seen.append(instruction)

    ctx: Any = SimpleNamespace(
        workspace=ws,
        agents=SimpleNamespace(validate_and_repair_tests=repair),
        settings=SimpleNamespace(
            proctor_faithfulness_guard=False,
            behavior_preservation_guard=False,
        ),
    )
    state: Any = {"task": "list the tasks", "plan": "", "design": "", "integrity_baseline": {}}
    _proctor_validate_repair(ctx, state, {}, ["tests/test_cli.py"], before)

    assert "Assertions to repair" not in seen[0]


# --- Coder-blind timing: repair runs only on the first (pre-coder) authoring pass (FN2) ---


def _author_ctx(root: Any, *, iteration: int, repair_spy: list[str]) -> Any:
    def author_tests(instruction: str, config: Any = None, corrections: Any = ()) -> None:
        pass

    def validate_and_repair_tests(
        instruction: str, config: Any = None, corrections: Any = ()
    ) -> None:
        repair_spy.append("called")  # records that the repair pass ran

    ws = _ws(root)
    agents = SimpleNamespace(
        tester_enabled=True,
        author_tests=author_tests,
        validate_and_repair_tests=validate_and_repair_tests,
    )
    settings = SimpleNamespace(
        tester_repairs_tests=True,
        proctor_faithfulness_guard=False,
        behavior_preservation_guard=False,
        refactor_oracle_scaffold=False,  # deny-by-default → the Proctor authors as usual
    )
    return SimpleNamespace(
        workspace=ws, agents=agents, settings=settings, sandbox=object(), protected_tests=set()
    )


def test_repair_runs_on_the_coder_blind_first_pass(tmp_path: Any, monkeypatch: Any) -> None:
    from mosaera_core.graph import nodes_plan

    (tmp_path / "tests").mkdir()
    monkeypatch.setattr(nodes_plan, "authored_seed_results", lambda *a, **k: (True, []))
    monkeypatch.setattr(nodes_plan, "authored_suite_asserts_behaviour", lambda *a, **k: True)
    spy: list[str] = []
    ctx = _author_ctx(tmp_path, iteration=1, repair_spy=spy)
    nodes_plan.author_tests_node(ctx, {"task": "t", "iteration": 1}, config={})
    assert spy == ["called"]  # first pass (iteration<=1) → the repair ran (coder-blind)


def test_repair_skipped_on_a_replan_with_coder_code_on_disk(
    tmp_path: Any, monkeypatch: Any
) -> None:
    # Red-team #54 FN2: a gate-deny re-plan re-enters author_tests with the coder's code ON DISK.
    # The repair (which grants the tamper excuse) must NOT run there, or it could fit a test to the
    # coder's diff and launder it. iteration>=2 identifies the post-coder pass.
    from mosaera_core.graph import nodes_plan

    (tmp_path / "tests").mkdir()
    monkeypatch.setattr(nodes_plan, "authored_seed_results", lambda *a, **k: (True, []))
    monkeypatch.setattr(nodes_plan, "authored_suite_asserts_behaviour", lambda *a, **k: True)
    spy: list[str] = []
    ctx = _author_ctx(tmp_path, iteration=2, repair_spy=spy)
    out = nodes_plan.author_tests_node(ctx, {"task": "t", "iteration": 2}, config={})
    assert spy == []  # re-plan pass → repair skipped
    assert "proctor_edits" not in out  # no excuse emitted on a post-coder pass


def test_author_tests_runs_once_skips_reauthoring_when_already_authored(tmp_path: Any) -> None:
    # ADR-0068: the graph re-enters author_tests on EVERY re-plan, but re-authoring re-writes the
    # engine's OWN baselined tests (the scaffold re-freezes the now-refactored module) → the tamper
    # guard false-trips → a self-inflicted thrash_park on correct code (the dominant thrash cause).
    # The run-once guard returns {} and re-authors NOTHING once tests are already authored.
    from mosaera_core.graph import nodes_plan

    spy: list[str] = []
    ctx = _author_ctx(tmp_path, iteration=2, repair_spy=spy)
    out = nodes_plan.author_tests_node(
        ctx,
        {"task": "t", "iteration": 2, "authored_tests": ["tests/test_calc.py"]},
        config={},
    )
    assert out == {}  # no-op: no re-author, no new tests_baseline, no contract message re-emitted
    assert spy == []  # neither the author nor the repair pass ran


# --- P4: acceptance-test bodies handed to the coder (#55) ---


def test_acceptance_contract_includes_test_bodies(tmp_path: Any) -> None:
    from mosaera_core.graph.nodes_plan import _acceptance_contract

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(
        "def test_a():\n    assert fmt(3) == '3 [ ] x'\n", encoding="utf-8"
    )
    out = _acceptance_contract(_ws(tmp_path), ["tests/test_a.py"])
    assert "tests/test_a.py" in out
    assert "assert fmt(3) == '3 [ ] x'" in out  # the EXACT expected value, not just the file name


def test_acceptance_contract_caps_large_suites(tmp_path: Any) -> None:
    from mosaera_core.graph.nodes_plan import _acceptance_contract

    (tmp_path / "tests").mkdir()
    big = "body = '" + "x" * 5000 + "'\n"
    (tmp_path / "tests" / "test_big.py").write_text(big, encoding="utf-8")
    out = _acceptance_contract(_ws(tmp_path), ["tests/test_big.py"], cap=200)
    assert len(out) < 600  # bounded — can't blow the coder's context
    assert "truncated" in out


def test_acceptance_contract_empty(tmp_path: Any) -> None:
    from mosaera_core.graph.nodes_plan import _acceptance_contract

    assert "no test files" in _acceptance_contract(_ws(tmp_path), [])


# --- the assertion profile refuses a WEAKENING repair (#66, ADR-0087 §6) -----------------------
#
# The assertion floor was necessary but not sufficient: it is `any()` over the file, so a repair
# that drops seven of eight tests still clears it while one real assertion survives. The Proctor
# repairs UNATTENDED — no human sees the diff — so a proven loss REFUSES the excuse outright.


def _repair_ctx(ws: Any, repair: Any) -> Any:
    return SimpleNamespace(
        workspace=ws,
        agents=SimpleNamespace(validate_and_repair_tests=repair),
        settings=SimpleNamespace(
            proctor_faithfulness_guard=False,
            behavior_preservation_guard=False,
        ),
    )


def _drive_repair(tmp_path: Any, original: str, repaired: str) -> tuple[Any, dict[str, str]]:
    (tmp_path / "tests").mkdir()
    t = tmp_path / "tests" / "test_a.py"
    t.write_text(original, encoding="utf-8")
    ws = _ws(tmp_path)
    baseline = integrity_baseline(ws)
    before = hash_files(ws, ws.file_listing())
    fake_ctx: Any = SimpleNamespace(workspace=ws)
    before_sources = baseline_test_sources(fake_ctx, baseline)

    def repair(instruction: str, config: Any, corrections: Any = ()) -> None:
        t.write_text(repaired, encoding="utf-8")

    state: Any = {"task": "t", "plan": "", "design": "", "integrity_baseline": baseline}
    _, proctor_edits = _proctor_validate_repair(
        _repair_ctx(ws, repair), state, {}, [], before, before_sources=before_sources
    )
    return ws, proctor_edits


_TWO_TESTS = (
    "def test_a():\n"
    "    assert compute() == 2\n"
    "    assert compute() > 0\n"
    "\n"
    "def test_b():\n"
    "    assert render() == 'x'\n"
)


def test_a_repair_that_drops_a_whole_test_is_not_excused(tmp_path: Any) -> None:
    """The gap the floor could not see: `test_b` is gone, and `test_a`'s surviving assertion
    still clears `authored_suite_asserts_behaviour`. Unexcused ⇒ tampered_integrity parks."""
    _, proctor_edits = _drive_repair(
        tmp_path, _TWO_TESTS, "def test_a():\n    assert compute() == 2\n"
    )
    assert proctor_edits == {}


def test_a_repair_that_shrinks_one_test_is_not_excused(tmp_path: Any) -> None:
    repaired = _TWO_TESTS.replace("    assert compute() > 0\n", "")
    _, proctor_edits = _drive_repair(tmp_path, _TWO_TESTS, repaired)
    assert proctor_edits == {}


def test_an_honest_relaxation_is_still_excused(tmp_path: Any) -> None:
    """The false-park direction, which is the expensive one. Loosening an OVER-STRICT assertion
    (`== 2` where the task said "non-zero") keeps the count, so the repair the whole #54 mechanism
    exists for is untouched."""
    repaired = _TWO_TESTS.replace("assert compute() == 2", "assert compute() != 0")
    ws, proctor_edits = _drive_repair(tmp_path, _TWO_TESTS, repaired)
    assert proctor_edits == {"tests/test_a.py": integrity_hash(ws, "tests/test_a.py")}


def test_a_strengthening_repair_is_excused(tmp_path: Any) -> None:
    repaired = _TWO_TESTS + "\ndef test_c():\n    assert total() == 3\n"
    ws, proctor_edits = _drive_repair(tmp_path, _TWO_TESTS, repaired)
    assert proctor_edits == {"tests/test_a.py": integrity_hash(ws, "tests/test_a.py")}


def test_no_pristine_source_refuses_the_excuse(tmp_path: Any) -> None:
    """Deny-by-default on the unknown side: with nothing to compare against we cannot prove
    nothing was lost, so the repair is not excused. Unknown is never clean."""
    (tmp_path / "tests").mkdir()
    t = tmp_path / "tests" / "test_a.py"
    t.write_text(_TWO_TESTS, encoding="utf-8")
    ws = _ws(tmp_path)
    baseline = integrity_baseline(ws)
    before = hash_files(ws, ws.file_listing())

    def repair(instruction: str, config: Any, corrections: Any = ()) -> None:
        t.write_text(_TWO_TESTS.replace("== 2", "!= 0"), encoding="utf-8")

    state: Any = {"task": "t", "plan": "", "design": "", "integrity_baseline": baseline}
    _, proctor_edits = _proctor_validate_repair(
        _repair_ctx(ws, repair), state, {}, [], before, before_sources={}
    )
    assert proctor_edits == {}


def test_omitting_before_sources_keeps_the_old_behaviour(tmp_path: Any) -> None:
    """Back-compat pin: the parameter defaults to None, and None means 'not measured' — the
    floor alone decides, exactly as before. Only a caller that supplies sources gets the check."""
    (tmp_path / "tests").mkdir()
    t = tmp_path / "tests" / "test_a.py"
    t.write_text(_TWO_TESTS, encoding="utf-8")
    ws = _ws(tmp_path)
    baseline = integrity_baseline(ws)
    before = hash_files(ws, ws.file_listing())

    def repair(instruction: str, config: Any, corrections: Any = ()) -> None:
        t.write_text("def test_a():\n    assert compute() == 2\n", encoding="utf-8")

    state: Any = {"task": "t", "plan": "", "design": "", "integrity_baseline": baseline}
    _, proctor_edits = _proctor_validate_repair(_repair_ctx(ws, repair), state, {}, [], before)
    assert proctor_edits == {"tests/test_a.py": integrity_hash(ws, "tests/test_a.py")}
