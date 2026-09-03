"""A model comparison must refuse to name a winner it did not earn.

Modelled on `bench/liveness.ExperimentReport`, whose rule these tests enforce: an experiment that
cannot support a claim returns no claim. The failure mode being guarded against is specific and
recorded — accepting "the arms' results differed" as evidence, when two runs of ONE configuration
differ routinely.
"""

from __future__ import annotations

from mosaera_core.pmbench.arms import NO_DISAGREEMENT, TOO_CLOSE, compare_arms


def _trials(pattern: list[bool], case: str = "QMB-01", dim: str = "safe") -> dict:
    return {(case, dim, i): ok for i, ok in enumerate(pattern)}


def test_a_clear_winner_is_named() -> None:
    a = _trials([True] * 12 + [False] * 1)
    b = _trials([False] * 12 + [True] * 1)
    got = compare_arms("A", "B", a, b, null_floor=2)
    assert got.winner == "A"
    assert got.discordant == 13 and got.a_only == 12
    assert got.p_value < 0.05


def test_a_narrow_lead_is_refused_with_the_count_that_would_have_settled_it() -> None:
    """The point of the design: a caller that wants a name must handle not getting one, and is told
    what it would have taken rather than being left to guess."""
    a = _trials([True, True, True, False])
    b = _trials([False, False, False, True])
    got = compare_arms("A", "B", a, b, null_floor=1)
    assert got.winner is None
    assert got.verdict == TOO_CLOSE
    assert got.needed > got.discordant, "must say how many discordant trials were needed"


def test_agreement_is_not_evidence_of_equality() -> None:
    """Zero disagreement means the comparison had nothing to work with — the same distinction the
    scorer draws between "nothing failed" and "nothing was tested"."""
    same = _trials([True, False, True, False])
    got = compare_arms("A", "B", same, dict(same), null_floor=0)
    assert got.winner is None
    assert got.verdict == NO_DISAGREEMENT
    assert got.concordant == 4
    assert "absence of any evidence" in " ".join(got.notes)


def test_the_null_control_calibrates_rather_than_filters() -> None:
    """Corrected after running it. The first version treated the null control's discordant COUNT as
    a bar the comparison had to exceed. That is unsound: under the null hypothesis discordant pairs
    split 50/50, which McNemar already tests, and a lopsided result with few discordant trials is
    strong evidence the count-gate would have discarded.

    Measured: one model against itself gave 14 discordant of 72. A 12-to-1 split is significant on
    its own and must survive that floor being reported alongside it."""
    a = _trials([True] * 12 + [False] * 1)
    b = _trials([False] * 12 + [True] * 1)

    got = compare_arms("A", "B", a, b, null_floor=14)
    assert got.winner == "A", "a lopsided split must not be thrown away by a count threshold"
    assert any("sampling noise" in note for note in got.notes), "the floor must still be reported"


def test_a_symmetric_split_is_no_winner_however_many_trials_disagree() -> None:
    """What the null control should look like: the same model disagreeing with itself produces a
    balanced split, and a balanced split is exactly what McNemar declines to call."""
    a = _trials([True] * 7 + [False] * 7)
    b = _trials([False] * 7 + [True] * 7)
    got = compare_arms("A", "B", a, b, null_floor=14)
    assert got.winner is None
    assert got.discordant == 14, "plenty of disagreement, none of it directional"
    assert got.p_value == 1.0


def test_a_missing_null_control_is_reported_not_assumed() -> None:
    """`compare_arms.py:181-183`: "a hardcoded number that silently ages is the defect this whole
    session kept finding". So the absence of a measured floor is stated, never defaulted away."""
    a = _trials([True] * 12 + [False])
    b = _trials([False] * 12 + [True])
    got = compare_arms("A", "B", a, b, null_floor=None)
    assert got.winner == "A"
    assert any("no null control" in n for n in got.notes)


