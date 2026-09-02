"""Reliability classification — the #43 scoreboard's pure classifier + aggregation (offline)."""

from __future__ import annotations

from mosaera_core.bench.reliability import (
    CLEAN_DELIVER,
    CRASH,
    FALSE_SHIP,
    HONEST_PARK,
    THRASH_PARK,
    classify_outcome,
    classify_park_cause,
    clean_conclusion_rate,
    is_clean,
    merge_counts,
    tally,
    worst_outcome,
)


def test_crash_dominates_even_a_delivery_flag() -> None:
    # An escaped exception is a crash regardless of any stale approved flag in final.
    assert classify_outcome({"approved": True}, errored=True, acceptance_failed=False) == CRASH


def test_approved_and_grader_clean_is_clean_deliver() -> None:
    assert (
        classify_outcome({"approved": True}, errored=False, acceptance_failed=False)
        == CLEAN_DELIVER
    )


def test_approved_but_grader_failed_is_false_ship() -> None:
    # Delivered, but the hidden acceptance suite fails → a dishonest "success".
    assert classify_outcome({"approved": True}, errored=False, acceptance_failed=True) == FALSE_SHIP


def test_park_after_breaker_trip_is_thrash() -> None:
    # The no-progress breaker tripped (stalled) → it ground to a stop, didn't self-stop early.
    final = {"approved": False, "stalled": True, "stall_reason": "same failure 3x"}
    assert classify_outcome(final, errored=False, acceptance_failed=False) == THRASH_PARK


def test_park_at_the_iteration_cap_is_thrash() -> None:
    # The gate's own iteration_limit reason = rode the loop to the cap → thrash.
    final = {
        "approved": False,
        "gate_decision": {"reasons": ["oracle_unverified", "iteration_limit"]},
    }
    assert classify_outcome(final, errored=False, acceptance_failed=False) == THRASH_PARK


def test_park_riding_to_the_cap_is_thrash_without_a_committed_reason() -> None:
    # #51 measurement fix: the gate's iteration_limit reason parks-then-never-resumes, so it never
    # commits to `final`; a reviewer-revise loop that rode to the cap must still bucket as thrash
    # via the committed `iteration` counter. iteration >= cap → thrash; below cap → honest.
    at_cap = {"approved": False, "iteration": 3}
    assert classify_outcome(at_cap, errored=False, acceptance_failed=False, max_iterations=3) == (
        THRASH_PARK
    )
    below = {"approved": False, "iteration": 2}
    assert classify_outcome(below, errored=False, acceptance_failed=False, max_iterations=3) == (
        HONEST_PARK
    )
    # Without a cap passed (pre-#51 callers), the ride-to-cap axis is inert.
    assert classify_outcome(at_cap, errored=False, acceptance_failed=False) == HONEST_PARK


def test_prompt_park_on_a_real_reason_is_honest() -> None:
    # Parked on a legitimate blocker, no breaker trip, no cap → an honest early stop (clean).
    final = {"approved": False, "gate_decision": {"reasons": ["reviewer_blocked"]}}
    assert classify_outcome(final, errored=False, acceptance_failed=False) == HONEST_PARK
    # And a bare park with no gate_decision at all is still honest, not thrash.
    assert (
        classify_outcome({"approved": False}, errored=False, acceptance_failed=False) == HONEST_PARK
    )


# --- classify_park_cause: the terminal-mechanism diagnostic (thrash-cause instrumentation) ---


def test_park_cause_is_empty_for_a_delivery() -> None:
    # The cause question is about parks; an approved run has none.
    assert classify_park_cause({"approved": True}) == ""


def test_park_cause_give_up_and_plan_unworkable_are_honest() -> None:
    give_up = {"approved": False, "give_up_reason": "no convergence: 5 → 5 → 5"}
    assert classify_park_cause(give_up) == "give_up"
    assert classify_outcome(give_up, errored=False, acceptance_failed=False) == HONEST_PARK
    plan = {"approved": False, "plan_unworkable_reason": "couldn't form a workable plan"}
    assert classify_park_cause(plan) == "plan_unworkable"
    assert classify_outcome(plan, errored=False, acceptance_failed=False) == HONEST_PARK


def test_park_cause_names_the_stalled_loop_and_is_thrash() -> None:
    # The fingerprint-stall breaker tripped; name the kind with the highest streak. → thrash.
    final = {
        "approved": False,
        "stalled": True,
        "stall_reason": "same failure 3x",
        "stall_by_kind": {"test": ["fp1", 1], "review": ["fp2", 3]},
    }
    assert classify_park_cause(final) == "stalled:review"
    assert classify_outcome(final, errored=False, acceptance_failed=False) == THRASH_PARK
    # No stall_by_kind map → "unknown" rather than an error.
    assert classify_park_cause({"approved": False, "stalled": True}) == "stalled:unknown"


