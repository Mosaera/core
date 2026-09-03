"""The deterministic acceptance spec-lint (#54 slice 0, ADR-0073)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mosaera_core.behavior_preservation import is_behavior_preserving, preservation_matches
from mosaera_core.spec_lint import (
    SpecFinding,
    checkability,
    curate_instruction,
    decidability,
    decidability_findings,
    diagnose_backlog,
    diagnose_item,
    lint_backlog,
    undecidable_reason,
)


def _item(item_id: int, title: str, acceptance: str, status: str = "todo") -> dict[str, Any]:
    return {
        "id": item_id,
        "title": title,
        "description": "",
        "acceptance": acceptance,
        "status": status,
    }


# --- R1: exact-value over-specification ---


def test_r1_fires_on_the_53_tuple_shape() -> None:
    # The literal acceptance that trapped the coder in the #53 drive: an invented
    # exact return tuple the Proctor pinned tamper-protected tests to.
    acceptance = (
        "- Calling `strength('short')` returns `(1, ['too short (len < 8)'])`.\n"
        "- Calling `strength('')` returns `(0, ['empty password'])`."
    )
    findings = lint_backlog([_item(1, "Add password_strength module", acceptance)])
    assert any(f.rule == "exact_value" and f.item_id == 1 for f in findings)


def test_r1_fires_on_backticked_exact_output() -> None:
    acceptance = "Running the CLI prints `4: length >= 8, has ['lower', 'upper']` to stdout."
    findings = lint_backlog([_item(2, "Create CLI", acceptance)])
    assert any(f.rule == "exact_value" for f in findings)


def test_r1_fires_on_exact_output_fence() -> None:
    acceptance = "Running `python cli.py Abc` outputs exactly\n```\nScore: 4\n```"
    findings = lint_backlog([_item(3, "Create CLI", acceptance)])
    assert any(f.rule == "exact_value" for f in findings)


def test_r1_silent_on_behavioural_acceptance() -> None:
    acceptance = (
        "- strength(password) returns a tuple (score, reasons) where score is an int 0-4 "
        "and reasons is a non-empty list of strings.\n"
        "- Any blocklisted password scores 0 with a reason mentioning it is common.\n"
        "- Tests assert score values and reason substrings, never exact reason lists."
    )
    assert lint_backlog([_item(4, "Add module", acceptance)]) == []


# --- R2: refactor-classifier collision ---


def test_r2_fires_on_preservation_phrasing_and_quotes_the_span() -> None:
    acceptance = "Piping via stdin produces the same output as before."
    findings = lint_backlog([_item(5, "Create CLI entry point", acceptance)])
    r2 = [f for f in findings if f.rule == "refactor_phrase"]
    assert r2 and "same output as before" in r2[0].detail


def test_r2_silent_on_plain_acceptance() -> None:
    acceptance = "stdin input is scored identically to argv input; both paths share one code path."
    assert lint_backlog([_item(6, "Create CLI", acceptance)]) == []


def test_preservation_matches_parity_with_classifier() -> None:
    # The accessor and the boolean must agree — same patterns, no drift.
    for text in (
        "a pure refactor, keep the behaviour unchanged",
        "produces the same output as the legacy code",
        "add a --verbose flag to the tool",
        "stdin gives the same result as the argv path",
    ):
        assert bool(preservation_matches(text)) is is_behavior_preserving(text), text


# --- R3: near-duplicate items ---


def test_r3_flags_the_53_redundant_tests_item() -> None:
    # Tonight's item #1 vs item #3: the module item's acceptance already required the tests
    # the third item re-demanded — it parked as "already satisfied".
    a = _item(
        1,
        "Add password_strength module",
        "unit tests for the strength function pass with pytest covering the scoring rules",
    )
    b = _item(
        3,
        "Add unit tests for strength function",
        "tests for the strength function scoring rules pass with pytest",
    )
    findings = lint_backlog([a, b])
    r3 = [f for f in findings if f.rule == "near_duplicate"]
    assert r3 and "#1" in r3[0].detail and "#3" in r3[0].detail


def test_r3_silent_on_distinct_items() -> None:
    a = _item(1, "Add password_strength module", "strength() scores 0-4 from length and variety")
    b = _item(2, "Create CLI entry point", "reads argv or stdin and prints the score with reasons")
    assert lint_backlog([a, b]) == []


# --- R4: existence-only acceptance (scaffolding items) ---


def test_r4_fires_on_the_live_scaffolding_items() -> None:
    # The two live items from the #54 validation drive: a package marker and its
    # recuration-spawned sibling — mere existence/importability, no behaviour, so the
    # independent oracle can never vouch and the sweep can only defer them.
    for acceptance in (
        "The file exists and can be imported without error. "
        "Importing `password_checker` should succeed.",
        "Importing `password_checker` succeeds without error.",
    ):
        findings = lint_backlog([_item(9, "Create package marker", acceptance)])
        assert any(f.rule == "no_behaviour" for f in findings), acceptance


def test_r4_silent_on_behavioural_acceptance() -> None:
    acceptance = (
        "Calling strength('Password123!') yields a score of 3 and reasons that include "
        "substrings indicating length and variety."
    )
    assert lint_backlog([_item(10, "Implement strength", acceptance)]) == []


def test_r4_silent_when_any_sentence_is_behavioural() -> None:
    # One behavioural sentence suppresses the flag (precision over recall) — including
    # the live tests item: "passes all tests" is behavioural even though its second
    # sentence ("No failures or errors occur") reads existence-only.
    for acceptance in (
        "The module exists. strength('x') returns a score between 0 and 4.",
        "Running `python -m unittest discover` passes all tests. No failures or errors occur.",
    ):
        findings = lint_backlog([_item(11, "Mixed item", acceptance)])
        assert not any(f.rule == "no_behaviour" for f in findings), acceptance


# --- scope + instruction rendering ---


def test_lints_only_todo_items() -> None:
    settled = _item(7, "Done thing", "returns `(1, ['x'])`", status="in_review")
    assert lint_backlog([settled]) == []


def test_curate_instruction_renders_findings_and_bounds_scope() -> None:
    findings = [SpecFinding(1, "exact_value", "item #1 pins exact literal values (...)")]
    text = curate_instruction(findings)
    assert "item #1" in text and "propose nothing else" in text
    assert curate_instruction([]) == ""


# ── DECIDABILITY: does the brief determine ONE answer? ───────────────────────
#
# `checkability` measures BINDABILITY — can a checker be attached to this sentence.
# It cannot see the failure that has now cost us three times: a claim that binds and
# still leaves its value unstated. Measured before this test was written:
#
#     greenfield  -> PARTIALLY_CHECKABLE   (5 material claims, 1 bound)
#     brownfield  -> PARTIALLY_CHECKABLE   (4 material claims, 2 bound)
#
# Same verdict for the brief that produced correct code in zero fix iterations and the
# one that produced two DIFFERENT invented scoring models across two runs. The dangerous
# cell is undecidable-but-BOUND: greenfield's "prints a score 0-4" bound to an
# acceptance_test, and 48 tests then passed over a model nobody specified.
#
# The assertions below are a PRE-REGISTERED PREDICTION, written before the detector
# existed so it could not be tuned to pass them.

_CASES = Path(__file__).resolve().parents[1] / "mosaera_core" / "bench" / "cases"
_DEMOS = Path(__file__).resolve().parents[3] / "demos"

# The two cases that are 100% of the suite's false_ship. Their briefs say "a short
# orchestrator (a handful of statements)" and their graders assert <=6 and <=7 — no
# reader, human or machine, could derive both numbers from that sentence.
_MUST_FLAG = {"MCB-05", "MCB-15"}

# MCB-02 says "a sentence or two of real content" — genuinely vague, and arguably SHOULD
# flag. Allowed, not required. A FOURTH case firing means the detector is too broad.
_MAY_FLAG = {"MCB-02"}


def _brief(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _is_undecidable(acceptance: str) -> bool:
    from mosaera_core.spec_lint import decidability

    return decidability([{"id": 1, "status": "todo", "acceptance": acceptance}]).get(1) == (
        "UNDECIDABLE"
    )


def test_the_demo_briefs_are_separated() -> None:
    """The evidence case: same verdict from `checkability`, opposite outcomes in practice."""
    assert _is_undecidable(_brief(_DEMOS / "greenfield" / "BRIEF.md")), (
        "greenfield names an output scale ('score 0-4') with no composition rule and produced "
        "two different scoring models across two runs — it must read UNDECIDABLE"
    )
    assert not _is_undecidable(_brief(_DEMOS / "brownfield" / "BRIEF.md")), (
        "brownfield states a rule that determines the answer (raise ValueError when removing "
        "more than stock; keep existing behaviour unchanged) — it must read DECIDABLE"
    )


def test_the_false_ship_cases_are_flagged_and_the_corpus_is_not() -> None:
    """The pre-registered corpus prediction, scored over all 24 MCB briefs."""
    flagged = {
        d.name
        for d in sorted(_CASES.glob("MCB-*"))
        if (d / "brief.md").is_file() and _is_undecidable(_brief(d / "brief.md"))
    }
    assert _MUST_FLAG <= flagged, f"missed the two-rulers cases: {_MUST_FLAG - flagged}"
    extra = flagged - _MUST_FLAG - _MAY_FLAG
    assert not extra, (
        f"detector too broad — flagged {sorted(extra)} beyond the predicted set. Narrow the "
        "patterns rather than widening the prediction."
    )


def test_an_explicit_mapping_is_decidable() -> None:
    """MCB-13 enumerates `score >= 90 -> 'A'` … a rule, not a shape. Must not flag."""
    assert not _is_undecidable(_brief(_CASES / "MCB-13" / "brief.md"))


def test_a_quantified_shape_claim_is_decidable() -> None:
    # "at least three helper functions" is countable; "a handful of statements" is not.
    assert not _is_undecidable("The function delegates to at least three helper functions.")
    assert _is_undecidable(
        "The function should read as a short orchestrator, a handful of statements."
    )


# --- the backfill: work authored before these checks existed ---------------------------


def test_settled_work_is_invisible_to_the_intake_verdicts() -> None:
    """The premise of the backfill, pinned so it can't drift.

    checkability/decidability judge `todo` items only — settled work isn't re-judged mid-run.
    That is correct for the run path and is precisely why items authored before these checks
    existed have never been looked at by them.
    """
    settled = [{"id": 1, "status": "done", "acceptance": "prints a strength score 0-4"}]
    assert checkability(settled) == {}
    assert decidability(settled) == {}
    assert decidability_findings(settled) == []


def test_the_diagnosis_reaches_settled_work_without_widening_the_filter() -> None:
    item = {"id": 1, "status": "done", "acceptance": "prints a strength score 0-4"}
    d = diagnose_item(item)
    assert d.status == "done"  # the real status is reported, never rewritten
    assert d.checkability == "CHECKABLE"
    assert d.decidability == "UNDECIDABLE"
    assert not d.compliant
    assert d.reasons == ["the text names a value it never states a rule for"]
    # And the status-blind entry point did not leak back into the run-path verdicts.
    assert checkability([item]) == {}


def test_a_clean_item_is_compliant_with_no_reasons() -> None:
    d = diagnose_item(
        {
            "id": 7,
            "status": "in_review",
            "acceptance": "raises ValueError when the quantity exceeds the stock on hand",
        }
    )
    assert d.compliant
    assert d.reasons == []


def test_both_axes_can_fail_at_once_and_both_are_named() -> None:
    # Empty acceptance: nothing binds. The reasons list is the operator's whole explanation,
    # so an item failing two ways must say two things rather than the first one found.
    d = diagnose_item({"id": 2, "status": "todo", "acceptance": ""})
    assert not d.compliant
    assert "no material acceptance claim binds to any oracle" in d.reasons

    # Failing both axes at once: nothing binds AND the magnitude doesn't resolve. The reasons
    # list is the operator's whole explanation, so it must say both rather than the first found.
    both = diagnose_item(
        {"id": 3, "status": "done", "acceptance": "The summary should be a handful of paragraphs."}
    )
    assert not both.compliant
    assert both.checkability == "UNDER_SPECIFIED"
    assert both.decidability == "UNDECIDABLE"
    assert len(both.reasons) == 2


def test_a_partially_checkable_brief_is_not_a_failure() -> None:
    """Calibration, found by driving the check rather than reading it.

    The first rule was CHECKABLE ∧ DECIDABLE. Under it, the brownfield demo brief — the one
    that produced correct code in ZERO fix iterations, our exemplar of a good brief — came back
    non-compliant, because it is PARTIALLY_CHECKABLE like essentially every real brief. A marker
    that fires on the best input we own is a marker operators learn to ignore.

    Non-compliance is now the two states the engine actually treats as broken: nothing binds at
    all (parks a run today) or the text doesn't fix its answer (ships invented evidence).
    """
    brownfield = Path("demos/brownfield/BRIEF.md")
    if brownfield.is_file():  # the demo dirs aren't shipped in every checkout
        good = diagnose_item({"id": 1, "status": "todo", "acceptance": brownfield.read_text()})
        assert good.checkability == "PARTIALLY_CHECKABLE"
        assert good.compliant, "the known-good brief must not be flagged"

    partial = diagnose_item(
        {
            "id": 4,
            "status": "todo",
            "acceptance": "prints every matching note.\nThe module handles unicode correctly.",
        }
    )
    assert partial.checkability == "PARTIALLY_CHECKABLE"
    assert partial.compliant  # visible on the checkability axis, not a flag
    assert partial.reasons == []


def test_the_diagnosis_covers_every_item_whatever_its_status() -> None:
    items = [
        {"id": i, "status": s, "acceptance": "prints a strength score 0-4"}
        for i, s in enumerate(["todo", "in_progress", "in_review", "done", "deferred"], start=1)
    ]
    rows = diagnose_backlog(items)
    assert len(rows) == len(items)  # no status is silently dropped
    assert all(not r.compliant for r in rows)
    assert [r.status for r in rows] == ["todo", "in_progress", "in_review", "done", "deferred"]


def test_a_rule_one_sentence_later_still_fixes_the_value() -> None:
    """Found by using the check, not by reading it.

    A brief repaired EXACTLY as this check's own finding instructed — "state the rule that fixes
    the value" — still scored UNDECIDABLE, because the rule landed in the next sentence and the
    scope was the claim. Report-only that is one false flag; gating anything, it blocks a
    correctly-written brief, which is the fastest way to lose an operator's trust in a check.
    """
    bullet = (
        "- prints a strength score 0-4 plus reasons. The score is the number of these four "
        "rules the password satisfies: it is at least 12 characters long; it contains both "
        "cases; it contains a digit; it contains a symbol."
    )
    assert not undecidable_reason("prints a strength score 0-4 plus reasons.", bullet)
    # …and the scope is the BLOCK, not the whole document: a rule in a different bullet is
    # about a different claim and must not quieten this one.
    other_bullet = (
        "- prints a strength score 0-4 plus reasons.\n"
        "- a reusable `strength(password) -> (score, reasons)` function the CLI calls."
    )
    assert undecidable_reason("prints a strength score 0-4 plus reasons.", other_bullet)


def test_vague_magnitude_stays_clause_scoped() -> None:
    # The block widening applies to the output-scale pattern ONLY. A countable elsewhere in the
    # bullet does not fix "a handful" — it just sits next to it, which is the MCB-05 shape and
    # the two-rulers defect this whole check exists for.
    block = (
        "- `checkout_total` should read as a short orchestrator (a handful of statements) "
        "that delegates to at least three helper functions."
    )
    assert undecidable_reason(
        "`checkout_total` should read as a short orchestrator (a handful of statements) "
        "that delegates to at least three helper functions.",
        block,
    )