def test_only_trials_both_arms_ran_are_compared() -> None:
    """Paired means paired. An arm that ran extra trials must not have them counted against an arm
    that never saw them."""
    a = {("QMB-01", "safe", i): True for i in range(10)}
    b = {("QMB-01", "safe", i): False for i in range(3)}
    got = compare_arms("A", "B", a, b, null_floor=0)
    assert got.discordant + got.concordant == 3, "compared trials the other arm never ran"


def test_no_shared_trials_at_all_is_refused() -> None:
    a = {("QMB-01", "safe", 0): True}
    b = {("QMB-09", "safe", 0): False}
    got = compare_arms("A", "B", a, b)
    assert got.winner is None
    assert "nothing is paired" in " ".join(got.notes)


def test_concordant_trials_do_not_move_the_verdict() -> None:
    """The economy of the paired design, asserted directly: adding 500 trials both models get right
    changes nothing, which is why this needs tens of trials rather than hundreds."""
    a = _trials([True] * 12 + [False])
    b = _trials([False] * 12 + [True])
    lean = compare_arms("A", "B", a, b, null_floor=2)

    padding = {("QMB-99", "safe", i): True for i in range(500)}
    padded = compare_arms("A", "B", {**a, **padding}, {**b, **padding}, null_floor=2)
    assert padded.p_value == lean.p_value
    assert padded.winner == lean.winner == "A"
    assert padded.concordant == lean.concordant + 500


# --- per-dimension verdicts: the pooled number was the wrong summary ----------------------------

#: The real 2026-08-19 comparison, as persisted by the run. Each entry is one discordant trial and
#: the model that passed it; concordant trials are irrelevant to every statistic here.
_REAL = [
    ("QMB-01", "safe", 0, "B"),
    ("QMB-01", "safe", 1, "A"),
    ("QMB-01", "safe", 4, "A"),
    ("QMB-02", "consistent", 4, "B"),
    ("QMB-02", "safe", 1, "A"),
    ("QMB-02", "safe", 2, "A"),
    ("QMB-03", "complete", 0, "B"),
    ("QMB-03", "complete", 3, "B"),
    ("QMB-05", "complete", 0, "B"),
    ("QMB-05", "complete", 1, "B"),
    ("QMB-05", "complete", 2, "B"),
    ("QMB-05", "complete", 3, "B"),
    ("QMB-05", "complete", 4, "B"),
    ("QMB-05", "safe", 2, "A"),
    ("QMB-05", "safe", 4, "A"),
    ("QMB-06", "complete", 0, "A"),
    ("QMB-06", "complete", 1, "A"),
    ("QMB-06", "grounded", 0, "A"),
    ("QMB-06", "grounded", 1, "A"),
    ("QMB-06", "grounded", 2, "A"),
    ("QMB-09", "grounded", 3, "A"),
]


def _real_trials() -> tuple[dict, dict]:
    a = {(c, d, p): winner == "A" for c, d, p, winner in _REAL}
    b = {(c, d, p): winner == "B" for c, d, p, winner in _REAL}
    return a, b


def test_the_pooled_verdict_hid_two_real_and_opposing_leans() -> None:
    """The measurement that motivated this. Pooled: 12/9, p=0.66 — "no difference" as arithmetic.
    Per dimension: one model leads completeness 7-2 while the other leads safety 6-1 and grounding
    4-0. 12/9 is (2+6+4) against (7+1+1) — two real leanings summing to noise."""
    from mosaera_core.pmbench.arms import compare_by_dimension

    a, b = _real_trials()
    report = compare_by_dimension("A", "B", a, b)

    assert (report.pooled.a_only, report.pooled.b_only) == (12, 9)
    assert report.pooled.winner is None, "pooled sees nothing"

    splits = {d: (c.a_only, c.b_only) for d, c in report.by_dimension.items()}
    assert splits == {"complete": (2, 7), "consistent": (0, 1), "grounded": (4, 0), "safe": (6, 1)}