def test_park_cause_iteration_limit_and_rode_to_cap_are_thrash() -> None:
    committed = {
        "approved": False,
        "gate_decision": {"reasons": ["oracle_unverified", "iteration_limit"]},
    }
    assert classify_park_cause(committed) == "iteration_limit"
    assert classify_outcome(committed, errored=False, acceptance_failed=False) == THRASH_PARK
    rode = {"approved": False, "iteration": 3}
    assert classify_park_cause(rode, max_iterations=3) == "rode_to_cap"
    assert classify_outcome(rode, errored=False, acceptance_failed=False, max_iterations=3) == (
        THRASH_PARK
    )


def test_park_cause_bare_park_below_the_cap_is_parked_and_honest() -> None:
    # Fell through every thrash signal → an autonomous gate park below the cap (honest).
    below = {"approved": False, "iteration": 2, "gate_decision": {"reasons": ["reviewer_blocked"]}}
    assert classify_park_cause(below, max_iterations=3) == "parked"
    assert classify_outcome(below, errored=False, acceptance_failed=False, max_iterations=3) == (
        HONEST_PARK
    )


def test_is_clean_only_deliver_and_honest_park() -> None:
    assert is_clean(CLEAN_DELIVER) and is_clean(HONEST_PARK)
    assert not is_clean(THRASH_PARK)
    assert not is_clean(FALSE_SHIP)
    assert not is_clean(CRASH)


def test_tally_has_every_bucket_and_ignores_unknown() -> None:
    counts = tally([CLEAN_DELIVER, CLEAN_DELIVER, THRASH_PARK, "bogus"])
    assert counts == {
        CLEAN_DELIVER: 2,
        HONEST_PARK: 0,
        THRASH_PARK: 1,
        FALSE_SHIP: 0,
        CRASH: 0,
    }


def test_merge_counts_sums_known_buckets() -> None:
    merged = merge_counts([{CLEAN_DELIVER: 2, THRASH_PARK: 1}, {CLEAN_DELIVER: 1, "bogus": 9}])
    assert merged[CLEAN_DELIVER] == 3 and merged[THRASH_PARK] == 1
    assert "bogus" not in merged


def test_worst_outcome_is_most_severe_present() -> None:
    # false_ship outranks a pile of clean deliveries — deny-by-default representative.
    assert worst_outcome([CLEAN_DELIVER, CLEAN_DELIVER, FALSE_SHIP]) == FALSE_SHIP
    assert worst_outcome([CLEAN_DELIVER, HONEST_PARK]) == HONEST_PARK
    assert worst_outcome([CRASH, THRASH_PARK]) == CRASH
    assert worst_outcome([]) is None


def test_clean_conclusion_rate() -> None:
    # 3 of 4 clean (2 deliver + 1 honest-park), 1 thrash → 0.75.
    counts = {CLEAN_DELIVER: 2, HONEST_PARK: 1, THRASH_PARK: 1, FALSE_SHIP: 0, CRASH: 0}
    assert clean_conclusion_rate(counts) == 0.75
    # A false-ship is NOT clean — "just succeed" must be TRUE success.
    assert clean_conclusion_rate({CLEAN_DELIVER: 1, FALSE_SHIP: 1}) == 0.5
    # No runs → 0.0, never a divide-by-zero.
    assert clean_conclusion_rate({b: 0 for b in (CLEAN_DELIVER, THRASH_PARK)}) == 0.0


def test_the_scorecard_still_feeds_the_classifier_uncaptured_state() -> None:
    """Source-level ratchet for ADR-0078's safety property.

    `bench/cli.py` now sources `gate_reasons` from the captured interrupt payload, which
    deliberately sees MORE than the classifier does. If a future refactor "tidied" that asymmetry
    away by passing the captured reasons to `classify_outcome`, `iteration_limit` would become
    visible and previously-`honest_park` runs would reclassify as `thrash_park` — silently moving
    the frozen clean-conclusion headline (ADR-0069). The behavioural pin lives in
    test_bench_harness.py; this catches the refactor at the call site, where it would be written.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "mosaera_core" / "bench" / "cli.py").read_text(
        encoding="utf-8"
    )
    assert "classify_outcome(\n        run.final," in src, (
        "classify_outcome must be passed run.final, NOT the captured terminal decision"
    )
    assert "classify_park_cause(run.final," in src, (
        "classify_park_cause must be passed run.final, NOT the captured terminal decision"
    )
