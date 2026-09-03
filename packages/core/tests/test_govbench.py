"""The governance suite's deterministic arm — a standing gate in `make test`.

It runs here rather than opt-in for one reason: a control nobody runs is a control that can rot.
That is not a hypothesis — a standing decision was inert in the product for its entire life, unit
tests green throughout, because the only instrument that could have seen it was opt-in and nobody
opted in.

No model, no Docker, no database. Seconds.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from mosaera_core.govbench.cases import CLASSES, available_gov_cases, load_gov_case
from mosaera_core.govbench.harness import run_gov_case
from mosaera_core.govbench.score import broken_cases, score_governance


def _sweep() -> tuple[list, list]:
    cases = [load_gov_case(c) for c in available_gov_cases()]
    return cases, [run_gov_case(c) for c in cases]


def test_every_case_produces_the_verdict_it_declared() -> None:
    """The pre-registration, enforced. A case whose verdict disagrees with its declaration is a
    BROKEN CASE, not a finding — reporting it as a low score would launder a fixture bug into a
    claim about the system. This caught two of my own on the suite's first run."""
    cases, runs = _sweep()
    broken = broken_cases(cases, runs)
    assert not broken, f"fixture bug, not a measurement: {broken}"


def test_the_ask_is_scored_on_precision_and_recall() -> None:
    """A missed ask and a spurious ask are both failures.

    An instrument that counts asks scores a system that asks about everything as perfect — the
    fatigue hazard ADR-0080 names, and the same shape as MCB scoring "parked for a human" 30/100.
    """
    cases, runs = _sweep()
    dims = {d.name: d for d in score_governance(cases, runs)}
    assert dims["Asked"].score == 100, dims["Asked"].rationale
    assert "missed []" in dims["Asked"].rationale
    assert "spurious []" in dims["Asked"].rationale


def test_the_control_case_is_the_one_that_makes_asking_falsifiable() -> None:
    """Without a case that must stay SILENT, `asked` cannot fail in the over-asking direction."""
    cases, runs = _sweep()
    by_id = {r.case_id: r for r in runs}
    controls = [c for c in cases if c.case_class == "control"]
    assert controls, "the suite must contain a case whose correct behaviour is silence"
    for case in controls:
        assert not by_id[case.id].asked, f"{case.id}: asked about a fully decidable item"


def test_a_spurious_ask_would_be_caught() -> None:
    """Prove the instrument can FAIL, not just that it currently passes.

    A suite that has never been shown failing is indistinguishable from a suite that cannot fail.
    Here the control case is re-declared as one that should be asked about; the score must drop.
    """
    cases, runs = _sweep()
    control = next(c for c in cases if c.case_class == "control")
    flipped = [replace(c, expect_ask=True) if c.id == control.id else c for c in cases]
    dims = {d.name: d for d in score_governance(flipped, runs)}
    assert (dims["Asked"].score or 0) < 100
    assert control.id in dims["Asked"].rationale


def test_every_case_is_REACHABLE_and_a_drift_would_be_caught() -> None:
    """ADR-0089's axis, and the reason it is asserted rather than merely declared.

    `expect_reachability` shipped on 2026-08-07 with NOTHING reading it: `broken_cases` compared
    only checkability and decidability, and `GovRun` did not even carry the observation. A declared
    expectation with no observation is not a measurement — F74's shape (`hygiene_unavailable`:
    declared, populated, read by nobody), committed the same day that one was fixed.

    Two halves, because either alone is worthless. G-01..G-05 are REAL acceptance text, so all
    judging REACHABLE is the precision evidence ADR-0089 claims. And flipping one declaration must
    BREAK the sweep — a field that cannot fail is the defect this test exists to prevent.
    """
    cases, runs = _sweep()
    assert {r.reachability for r in runs} == {"REACHABLE"}, [
        (r.case_id, r.reachability) for r in runs
    ]

    flipped = [replace(c, expect_reachability="UNREACHABLE") for c in cases[:1]] + list(cases[1:])
    broken = broken_cases(flipped, runs)
    assert [b.case_id for b in broken] == [cases[0].id]
    assert "reachability" in broken[0].expected
    with pytest.raises(ValueError, match="broken cases"):
        score_governance(flipped, runs)


def test_a_ratified_decision_stops_the_question_recurring() -> None:
    """The clause tier's entire promise, checked end to end for the first time."""
    cases, runs = _sweep()
    by_id = {r.case_id: r for r in runs}
    settleable = [c for c in cases if c.case_class == "clause-settleable"]
    assert settleable, "the suite must contain a case a standing decision can settle"
    for case in settleable:
        run = by_id[case.id]
        assert run.asked, f"{case.id}: should ask the FIRST time"
        assert run.asked_again is False, f"{case.id}: asked again after the decision was ratified"


def test_governance_dimensions_cannot_reach_mcb_overall() -> None:
    """MCB stays frozen and comparable — a floor you keep editing is not a floor.

    Asserted structurally rather than by mutating a card: `score()` computes `overall` at
    construction from the `capability` bucket alone, so appending dimensions afterwards proves
    nothing. The real guarantee is that governance names are not weighted — and that a governance
    dimension mistakenly filed as `capability` would raise a KeyError rather than silently move
    the headline.
    """
    from mosaera_core.bench.scorecard import _CAPABILITY_WEIGHTS

    cases, runs = _sweep()
    for dim in score_governance(cases, runs):
        assert dim.bucket == "governance"
        assert dim.name not in _CAPABILITY_WEIGHTS, (
            f"{dim.name} is weighted into MCB's overall — the two suites must not share a headline"
        )


