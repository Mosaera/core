"""Repo shape + oracle plan — the onboarding flow's deterministic half (#121).

The property under test is the one the flow's whole honesty rests on: it must say a suite can
vouch ONLY when the same predicate the gate uses would say so, and it must recommend the Proctor
exactly where nothing else can supply independence.
"""

from __future__ import annotations

from pathlib import Path

from mosaera_core.graph._oracle_legs import LEG_NAMES
from mosaera_core.reposhape import SHAPES, classify_repo_shape, oracle_plan
from mosaera_core.tools.repo import Workspace

_ASSERTING_SUITE = "def test_adds():\n    assert 1 + 1 == 2\n"
# Collects and passes, asserts nothing about behaviour — a file, not an oracle.
_HOLLOW_SUITE = "def test_smoke():\n    pass\n"


def _ws(tmp_path: Path, files: dict[str, str]) -> Workspace:
    for rel, content in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return Workspace(root=tmp_path, run_id="t", branch="b")


# --- classification -----------------------------------------------------------------------


def test_empty_repo(tmp_path: Path) -> None:
    shape = classify_repo_shape(_ws(tmp_path, {}))
    assert shape.shape == "empty"
    assert shape.source_files == 0 and shape.test_files == 0
    assert shape.needs_an_oracle


def test_sources_without_tests_are_greenfield(tmp_path: Path) -> None:
    shape = classify_repo_shape(_ws(tmp_path, {"app.py": "def add(a, b):\n    return a + b\n"}))
    assert shape.shape == "greenfield"
    assert shape.source_files == 1 and shape.test_files == 0
    assert shape.needs_an_oracle


def test_test_files_that_assert_nothing_are_not_a_suite(tmp_path: Path) -> None:
    # The distinction the whole module exists for: counting `test_*` files would call this a
    # standing suite, and the gate would then refuse to credit it — the operator learns at the
    # park what they could have learned at setup.
    shape = classify_repo_shape(
        _ws(tmp_path, {"app.py": "x = 1\n", "tests/test_app.py": _HOLLOW_SUITE})
    )
    assert shape.shape == "sources_no_suite"
    assert shape.test_files == 1  # the FILE is counted honestly...
    assert shape.needs_an_oracle  # ...and still cannot vouch


def test_asserting_suite_is_a_standing_suite(tmp_path: Path) -> None:
    shape = classify_repo_shape(
        _ws(tmp_path, {"app.py": "x = 1\n", "tests/test_app.py": _ASSERTING_SUITE})
    )
    assert shape.shape == "standing_suite"
    assert not shape.needs_an_oracle


def test_classification_is_deterministic_and_in_the_declared_set(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"app.py": "x = 1\n", "tests/test_app.py": _ASSERTING_SUITE})
    first = classify_repo_shape(ws)
    assert first.shape in SHAPES
    assert classify_repo_shape(ws) == first  # same tree in, same answer out


def test_evidence_is_provenanced_and_names_the_planner(tmp_path: Path) -> None:
    shape = classify_repo_shape(_ws(tmp_path, {"app.py": "x = 1\n"}))
    assert shape.evidence  # never a bare claim
    assert any("tool:walk" in line for line in shape.evidence)
    assert any("tool:detect_validation_plan" in line for line in shape.evidence)
    assert shape.plan_reason  # the planner's own words, carried verbatim


# --- the oracle plan ----------------------------------------------------------------------


def test_greenfield_with_nothing_configured_cannot_be_verified(tmp_path: Path) -> None:
    shape = classify_repo_shape(_ws(tmp_path, {"app.py": "x = 1\n"}))
    plan = oracle_plan(shape, tester_enabled=False, test_cmd="")
    # This IS the newcomer's default state, and it is why their first run parks.
    assert plan.verified_possible is False
    assert plan.recommended_knobs == ("tester_enabled",)
    assert plan.recommend_test_cmd is True


def test_the_proctor_supplies_independence_on_any_repo(tmp_path: Path) -> None:
    shape = classify_repo_shape(_ws(tmp_path, {"app.py": "x = 1\n"}))
    plan = oracle_plan(shape, tester_enabled=True, test_cmd="")
    assert plan.legs["tester_vouched"] is True
    assert plan.verified_possible is True
    assert plan.recommended_knobs == ()  # nothing left to recommend


def test_an_operator_test_command_supplies_independence(tmp_path: Path) -> None:
    shape = classify_repo_shape(_ws(tmp_path, {"app.py": "x = 1\n"}))
    plan = oracle_plan(shape, tester_enabled=False, test_cmd="pytest -q")
    assert plan.legs["test_cmd"] is True
    assert plan.verified_possible is True
    assert plan.recommend_test_cmd is False
    # Whitespace is not a command.
    assert oracle_plan(shape, tester_enabled=False, test_cmd="   ").verified_possible is False


def test_a_standing_suite_needs_no_recommendation(tmp_path: Path) -> None:
    shape = classify_repo_shape(
        _ws(tmp_path, {"app.py": "x = 1\n", "tests/test_app.py": _ASSERTING_SUITE})
    )
    plan = oracle_plan(shape, tester_enabled=False, test_cmd="")
    assert plan.legs["standing_suite"] is True
    assert plan.verified_possible is True
    assert plan.recommended_knobs == ()  # the Proctor is not pushed where a suite already vouches


def test_structural_vouch_is_never_promised_from_the_repo_alone(tmp_path: Path) -> None:
    # It is earned per-item from a refactor/AST contract. Promising it at setup would be the
    # aspirational claim the instrument-trust rule forbids.
    shape = classify_repo_shape(_ws(tmp_path, {"app.py": "x = 1\n"}))
    plan = oracle_plan(shape, tester_enabled=False, test_cmd="")
    assert plan.legs["structural_vouch"] is False


def test_legs_use_the_gates_own_names(tmp_path: Path) -> None:
    # A second vocabulary for the same four routes is the drift `_oracle_legs` exists to prevent.
    shape = classify_repo_shape(_ws(tmp_path, {"app.py": "x = 1\n"}))
    plan = oracle_plan(shape, tester_enabled=False, test_cmd="")
    assert set(plan.legs) == set(LEG_NAMES)