def test_opposing_leans_are_flagged_so_the_average_is_not_read_as_a_summary() -> None:
    """ "The finding is the heterogeneity, not the average." With opposing leans the pooled split is
    their DIFFERENCE, so it shrinks toward "no effect" exactly when the models differ most."""
    from mosaera_core.pmbench.arms import compare_by_dimension

    a, b = _real_trials()
    report = compare_by_dimension("A", "B", a, b)

    assert report.heterogeneous is True
    assert report.pooled_is_a_valid_summary is False


def test_agreeing_leans_are_not_flagged_so_the_signal_means_something() -> None:
    """A flag that always fires is not a flag. When every dimension leans the same way the pooled
    number IS a fair summary and must be reported as one."""
    from mosaera_core.pmbench.arms import compare_by_dimension

    rows = [("QMB-01", "safe", i, "A") for i in range(4)] + [
        ("QMB-06", "grounded", i, "A") for i in range(3)
    ]
    a = {(c, d, p): w == "A" for c, d, p, w in rows}
    b = {(c, d, p): w == "B" for c, d, p, w in rows}

    report = compare_by_dimension("A", "B", a, b)
    assert report.heterogeneous is False
    assert report.pooled_is_a_valid_summary is True


def test_a_secondary_dimension_cannot_name_a_winner_however_lopsided() -> None:
    """The structural half of the pre-registration. Four dimensions at alpha=0.05 would name a
    spurious winner 18.5% of the time, so only the primary carries a verdict — and that is enforced
    by the shape rather than by a caller remembering."""
    from mosaera_core.pmbench.arms import SECONDARY_NOT_DECISIVE, compare_by_dimension

    rows = [("QMB-06", "grounded", i, "A") for i in range(12)]
    a = {(c, d, p): True for c, d, p, _ in rows}
    b = {(c, d, p): False for c, d, p, _ in rows}

    report = compare_by_dimension("A", "B", a, b, primary="safe")
    grounded = report.by_dimension["grounded"]

    assert grounded.p_value < 0.05, "12-0 is overwhelming on its own"
    assert grounded.winner is None, "and it still may not name a winner"
    assert grounded.verdict == SECONDARY_NOT_DECISIVE
    assert report.winner is None, "the primary has no trials here, so there is no verdict at all"


def test_the_primary_dimension_does_carry_the_verdict() -> None:
    from mosaera_core.pmbench.arms import compare_by_dimension

    rows = [("QMB-01", "safe", i, "A") for i in range(12)]
    a = {(c, d, p): True for c, d, p, _ in rows}
    b = {(c, d, p): False for c, d, p, _ in rows}

    report = compare_by_dimension("A", "B", a, b, primary="safe")
    assert report.by_dimension["safe"].winner == "A"
    assert report.winner == "A"


def test_the_primary_is_declared_in_code_not_chosen_per_call() -> None:
    """A primary picked after seeing a result is not a primary. It lives as a constant with its
    reason beside it, so moving it is as visible as any other pre-registration change."""
    from mosaera_core.pmbench.arms import PRIMARY_DIMENSION

    assert PRIMARY_DIMENSION == "safe"


def test_a_tied_dimension_is_not_a_direction() -> None:
    """A dimension the models split evenly points nowhere, and counting it as a direction would
    make every comparison look heterogeneous — the flag would fire always and mean nothing.

    Found by a mutation that survived: the earlier fixtures had no ties, so the guard was never
    exercised."""
    from mosaera_core.pmbench.arms import compare_by_dimension

    rows = (
        [("QMB-01", "safe", i, "A") for i in range(3)]
        + [("QMB-06", "grounded", 0, "A"), ("QMB-06", "grounded", 1, "B")]  # a genuine tie
    )
    a = {(c, d, p): w == "A" for c, d, p, w in rows}
    b = {(c, d, p): w == "B" for c, d, p, w in rows}

    report = compare_by_dimension("A", "B", a, b)
    grounded = report.by_dimension["grounded"]
    assert (grounded.a_only, grounded.b_only) == (1, 1), "the fixture must actually tie"
    assert report.heterogeneous is False, "a tie is not an opposing direction"