def test_mcb_is_untouched_by_this_suite() -> None:
    """The governance cases must not appear in MCB's registry, or the frozen suite silently grew."""
    from mosaera_core.bench.cases import available_cases

    mcb = available_cases()
    # 24 -> 25 -> 26 on 2026-08-09: MCB-27 (subtract, ADR-0095) and MCB-28 (modify, ADR-0097) are
    # the corpus's first removal and behaviour-change cases, each added because its slice was
    # unmeasurable without one — MCB otherwise covers greenfield/bug-fix/feature/refactor/
    # robustness, all ADD-shaped. The tripwire guards against the
    # governance suite LEAKING in, which the assertion below is what actually checks — the count is
    # the coarse half and moves with a reviewed diff.
    #
    # 26 -> 30 on 2026-08-29 (ADR-0124): MCB-30/31/32/33 are the corpus's first NON-BEHAVIOURAL
    # cases — a comment, two docstring rewords and a version bump. Added because 0 of the previous
    # 26 armed the trivial-lane classifier, which made an A/B over the corpus null by construction:
    # every existing case changes behaviour, because the corpus was built to measure CAPABILITY.
    # MCB-31 is deliberately one the classifier DECLINES, as the lane's do-nothing control.
    assert len(mcb) == 30, f"MCB's case count moved: {len(mcb)}"
    assert not [c for c in mcb if c.startswith("G-")]


def test_the_case_contract_refuses_a_typo() -> None:
    """`bench`'s case loader silently drops an unknown key. In a suite whose entire job is
    expectations, a typo'd expectation that quietly does nothing is worse than a crash."""
    import tomllib
    from pathlib import Path

    from mosaera_core.govbench import cases as mod

    for case_id in available_gov_cases():
        raw = tomllib.loads((Path(mod._CASES_DIR) / case_id / "case.toml").read_text())
        assert raw["case_class"] in CLASSES
        assert set(raw) <= mod._CASE_KEYS


def test_loading_an_unknown_case_is_an_error() -> None:
    with pytest.raises(ValueError, match="unknown governance case"):
        load_gov_case("G-99")


# --- the CLI: the sweep now leaves a record (2026-08-07 audit) ---------------------------------
#
# The sweep already ran on every `make test`, and persisted NOTHING — no scorecard, no history, no
# engine stamp. Governance had no trend while MCB had one, which is a quieter version of the
# asymmetry ADR-0083 exists to close.


def test_the_cli_sweeps_and_writes_a_stamped_scorecard(tmp_path, monkeypatch) -> None:
    import json as _json

    from mosaera_core.govbench import cli as gov_cli

    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    assert gov_cli.main(["--no-write"]) == 0  # prints, persists nothing
    assert not (tmp_path / "benchmarks").exists()

    assert gov_cli.main([]) == 0
    card_dir = tmp_path / "benchmarks" / "_govbench"
    cards = sorted(card_dir.glob("*.json"))
    assert len(cards) == 1
    card = _json.loads(cards[0].read_text())
    assert {d["name"] for d in card["dimensions"]} >= {"Detected", "Asked"}
    assert all(d["bucket"] == "governance" for d in card["dimensions"])
    assert card["meta"]["engine_version"]  # attributable, per ADR-0055's argument for the MCB trend

    row = _json.loads((card_dir / "history.jsonl").read_text().splitlines()[-1])
    assert row["dimensions"]["Asked"] == 100
    assert row["engine_version"] == card["meta"]["engine_version"]


def test_the_cli_REFUSES_to_score_over_a_broken_fixture(monkeypatch) -> None:
    """The posture `score_governance` already takes internally, surfaced at the command line: a
    drifted fixture exits non-zero WITHOUT a score, so a sweep can never be published over one."""
    from mosaera_core.govbench import cases as gov_cases
    from mosaera_core.govbench import cli as gov_cli

    real = gov_cases.load_gov_case

    def _drifted(case_id: str):
        case = real(case_id)
        return replace(case, expect_reachability="UNREACHABLE")

    monkeypatch.setattr(gov_cli, "load_gov_case", _drifted)
    assert gov_cli.main(["--no-write"]) == 1


def test_a_governance_only_card_does_not_claim_a_CAPABILITY_score() -> None:
    """`overall` averages the capability bucket, and governance never reaches it — so a passing
    governance sweep has overall == 0 by construction. Printing "Capability 0/100" over three 100s
    reads as a failing score for a passing sweep."""
    import io
    from contextlib import redirect_stdout

    from mosaera_core.bench.report import print_summary
    from mosaera_core.govbench.cli import _card

    cases, runs = _sweep()
    buf = io.StringIO()
    with redirect_stdout(buf):
        print_summary(_card(runs, score_governance(cases, runs), "stamp"))
    out = buf.getvalue()
    assert "Capability" not in out
    assert "Governance" in out and "Asked" in out
