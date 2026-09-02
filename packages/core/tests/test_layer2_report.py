"""Layer-2's standing record reads the fields that already existed and nobody crossed.

The per-run fields (`layer2_class`, `layer2_verdict`, `layer2_decline`) have been written since
`#76`. Crossing them with `grader_passed` is the whole measurement, and until 2026-08-08 nothing
did — a scan of 2,049 stored cards found **zero** where Layer 2 was ever eligible. Declared fields
with no consumer is this repo's most-repeated defect (F74); these tests are the consumer's proof.
"""

from __future__ import annotations

from typing import Any

from mosaera_core.bench.layer2_report import _bound, render, summarize


def _card(**meta: Any) -> dict[str, Any]:
    base = {"outcome": "honest_park", "_case": "MCB-XX"}
    return {**base, **meta}


def test_the_four_cells_are_counted_separately() -> None:
    """A single number would hide which failure happened — the asymmetry is the point."""
    cards = [
        _card(layer2_class="engine_blocked_give_up", layer2_verdict="verified", grader_passed=True),
        _card(layer2_class="oracle_unverified", layer2_verdict="verified", grader_passed=False),
        _card(layer2_class="oracle_unverified", layer2_verdict="unverified", grader_passed=True),
        _card(layer2_class="oracle_unverified", layer2_verdict="unavailable", grader_passed=False),
        _card(outcome="clean_deliver", grader_passed=True),  # not a park — must not be counted
    ]
    s = summarize(cards)
    assert s["honest_parks"] == 4
    assert s["eligible"] == 4
    assert s["matrix"][("converted", "work was right")] == 1  # the win
    assert s["matrix"][("converted", "work was wrong")] == 1  # the false ship
    assert s["matrix"][("left parked", "work was right")] == 1  # the waste
    assert s["matrix"][("left parked", "work was wrong")] == 1  # the correct refusal


def test_only_verified_counts_as_shipped() -> None:
    """`unverified` and `unavailable` leave the park standing — the safe direction.

    Counting either as a conversion would inflate the win column with runs that never shipped.
    """
    cards = [
        _card(layer2_class="c", layer2_verdict=v, grader_passed=True)
        for v in ("unverified", "unavailable", None)
    ]
    assert summarize(cards)["matrix"][("converted", "work was right")] == 0
    assert summarize(cards)["matrix"][("left parked", "work was right")] == 3


def test_an_ungraded_park_is_never_scored_as_a_win_or_a_failure() -> None:
    """Deny-by-default applied to the measurement: no ground truth, no claim either way."""
    s = summarize([_card(layer2_class="c", layer2_verdict="verified", grader_passed=None)])
    assert s["matrix"][("converted", "work was right")] == 0
    assert s["matrix"][("converted", "work was wrong")] == 0
    assert s["matrix"][("converted", "ungraded")] == 1


def test_the_bound_is_never_reported_as_zero() -> None:
    """A clean small sample bounds the error rate near 50%, not near 0.

    ADR-0061's gate-2 amendment: *a rate is only a result when the distribution it bounds is
    named.* Printing "0 false ships" without the bound is precisely the overclaim it exists to
    stop, so the renderer is not allowed to produce a bare zero.
    """
    assert "NOT zero" in _bound(0, 5)
    assert "~60%" in _bound(0, 5)  # rule of three over five conversions
    assert "~3%" in _bound(0, 100)
    assert "nothing is bounded" in _bound(0, 0)
    assert "FALSE SHIPS" in _bound(1, 5) and "knob stays off" in _bound(1, 5)


def test_never_eligible_is_reported_as_a_result_not_a_blank() -> None:
    """The historical state, and the one most likely to recur.

    A report that renders an empty table when nothing fired is indistinguishable from a report
    nobody ran. It has to say so in words.
    """
    out = render(summarize([_card(), _card()]))
    assert "NEVER ELIGIBLE" in out
    assert "a real result, not a missing measurement" in out


def test_the_render_survives_a_real_shaped_summary() -> None:
    out = render(
        summarize(
            [
                _card(
                    layer2_class="engine_blocked_give_up",
                    layer2_verdict="verified",
                    grader_passed=True,
                ),
                _card(
                    layer2_class="oracle_unverified",
                    layer2_decline="class2: gate reason(s) outside",
                ),
            ]
        )
    )
    assert "the win     : 1" in out
    assert "why it was never attempted" in out


def test_the_reason_an_attempt_declined_is_reported() -> None:
    """`unverified` alone is not a finding — three opposite causes share that verdict.

    "the delivered code fails the independent acceptance test" means the park was right; "does not
    catch a mutation" means the authored test is a rubber stamp; "inconclusive" means the oracle
    could not form a question at all. Reporting only the verdict cost two hours and a wrong
    conclusion on 2026-08-08 — seven declines read as weak tests were in fact seven inconclusives.
    """
    cards = [
        _card(
            layer2_class="oracle_unverified",
            layer2_verdict="unverified",
            layer2_reason="the mutation check was inconclusive",
            layer2_mutation_caught=None,
            grader_passed=True,
        ),
        _card(
            layer2_class="oracle_unverified",
            layer2_verdict="unverified",
            layer2_reason="the authored test does not catch a mutation of the change",
            layer2_mutation_caught=False,
            grader_passed=True,
        ),
    ]
    out = render(summarize(cards))
    assert "why each ATTEMPT decided as it did" in out
    assert "inconclusive" in out and "does not catch a mutation" in out
    # The decisive distinction, kept separable rather than collapsed into one count.
    assert summarize(cards)["mutation"] == {"inconclusive": 1, "SURVIVED": 1}


def test_an_unrecorded_reason_is_named_not_blanked() -> None:
    """Cards written before this field existed must read as "(not recorded)", never as agreement
    with whatever the newest cards say — that is how a mixed corpus tells a comfortable lie."""
    s = summarize([_card(layer2_class="c", layer2_verdict="unverified", grader_passed=True)])
    assert s["reasons"] == {"(not recorded)": 1}
