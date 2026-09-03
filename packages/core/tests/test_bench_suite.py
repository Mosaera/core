"""Suite rollup — pure aggregation of per-case scorecards (offline)."""

from __future__ import annotations

from mosaera_core.bench.scorecard import Dimension, Scorecard
from mosaera_core.bench.suite import build_suite, render_suite_md


def card(
    case_id: str,
    capability: str,
    tier: str,
    overall: int,
    delivered: bool,
    outcome: str | None = None,
    outcomes: dict[str, int] | None = None,
) -> Scorecard:
    meta: dict[str, object] = {"capability": capability, "tier": tier, "delivered": delivered}
    if outcome is not None:
        meta["outcome"] = outcome
    if outcomes is not None:
        meta["outcomes"] = outcomes
    return Scorecard(
        case_id=case_id,
        overall=overall,
        dimensions=[Dimension("Implementation", overall, "")],
        cost={"total_tokens": 1000, "usd": 0.0, "calls": 5},
        meta=meta,
    )


def _cards() -> list[Scorecard]:
    return [
        card("MCB-03", "bug-fix", "moderate", 80, True),
        card("MCB-04", "feature", "moderate", 60, True),
        card("MCB-05", "refactor", "hard", 40, False),
        card("MCB-06", "robustness", "moderate", 100, True),
    ]


def test_suite_headline_is_mean_of_case_overalls() -> None:
    report = build_suite(_cards())
    assert report.overall == 70  # mean(80, 60, 40, 100)
    assert report.total == 4
    assert report.delivered == 3


def test_by_capability_groups_and_counts() -> None:
    report = build_suite(_cards())
    assert report.by_capability["bug-fix"] == {"score": 80, "n": 1, "delivered": 1}
    assert report.by_capability["refactor"] == {"score": 40, "n": 1, "delivered": 0}


def test_matrix_places_cells_by_capability_and_tier() -> None:
    report = build_suite(_cards())
    assert report.matrix["bug-fix"]["moderate"] == 80
    # a bucket with no case is None, not zero
    assert report.matrix["bug-fix"].get("hard") is None
    assert report.matrix["refactor"]["hard"] == 40


def test_cost_is_summed_across_cases() -> None:
    report = build_suite(_cards())
    assert report.cost["total_tokens"] == 4000
    assert report.cost["calls"] == 20


def test_capabilities_render_in_taxonomy_order() -> None:
    report = build_suite(_cards())
    md = render_suite_md(report, "stamp-1")
    assert "Suite capability: 70 / 100" in md
    # bug-fix appears before feature before refactor before robustness
    order = [md.index(cap) for cap in ("bug-fix", "feature", "refactor", "robustness")]
    assert order == sorted(order)


# --- #43 reliability scoreboard -------------------------------------------------------


def test_clean_conclusion_rate_aggregates_single_run_outcomes() -> None:
    # Four single-run cards, one per bucket-ish: 2 clean (deliver + honest_park), 2 not.
    cards = [
        card("MCB-03", "bug-fix", "moderate", 80, True, outcome="clean_deliver"),
        card("MCB-04", "feature", "moderate", 0, False, outcome="honest_park"),
        card("MCB-05", "refactor", "hard", 0, False, outcome="thrash_park"),
        card("MCB-06", "robustness", "moderate", 100, True, outcome="false_ship"),
    ]
    report = build_suite(cards)
    assert report.runs == 4
    assert report.clean_conclusion_rate == 0.5  # deliver + honest_park of 4
    assert report.outcomes == {
        "clean_deliver": 1,
        "honest_park": 1,
        "thrash_park": 1,
        "false_ship": 1,
        "crash": 0,
    }
    # The per-case representative rides on the row.
    assert {r.case_id: r.outcome for r in report.cases}["MCB-06"] == "false_ship"


def test_clean_rate_counts_every_repeat_from_an_averaged_card() -> None:
    # An averaged card carries a full outcomes map (3 repeats): the suite counts all 3 runs.
    cards = [
        card("MCB-03", "bug-fix", "moderate", 70, True, outcomes={"clean_deliver": 3}),
        card(
            "MCB-05",
            "refactor",
            "hard",
            30,
            False,
            outcomes={"thrash_park": 2, "false_ship": 1},
        ),
    ]
    report = build_suite(cards)
    assert report.runs == 6  # 3 + 3, not 2 cards
    assert report.outcomes["clean_deliver"] == 3
    assert report.outcomes["thrash_park"] == 2 and report.outcomes["false_ship"] == 1
    assert report.clean_conclusion_rate == 0.5  # 3 clean of 6 runs


