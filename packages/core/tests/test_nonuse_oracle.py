"""SUBTRACT, end to end — the non-use oracle and the removal claim (verb-arc slice 1).

**The deadlock, reproduced before anything was built** (measured on `4bcaa77`): every removal
phrasing classified `("none", True)` — a MATERIAL claim with NO oracle, unsatisfiable by
construction, so the item could never deliver. Meanwhile `delete_file` is admin-opt-in and off, so
the coder could not do the work either. Re-scope loop to the iteration cap, and a park that never
said why.

    classify_sentence("Remove the deprecated `legacy_export` function.")  ->  ('none', True)
    classify_sentence("Delete the unused `helpers/oldmath.py` module.")   ->  ('none', True)
    classify_sentence("Drop the `--legacy` CLI flag.")                    ->  ('none', True)

A removal has no behavioural signature: the *absence* of code cannot be exercised by a test, and a
green suite proves only that what remains still works. The oracle has to be structural, and the
proof obligation is "nothing references it".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mosaera_core.claim_oracles import evaluate_claims, failed_claim_classes
from mosaera_core.claims import CLAIM_EVIDENCE_CLASS, ORACLE_KINDS, classify_sentence
from mosaera_core.nonuse import non_use_proven, removal_target


class _WS:
    def __init__(self, root: Path) -> None:
        self.root = root


def _tree(tmp: Path, **files: str) -> Path:
    for name, body in files.items():
        p = tmp / name.replace("__", "/")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp


# --- 1.1 the claim ------------------------------------------------------------------------------


def test_a_removal_sentence_now_binds_an_oracle() -> None:
    """THE regression. Each of these returned `('none', True)` before the slice."""
    for sentence in (
        "Remove the deprecated `legacy_export` function.",
        "Delete the unused `helpers/oldmath.py` module.",
        "- Drop the `--legacy` CLI flag.",
        "The `legacy_export` helper should be removed entirely.",
    ):
        kind, material = classify_sentence(sentence)
        assert (kind, material) == ("non_use", True), f"{sentence!r} -> {kind!r}"


def test_the_pattern_does_not_over_match_any_real_brief() -> None:
    """The dangerous direction, measured against all 27 shipped cases.

    Under-matching is safe: it falls back to the old behaviour, which parks. OVER-matching turns
    ordinary items into unproven removals that cannot ship. A bare verb search produced FIVE false
    positives here — `delete` naming a CLI verb (MCB-01/23), a dict method (MCB-10) and a payload
    action (MCB-18), all features being BUILT rather than code being removed.
    """
    from mosaera_core.claims import claims_from_acceptance

    cases = Path(__file__).resolve().parents[1] / "mosaera_core" / "bench" / "cases"
    offenders = []
    subtract_claims = 0
    for brief in sorted(cases.glob("*/brief.md")):
        for c in claims_from_acceptance(None, brief.read_text(encoding="utf-8")):
            if c.oracle_kind != "non_use":
                continue
            if brief.parent.name == "MCB-27":
                subtract_claims += 1  # the subtract case — a removal claim here is the POINT
            else:
                offenders.append((brief.parent.name, c.text[:70]))
    assert not offenders, f"the removal pattern over-matches real briefs: {offenders}"
    # The positive half: a pattern that matched nothing anywhere would also pass the line above.
    assert subtract_claims >= 1, "MCB-27 is the subtract case and mints no removal claim"


def test_removal_loses_to_tests_unmodified_and_transformation() -> None:
    """Ordering is load-bearing and already documented in `classify_sentence`: tests-unmodified
    sentences carry "delete/skip" verbs, and "extract X into Y" is a reshape, not a removal."""
    assert classify_sentence("Do not delete or modify the existing tests.")[0] == "tests_unmodified"
    assert classify_sentence("Extract the shared helper into a module-level helper.")[0] == (
        "ast_transformation_contract"
    )


def test_the_evidence_class_partition_stays_total() -> None:
    """`non_use` is its own class, NOT `structural` — and the reason is a real hole, not taste.

    `claim_structural_failed` is the bucket ADR-0094 widened for Layer-2 eligibility. An unproven
    removal landing there would become auto-ship-eligible, and Layer 2 verifies by authoring a
    BEHAVIOURAL test and mutating it — which says nothing about whether the removed thing is still
    referenced. It could convert a removal that breaks every caller.
    """
    assert "non_use" in ORACLE_KINDS
    assert CLAIM_EVIDENCE_CLASS["non_use"] == "removal"
    assert CLAIM_EVIDENCE_CLASS["non_use"] != CLAIM_EVIDENCE_CLASS["ast_transformation_contract"]
    covered = set(CLAIM_EVIDENCE_CLASS) | {"none"}
    assert covered == set(ORACLE_KINDS), f"partition is not total: {set(ORACLE_KINDS) - covered}"


# --- 1.2 the oracle -----------------------------------------------------------------------------


def test_proven_when_nothing_references_it(tmp_path: Path) -> None:
    root = _tree(tmp_path, **{"app.py": "def keep():\n    return 1\n"})
    proven, why = non_use_proven(root, "legacy_export")
    assert proven is True
    assert "referenced nowhere" in why


def test_refused_when_a_caller_survives(tmp_path: Path) -> None:
    """The failure this whole slice exists to prevent: a removal that breaks a live caller."""
    root = _tree(
        tmp_path,
        **{"app.py": "def keep():\n    return legacy_export()\n", "other.py": "x = 1\n"},
    )
    proven, why = non_use_proven(root, "legacy_export")
    assert proven is False
    assert "app.py" in why


def test_a_surviving_definition_also_refuses(tmp_path: Path) -> None:
    """ "Still defined" answers the same question as "still called": it was not removed."""
    root = _tree(tmp_path, **{"legacy.py": "def legacy_export():\n    return 1\n"})
    assert non_use_proven(root, "legacy_export")[0] is False


def test_imports_count_as_references(tmp_path: Path) -> None:
    for body in (
        "from legacy import legacy_export\n",
        "import legacy_export\n",
        "from legacy import legacy_export as le\n",
    ):
        root = _tree(tmp_path / body[:12].replace(" ", "_"), **{"app.py": body})
        assert non_use_proven(root, "legacy_export")[0] is False, body


def test_a_dotted_target_is_matched_by_its_last_segment(tmp_path: Path) -> None:
    """`from pkg.mod import helper` binds the bare name — searching the full path would miss it."""
    root = _tree(tmp_path, **{"app.py": "from pkg.mod import helper\nhelper()\n"})
    assert non_use_proven(root, "pkg.mod.helper")[0] is False


def test_unparseable_source_is_None_not_proven(tmp_path: Path) -> None:
    """Deny-by-default: a file we could not read might hold the one live caller. "We did not look"
    is never "it is not there" — the rule ADR-0076 applies to security evidence."""
    root = _tree(tmp_path, **{"broken.py": "def (((\n"})
    proven, why = non_use_proven(root, "legacy_export")
    assert proven is None
    assert "could not parse" in why


def test_no_target_and_no_tree_are_None(tmp_path: Path) -> None:
    assert non_use_proven(tmp_path, "")[0] is None
    assert non_use_proven(tmp_path / "missing", "x")[0] is None
    assert non_use_proven(_tree(tmp_path, **{"README.md": "hi"}), "x")[0] is None


def test_the_agent_scratch_space_is_not_a_caller(tmp_path: Path) -> None:
    """A reference inside `.mosaera` (ADR-0064 scratch) is not a live caller."""
    root = _tree(tmp_path, **{"app.py": "x = 1\n", ".mosaera__scratch.py": "legacy_export()\n"})
    assert non_use_proven(root, "legacy_export")[0] is True


def test_a_dynamic_reference_is_not_vouched_for(tmp_path: Path) -> None:
    """RED TEAM R3, confirmed and fixed. `getattr(mod, "legacy_export")` names its target as a
    STRING, so the AST pass saw no Name, no Attribute and no import — and vouched for a removal a
    live caller still used.

    A false vouch is the ONLY unsafe direction this oracle has. Every other error makes it refuse a
    fine removal (waste); this one ships breakage.
    """
    root = _tree(tmp_path, **{"d.py": 'import m\nfn = getattr(m, "legacy_export")\nfn()\n'})
    proven, why = non_use_proven(root, "legacy_export")
    assert proven is not True, "vouched for a removal a dynamic caller still uses"
    assert "dynamic reference" in why


def test_prose_mentioning_the_symbol_still_vouches(tmp_path: Path) -> None:
    """The other half of R3's fix: EXACT string match, not substring.

    Treating a docstring that happens to mention the name as a caller would make the oracle refuse
    almost every real removal — conservative to the point of useless is its own failure mode.
    """
    root = _tree(tmp_path, **{"s.py": 'msg = "call legacy_export() someday"\n'})
    assert non_use_proven(root, "legacy_export")[0] is True


def test_removal_target_reads_the_code_span() -> None:
    assert removal_target("Remove the deprecated `legacy_export` function.") == "legacy_export"
    assert removal_target("Remove the deprecated function.") == ""


# --- deny-by-default: unprovable must BLOCK, which differs from every other kind -----------------


def _claim(text: str) -> list[dict[str, Any]]:
    return [{"id": "c1", "oracle_kind": "non_use", "text": text, "material": True}]


def test_unprovable_removal_is_FAILED_not_unevaluable(tmp_path: Path) -> None:
    """The design decision, pinned.

    Every other kind resolves an unaskable question to `unevaluable`, which the gate deliberately
    ignores. That is right for a claim about behaviour — absent evidence is not an objection. It is
    WRONG for a claim of absence: the slice's requirement is *removal without a non-use proof
    cannot ship*, and `unevaluable` would let exactly that through.
    """
    rows = evaluate_claims(
        _claim("Remove the deprecated `legacy_export` helper."),
        _WS(_tree(tmp_path, **{"broken.py": "def (((\n"})),
        {},
    )
    assert rows[0]["verdict"] == "failed"
    assert "could not prove non-use" in rows[0]["oracle_ref"]


def test_a_claim_naming_no_symbol_fails_rather_than_passing(tmp_path: Path) -> None:
    rows = evaluate_claims(_claim("Remove the deprecated helper."), _WS(tmp_path), {})
    assert rows[0]["verdict"] == "failed"
    assert "names no removable symbol" in rows[0]["oracle_ref"]


def test_a_proven_removal_is_satisfied(tmp_path: Path) -> None:
    rows = evaluate_claims(
        _claim("Remove the deprecated `legacy_export` helper."),
        _WS(_tree(tmp_path, **{"app.py": "def keep():\n    return 1\n"})),
        {},
    )
    assert rows[0]["verdict"] == "satisfied"


def test_the_two_failing_causes_stay_distinguishable(tmp_path: Path) -> None:
    """Both fail, but the RECORD says which — collapsing causes into one unexplained verdict is
    the F83 defect, and it cost two hours the first time."""
    still_used = evaluate_claims(
        _claim("Remove the deprecated `legacy_export` helper."),
        _WS(_tree(tmp_path / "a", **{"app.py": "legacy_export()\n"})),
        {},
    )[0]["oracle_ref"]
    unprovable = evaluate_claims(
        _claim("Remove the deprecated `legacy_export` helper."),
        _WS(_tree(tmp_path / "b", **{"broken.py": "def (((\n"})),
        {},
    )[0]["oracle_ref"]
    assert "still referenced" in still_used
    assert "could not prove" in unprovable
    assert still_used != unprovable


def test_a_failed_removal_claim_reaches_the_gate_as_the_removal_class(tmp_path: Path) -> None:
    claims = _claim("Remove the deprecated `legacy_export` helper.")
    rows = evaluate_claims(claims, _WS(_tree(tmp_path, **{"app.py": "legacy_export()\n"})), {})
    assert failed_claim_classes(rows, claims) == ["removal"]


# --- The MCB-27 over-park: a test that PROVES the removal was counted as a live caller ----------
#
# Measured 2026-08-10 on the 52-run integration sweep: MCB-27 parked 2/2 with `over_park: True`,
# the hidden grader PASSING, and `unsatisfied_claim_kinds == {'non_use': 2}`. The oracle refused a
# removal that was correct and complete. Cause: `from pkg import gone` inside a
# `pytest.raises(ImportError)` block is an `ast.ImportFrom` like any other, and `_SKIP_DIRS` never
# excluded `tests/`. This slice's own hidden grader makes that exact assertion
# (`test_it_is_no_longer_importable`) — so the oracle would have refused its own proof.


_ABSENCE_TEST = (
    "import pytest\n\n"
    "def test_it_is_gone() -> None:\n"
    "    with pytest.raises(ImportError):\n"
    "        from app import legacy_export\n"
)


def test_a_test_asserting_the_symbol_is_gone_does_not_refute_the_removal(tmp_path: Path) -> None:
    """THE REGRESSION. The natural way to test a deletion must not be the thing that blocks it."""
    root = _tree(
        tmp_path,
        **{"app.py": "def keep():\n    return 1\n", "tests__test_removed.py": _ABSENCE_TEST},
    )
    proven, evidence = non_use_proven(root, "legacy_export")
    assert proven is True, evidence


def test_the_test_side_mention_is_NAMED_not_silently_dropped(tmp_path: Path) -> None:
    """Ignoring a reference invisibly is the defect class this repo has measured four times: the
    verdict may discount the test, the RECORD may not omit it."""
    root = _tree(
        tmp_path,
        **{"app.py": "def keep():\n    return 1\n", "tests__test_removed.py": _ABSENCE_TEST},
    )
    _, evidence = non_use_proven(root, "legacy_export")
    assert "tests/test_removed.py" in evidence
    assert "the suite judges those" in evidence


def test_a_PRODUCTION_caller_still_refutes_the_removal(tmp_path: Path) -> None:
    """The direction that must not move: a real caller is still an objection."""
    root = _tree(
        tmp_path,
        **{"app.py": "legacy_export()\n", "tests__test_removed.py": _ABSENCE_TEST},
    )
    proven, evidence = non_use_proven(root, "legacy_export")
    assert proven is False
    assert "app.py" in evidence


def test_a_test_that_CALLS_the_symbol_is_left_to_the_suite(tmp_path: Path) -> None:
    """A test that genuinely exercises the removed symbol goes RED, and `validation_failed` parks
    the run — a separate, already-independent control. The non-use oracle does not double-judge it,
    but it does say it saw it."""
    root = _tree(
        tmp_path,
        **{
            "app.py": "def keep():\n    return 1\n",
            "tests__test_legacy.py": "from app import legacy_export\n\n"
            "def test_it() -> None:\n    assert legacy_export(['a']) == 'a'\n",
        },
    )
    proven, evidence = non_use_proven(root, "legacy_export")
    assert proven is True
    assert "tests/test_legacy.py" in evidence


def test_a_tree_of_only_tests_proves_nothing(tmp_path: Path) -> None:
    """Green-by-vacancy guard: 'zero production callers' and 'zero production files examined' are
    the same sentence with opposite meanings."""
    root = _tree(tmp_path, **{"tests__test_removed.py": _ABSENCE_TEST})
    proven, evidence = non_use_proven(root, "legacy_export")
    assert proven is None
    assert "no production sources" in evidence


def test_a_dynamic_mention_in_a_test_does_not_block_either(tmp_path: Path) -> None:
    """R3's string-literal guard is a PRODUCTION guard: `getattr(m, "legacy_export")` in a test is
    the test naming what it expects to be absent, not a caller we failed to see."""
    root = _tree(
        tmp_path,
        **{
            "app.py": "def keep():\n    return 1\n",
            "tests__test_dyn.py": (
                'def test_it() -> None:\n    assert "legacy_export" not in dir()\n'
            ),
        },
    )
    proven, _ = non_use_proven(root, "legacy_export")
    assert proven is True
