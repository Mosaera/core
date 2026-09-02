"""Regression compare + average — pure, offline."""

from __future__ import annotations

from typing import Any

import pytest
from mosaera_core.bench.compare import average, compare, load_baseline, write_baseline
from mosaera_core.bench.scorecard import Dimension, Scorecard


def card(
    overall: int,
    dims: dict[str, int | None],
    cost: dict[str, Any],
    outcome: str | None = None,
) -> Scorecard:
    return Scorecard(
        case_id="MCB-01",
        overall=overall,
        dimensions=[Dimension(n, s, "") for n, s in dims.items()],
        cost=cost,
        meta={"outcome": outcome} if outcome is not None else {},
    )


def test_average_means_scores_and_cost_and_keeps_na() -> None:
    a = card(80, {"Implementation": 100, "Testing": None}, {"total_tokens": 1000, "usd": 0.0})
    b = card(60, {"Implementation": 50, "Testing": None}, {"total_tokens": 3000, "usd": 0.0})
    avg = average([a, b])
    assert avg.overall == 70
    scores = {d.name: d.score for d in avg.dimensions}
    assert scores["Implementation"] == 75
    assert scores["Testing"] is None  # N/A stays N/A
    assert avg.cost["total_tokens"] == 2000
    assert avg.meta["runs"] == 2


def test_average_single_run_is_identity() -> None:
    a = card(90, {"Implementation": 100}, {"total_tokens": 5})
    assert average([a]) is a


def test_average_aggregates_reliability_outcomes_across_repeats() -> None:
    # #43 scoreboard: the terminal buckets must survive averaging (the easy-to-miss seam), with the
    # WORST that occurred as the representative — a single false-ship among green runs is surfaced.
    cost = {"total_tokens": 1000, "usd": 0.0}
    runs = [
        card(80, {"Implementation": 90}, cost, outcome="clean_deliver"),
        card(70, {"Implementation": 80}, cost, outcome="clean_deliver"),
        card(0, {"Implementation": 0}, cost, outcome="false_ship"),
    ]
    avg = average(runs)
    assert avg.meta["outcomes"] == {
        "clean_deliver": 2,
        "honest_park": 0,
        "thrash_park": 0,
        "false_ship": 1,
        "crash": 0,
    }
    assert avg.meta["outcome"] == "false_ship"  # worst-of-repeats representative


def test_compare_no_regression_within_tolerance() -> None:
    baseline = card(90, {"Implementation": 100}, {"usd": 0.0, "total_tokens": 1000}).to_dict()
    fresh = card(87, {"Implementation": 96}, {"usd": 0.0, "total_tokens": 1100})  # small drops
    result = compare(fresh, baseline)
    assert not result.regressed


def test_compare_flags_overall_and_dimension_regression() -> None:
    baseline = card(90, {"Implementation": 100}, {}).to_dict()
    fresh = card(70, {"Implementation": 60}, {})  # both drop well beyond tolerance
    result = compare(fresh, baseline)
    assert result.regressed
    assert any("overall" in r for r in result.regressions)
    assert any("Implementation" in r for r in result.regressions)


def test_compare_flags_cost_regression() -> None:
    baseline = card(90, {}, {"total_tokens": 1000, "usd": 0.0}).to_dict()
    fresh = card(90, {}, {"total_tokens": 2000, "usd": 0.0})  # +100% tokens
    result = compare(fresh, baseline)
    assert result.regressed and any("total_tokens" in r for r in result.regressions)


def test_compare_skips_na_dimensions() -> None:
    baseline = card(90, {"Testing": None}, {}).to_dict()
    fresh = card(90, {"Testing": None}, {})
    assert not compare(fresh, baseline).regressed


def test_compare_reports_improvement_as_a_note_not_a_regression() -> None:
    baseline = card(70, {"Implementation": 60}, {}).to_dict()
    fresh = card(90, {"Implementation": 100}, {})
    result = compare(fresh, baseline)
    assert not result.regressed and any("improved" in n for n in result.notes)


def test_baseline_write_and_load_roundtrip(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    import mosaera_core.bench.compare as cmp

    monkeypatch.setattr(cmp, "_BASELINE_DIR", tmp_path / "baselines")
    c = card(88, {"Implementation": 100, "Testing": None}, {"usd": 0.0, "total_tokens": 42})
    write_baseline(c)
    loaded = load_baseline("MCB-01")
    assert loaded is not None and loaded["overall"] == 88
    assert load_baseline("MCB-99") is None  # missing baseline → None


def _reasons_card(reasons: list[str]) -> Scorecard:
    return Scorecard(
        case_id="MCB-01",
        overall=50,
        dimensions=[Dimension("Implementation", 50, "")],
        cost={"total_tokens": 1, "usd": 0.0, "calls": 1},
        meta={"gate_reasons": reasons},
    )


def test_average_aggregates_park_reasons_across_repeats() -> None:
    """ADR-0078: the WHY must survive averaging, like `outcomes` already does.

    `--compare` / `--update-baseline` default to repeat=3, so the AVERAGED card is the one that
    gets written — and it previously dropped `gate_reasons` entirely, discarding the newly
    captured evidence one layer above where it was captured.
    """
    cards = [
        _reasons_card(["validation_failed", "oracle_unverified"]),
        _reasons_card(["validation_failed"]),
        _reasons_card([]),  # a delivered run contributes nothing
    ]
    assert average(cards).meta["park_reasons"] == {
        "validation_failed": 2,
        "oracle_unverified": 1,
    }


def test_average_park_reasons_is_empty_when_nothing_was_blocked() -> None:
    assert average([_reasons_card([]), _reasons_card([])]).meta["park_reasons"] == {}


def test_average_carries_per_repeat_fingerprints() -> None:
    """ADR-0081: fingerprints survive averaging as a LIST (never averaged — liveness compares
    them pairwise across A/B arms); a pre-capture repeat contributes None, not a gap."""
    fp = {"schema": 1, "nodes": [["plan", ["plan"]]], "interrupts": [], "terminal": "delivered"}
    cost = {"total_tokens": 1, "usd": 0.0, "calls": 1}
    with_fp = Scorecard(
        "MCB-01", 50, [Dimension("Implementation", 50, "")], cost, meta={"fingerprint": fp}
    )
    without = Scorecard("MCB-01", 50, [Dimension("Implementation", 50, "")], cost, meta={})
    assert average([with_fp, without]).meta["fingerprints"] == [fp, None]