def test_suite_stamps_the_engine_version() -> None:
    # ADR-0055: the scoreboard trend is attributable to the engine version that produced it.
    import mosaera_core

    report = build_suite([card("MCB-03", "bug-fix", "moderate", 80, True, outcome="clean_deliver")])
    assert report.engine_version == mosaera_core.__version__
    assert report.to_dict()["engine_version"] == mosaera_core.__version__
    assert f"Engine: **v{mosaera_core.__version__}**" in render_suite_md(report, "s")


def test_reliability_section_renders_rate_and_buckets() -> None:
    cards = [card("MCB-03", "bug-fix", "moderate", 80, True, outcome="clean_deliver")]
    md = render_suite_md(build_suite(cards), "stamp-1")
    assert "Clean-conclusion rate: 100.0%" in md
    assert "Reliability (#43 scoreboard)" in md
    assert "false_ship" in md  # every bucket row is present even at zero


# --- Over-parks must survive averaging ---------------------------------------------------------
#
# `compare.average` collapses N repeats into ONE card, and a count that isn't explicitly aggregated
# there is simply gone by the time the suite sees it. That seam is annotated three times in
# compare.py (outcomes, critic vetoes, fingerprints) because it has bitten this repo repeatedly —
# and over-park is the number that already spent a week invisible.


def _park_card(case_id: str, *, over_park: bool | None = None, over_parks: int | None = None):
    c = card(case_id, "feature", "moderate", 70, False, outcome="honest_park")
    if over_park is not None:
        c.meta["over_park"] = over_park
    if over_parks is not None:
        c.meta["over_parks"] = over_parks
    return c


def test_single_run_cards_contribute_their_over_park_bool() -> None:
    report = build_suite([_park_card("MCB-01", over_park=True), _park_card("MCB-02")])
    assert report.over_parks == 1
    assert report.to_dict()["over_parks"] == 1


def test_averaged_cards_contribute_their_over_park_COUNT() -> None:
    """An averaged card carries a count across repeats. Reading it as a bool would report 1 for a
    case that over-parked three times — under-counting by the repeat factor, silently."""
    report = build_suite([_park_card("MCB-26", over_parks=3), _park_card("MCB-21", over_parks=1)])
    assert report.over_parks == 4


def test_the_history_row_carries_over_parks_and_its_rate(tmp_path) -> None:
    """The trend log's own gap, found by the 2026-08-07 audit. `over_parks` reached `to_dict` and
    the rendered markdown but NOT the history row — so the one metric the reliability program
    targets (correct work our own gates destroyed) had no trend line at all, while
    clean-conclusion did. A number you cannot trend is a number you cannot manage.
    """
    import json

    from mosaera_core.bench.suite import write_suite

    report = build_suite([_park_card("MCB-01", over_park=True), _park_card("MCB-02")])
    write_suite(tmp_path, report, "20260807-000000-abcdef")
    row = json.loads((tmp_path / "_suite" / "history.jsonl").read_text().splitlines()[-1])
    assert row["over_parks"] == 1
    assert row["over_park_rate"] == 0.5  # 1 of 2 runs
    # and the pre-existing trend fields are untouched
    assert "clean_conclusion_rate" in row and "outcomes" in row and row["runs"] == 2


def test_over_parks_are_reported_beside_the_frozen_outcome_not_inside_it() -> None:
    """`classify_outcome` is frozen (ADR-0069). An over-parking run stays an `honest_park` — it is
    honest about STOPPING and wrong about the WORK, and both readings must survive."""
    report = build_suite([_park_card("MCB-01", over_park=True)])
    assert report.outcomes["honest_park"] == 1
    assert report.outcomes.get("thrash_park", 0) == 0
    assert report.over_parks == 1
    assert "Over-parks: 1/1" in render_suite_md(report, "stamp")
