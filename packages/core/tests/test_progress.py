"""No-progress detection: normalization, fingerprinting, and the stall counter."""

from __future__ import annotations

from mosaera_core.progress import (
    bump_progress,
    bump_stall,
    fingerprint,
    normalize,
    parse_failing_count,
    parse_failing_tests,
    parse_yield,
    stall_message,
    wont_converge,
)


def test_wont_converge_flags_a_too_slow_crawl() -> None:
    # 12 → 11 → 10 (avg 1/attempt), 10 still failing, only 5 attempts left → 10/1 = 10 > 5 → won't
    # make it. THIS is the thrash the streak breaker misses (it keeps improving, so never trips).
    assert wont_converge([12, 11, 10], remaining=5) is True


def test_wont_converge_lets_an_on_track_run_continue() -> None:
    # 12 → 10 → 8 (avg 2/attempt), 8 failing, 5 left → 8/2 = 4 <= 5 → on track → do NOT trip.
    assert wont_converge([12, 10, 8], remaining=5) is False
    # exactly on the line (needs 4, has 4) is allowed to continue.
    assert wont_converge([12, 10, 8], remaining=4) is False


def test_wont_converge_is_conservative() -> None:
    assert wont_converge([12, 10], remaining=1) is False  # < min_history → no estimate
    assert wont_converge([5, 5, 5], remaining=3) is False  # no net progress → streak breaker's job
    assert wont_converge([5, 3, 0], remaining=1) is False  # already converged (current 0)
    assert wont_converge([], remaining=5) is False
    assert wont_converge([9, 6, 3], remaining=0) is False  # no attempts left → not this breaker


def test_parse_failing_count() -> None:
    # The pytest summary line — failed + error both count as "not passing" (#55 convergence signal).
    assert parse_failing_count("=== 3 failed, 5 passed in 0.42s ===") == 3
    assert parse_failing_count("== 2 failed, 1 error, 4 passed ==") == 3
    assert parse_failing_count("1 failed, 12 passed") == 1
    # No failing count present → None (a green run, or a non-pytest validator).
    assert parse_failing_count("=== 8 passed in 0.1s ===") is None
    assert parse_failing_count("compiled OK; no validator") is None
    assert parse_failing_count("") is None


def test_normalize_ignores_run_to_run_noise() -> None:
    # Same failure, different timings / line numbers / temp-dir suffixes → identical.
    a = "FAILED tests/test_x.py::test_it at line 42 (0.31s) in /tmp/ws_8837"
    b = "failed   tests/test_x.py::test_it at line 108 (1.90s) in /tmp/ws_2201"
    assert normalize(a) == normalize(b)


def test_fingerprint_stable_and_kind_scoped() -> None:
    assert fingerprint("test", "boom 1") == fingerprint("test", "boom 2")  # digits stripped
    assert fingerprint("test", "boom") != fingerprint("test", "different")
    # the same text under different loop "kinds" must not collide
    assert fingerprint("test", "x") != fingerprint("gate", "x")


def test_bump_stall_trips_after_limit_identical_outcomes() -> None:
    limit = 3
    fp = fingerprint("test", "same failure")
    prev, count = "", 0
    trail = []
    for _ in range(4):
        count, stalled = bump_stall(prev, fp, count, limit)
        trail.append(stalled)
        prev = fp
    # first sets the baseline (no repeat yet); trips on the 3rd identical outcome.
    assert trail == [False, False, True, True]


def test_bump_stall_resets_on_change() -> None:
    limit = 3
    a, b = fingerprint("test", "A"), fingerprint("test", "B")
    count, stalled = bump_stall(a, a, 1, limit)  # streak of identical A
    assert stalled is True
    count, stalled = bump_stall(a, b, count, limit)  # a different outcome resets
    assert count == 0 and stalled is False


def test_bump_stall_disabled_when_limit_not_above_one() -> None:
    fp = fingerprint("test", "x")
    _, stalled = bump_stall(fp, fp, 99, 1)
    assert stalled is False


