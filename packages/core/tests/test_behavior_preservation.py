"""The deterministic behaviour-preservation detector (ADR-0066)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from mosaera_core.behavior_preservation import is_behavior_preserving
from mosaera_core.graph._proctor_authoring import _behavior_preservation_block

_CASES = Path(__file__).resolve().parents[1] / "mosaera_core" / "bench" / "cases"


def _brief(case_id: str) -> str:
    return (_CASES / case_id / "brief.md").read_text(encoding="utf-8")


def test_fires_on_the_refactor_case() -> None:
    # MCB-05 is the one refactor case ("Refactor ... without changing its behaviour ...
    # a pure refactor"). The detector must fire so the differential-golden-master guidance injects.
    assert is_behavior_preserving(_brief("MCB-05")) is True


def test_silent_on_non_refactor_cases() -> None:
    # A bug-fix (MCB-09) and a feature (MCB-10) are NOT behaviour-preserving tasks — even MCB-10's
    # scoped "keep the existing get/set behaviour unchanged" clause must not trip it (it ADDS a
    # feature). Deny-by-default precision: refactor-only guidance never reaches a feature/bug-fix.
    assert is_behavior_preserving(_brief("MCB-09")) is False
    assert is_behavior_preserving(_brief("MCB-10")) is False
    assert is_behavior_preserving(_brief("MCB-04")) is False
    # MCB-11 (the live scaffold-misfire case): a feature whose symbol-scoped "keep the existing
    # `+`/`-` behaviour unchanged" constraint must NOT fire task-only — the misfire came from the
    # PM's paraphrase dropping the symbols, which the scaffold no longer consults.
    assert is_behavior_preserving(_brief("MCB-11")) is False


def test_explicit_preservation_phrases_fire() -> None:
    for phrase in (
        "Refactor checkout without changing its behaviour.",
        "Restructure the module but preserve the behaviour.",
        "This is a pure refactor.",
        "The output must be identical for every input.",
        "Do not change any observable behaviour.",
        "Extract helpers; the results must be the same.",
        "A behaviour-preserving cleanup of the parser.",
        "keep the behavior unchanged",  # American spelling
    ):
        assert is_behavior_preserving(phrase) is True, phrase


def test_bare_refactor_verb_alone_does_not_fire() -> None:
    # Deny-by-default: the STRUCTURAL verb without a preservation clause is not enough — a feature
    # can say "refactor and add X". We require an explicit "behaviour/output unchanged" promise.
    assert is_behavior_preserving("Refactor the parser and add JSON support.") is False
    assert is_behavior_preserving("Decompose the god-file into modules and add a CLI.") is False
    assert is_behavior_preserving("Add a --verbose flag to the tool.") is False


def test_comparative_same_output_as_input_path_does_not_fire() -> None:
    # The #53 live-drive false positive: "same output as <another input path>" is a feature
    # CONSISTENCY clause (two entry points must agree), NOT a promise that behaviour is
    # unchanged vs. the pre-change code. Quincy's decompose emits this shape readily; it must
    # never arm the refactor-only guidance / structural oracle against a feature task.
    for phrase in (
        "Piping a password via stdin produces the same output as providing it on the command line.",
        "stdin input gives the same result as the argv path",
        "the same output as the reference implementation of the competitor",
        # Plural forms — the red-team's lookahead-bypass finding: `s?` must not backtrack
        # past the guard ("same resultS as <endpoint>" is the #53 shape, pluralized).
        "The new endpoint returns the same results as /v1/users",
        "Batch mode yields the same results as the interactive mode",
        "Dry-run mode must show identical results as a real run would produce",
        "The gzip and zstd paths write the same outputs as each other",
    ):
        assert is_behavior_preserving(phrase) is False, phrase


def test_baseline_referent_same_output_as_fires() -> None:
    # A comparison against the PRE-CHANGE baseline is exactly the preservation promise.
    for phrase in (
        "Refactor: must return the same output as before.",
        "identical results as the original implementation",
        "the same behaviour as it does today",
        "keep the same output as the existing version",
        # Widened baseline referents (red-team: the plural fix would otherwise unmask these).
        "produces the same output as the legacy code",
        "the same results as the prior version",
        "identical output as the pre-refactor implementation",
    ):
        assert is_behavior_preserving(phrase) is True, phrase


def test_reads_plan_and_design_too() -> None:
    # The signal may live in the plan/design, not just the task.
    assert is_behavior_preserving("do the thing", plan="a pure refactor, no output change") is True
    assert is_behavior_preserving("do the thing", design="preserve the behaviour exactly") is True


def _ctx(guard: bool) -> Any:
    return SimpleNamespace(settings=SimpleNamespace(behavior_preservation_guard=guard))


def test_guidance_block_injects_only_when_guarded_and_detected() -> None:
    refactor: Any = {"task": "Refactor checkout without changing behaviour."}
    feature: Any = {"task": "Add a --verbose flag to the tool."}
    # guard ON + detected refactor -> the differential-golden-master guidance is injected
    block = _behavior_preservation_block(_ctx(True), refactor)
    assert "differential golden-master" in block.lower()
    assert "frozen" in block.lower() and "hypothesis" in block.lower()  # the key how-tos
    # guard ON + NOT a refactor -> empty (a feature never sees refactor-only guidance)
    assert _behavior_preservation_block(_ctx(True), feature) == ""
    # guard OFF -> empty even for a refactor (deny-by-default)
    assert _behavior_preservation_block(_ctx(False), refactor) == ""