def test_bump_progress_improving_counts_never_trip() -> None:
    # 5 → 3 → 1: each beats the best so far → streak stays 0, no trip (#56 honest-stop).
    best, streak, tripped = bump_progress(None, 0, 5, 3)
    assert (best, streak, tripped) == (5, 0, False)
    best, streak, tripped = bump_progress(best, streak, 3, 3)
    assert (best, streak, tripped) == (3, 0, False)
    best, streak, tripped = bump_progress(best, streak, 1, 3)
    assert (best, streak, tripped) == (1, 0, False)


def test_bump_progress_flat_counts_trip_at_the_limit() -> None:
    # 5 → 5 → 5 with limit 3: trips on the 3rd non-improving attempt (bump_stall's off-by-one).
    best, streak, tripped = bump_progress(None, 0, 5, 3)
    best, streak, tripped = bump_progress(best, streak, 5, 3)
    assert (streak, tripped) == (1, False)
    best, streak, tripped = bump_progress(best, streak, 5, 3)
    assert (streak, tripped) == (2, True)


def test_bump_progress_oscillation_trips() -> None:
    # 5 → 6 → 5: never beats best=5 → a non-converging streak the two-value #55 window
    # (and the digit-stripped fingerprint) cannot see. The whole point of best-so-far.
    best, streak, tripped = bump_progress(None, 0, 5, 3)
    best, streak, tripped = bump_progress(best, streak, 6, 3)
    assert (best, streak, tripped) == (5, 1, False)
    best, streak, tripped = bump_progress(best, streak, 5, 3)
    assert (best, streak, tripped) == (5, 2, True)


def test_bump_progress_improvement_resets_a_started_streak() -> None:
    best, streak, _ = bump_progress(None, 0, 5, 3)
    best, streak, _ = bump_progress(best, streak, 5, 3)  # streak 1
    best, streak, tripped = bump_progress(best, streak, 2, 3)  # beats best → reset
    assert (best, streak, tripped) == (2, 0, False)


def test_bump_progress_disabled_when_limit_not_above_one() -> None:
    _best, _streak, tripped = bump_progress(1, 99, 1, 1)
    assert tripped is False


def test_parse_failing_tests_reads_the_short_summary() -> None:
    out = parse_failing_tests(
        "FAILED tests/test_a.py::test_x - assert 1 == 2\n"
        "FAILED tests/test_a.py::test_y - boom\n"
        "ERROR tests/test_b.py::test_z\n"
        "FAILED tests/test_a.py::test_x - assert 1 == 2\n"  # duplicate → deduped
    )
    assert out == ["tests/test_a.py::test_x", "tests/test_a.py::test_y", "tests/test_b.py::test_z"]


def test_parse_failing_tests_caps_and_handles_absence() -> None:
    many = "\n".join(f"FAILED t.py::t{i}" for i in range(9))
    assert len(parse_failing_tests(many, cap=5)) == 5
    assert parse_failing_tests("=== 8 passed ===") == []
    assert parse_failing_tests("") == []


def test_parse_yield_extracts_blocked_and_escalate() -> None:
    # Recognizes the 'SUMMARY: blocked/escalate — …' convention repo.py emits.
    assert parse_yield("SUMMARY: blocked — cannot rename files") == ("cannot rename files", "")
    assert parse_yield("summary:  ESCALATE:  task conflicts with test_x") == (
        "",
        "task conflicts with test_x",
    )
    # both kinds present → first of each wins
    b, e = parse_yield("SUMMARY: blocked — no delete tool\nSUMMARY: escalate — need a decision")
    assert b == "no delete tool" and e == "need a decision"
    # tolerant of leading prose and a hyphen/colon separator
    assert parse_yield("...work done...\nSUMMARY: blocked - stuck here")[0] == "stuck here"


def test_parse_yield_absent_returns_empty() -> None:
    assert parse_yield("SUMMARY: implemented the feature and tests pass") == ("", "")
    assert parse_yield("") == ("", "")


def test_stall_message_is_honest_and_includes_forge_summary() -> None:
    msg = stall_message("validation failed the same way 3 times in a row", "I cannot delete files.")
    assert "no progress" in msg.lower()
    assert "beyond what I can complete" in msg
    assert "I cannot delete files." in msg
    # no summary → still a complete, honest message
    assert "Forge" not in stall_message("reason", "  ")
