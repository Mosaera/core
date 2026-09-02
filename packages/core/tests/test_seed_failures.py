"""Per-test red-verify parsing (P2 Stage A) — absence must never read as evidence.

`authored_seed_results` answers two questions from one pytest run: is the authored suite red
(the ADR-0013 red-verify), and WHICH tests fail against the seed. The second is P2's raw signal,
so its parse has the vacancy obligation this branch keeps enforcing: ``None`` (could not read)
and ``[]`` (read, nothing failed) are different evidence and must never collapse.
"""

from __future__ import annotations

from mosaera_core.seedcheck import seed_failures_from_output

_RED_TAIL = """\
F..F                                                                     [100%]
=================================== FAILURES ===================================
...
=========================== short test summary info ============================
FAILED tests/test_tags.py::test_find_prints_matching - AssertionError: assert...
FAILED tests/test_tags.py::test_list_format_exact - AssertionError
2 failed, 2 passed in 0.21s
"""


def test_failing_node_ids_are_parsed_exactly() -> None:
    assert seed_failures_from_output(_RED_TAIL) == [
        "tests/test_tags.py::test_find_prints_matching",
        "tests/test_tags.py::test_list_format_exact",
    ]


def test_a_green_run_earns_the_empty_list() -> None:
    assert seed_failures_from_output("....\n4 passed in 0.10s\n") == []


def test_garbage_is_absence_never_the_empty_list() -> None:
    """THE VACANCY PIN. An unreadable tail must not report "nothing failed" — that would let a
    crashed red-verify look identical to a clean one, the exact class measured five times on
    2026-08-10."""
    assert seed_failures_from_output("INTERNALERROR> boom") is None
    assert seed_failures_from_output("") is None
    assert seed_failures_from_output("   \n") is None


def test_collection_errors_are_failures_not_absence() -> None:
    out = "ERROR collecting tests/test_x.py\n1 error in 0.05s\n"
    assert seed_failures_from_output(out) == ["tests/test_x.py"]


def test_stays_in_sync_with_the_grader_parser() -> None:
    """The regex is deliberately a copy of `bench/grade._FAILED_ID` (core must not import the
    measurement layer). This pin fails if either side drifts."""
    from mosaera_core.bench.grade import _FAILED_ID
    from mosaera_core.seedcheck import _SEED_FAILED_ID

    assert _SEED_FAILED_ID.pattern == _FAILED_ID.pattern


def test_colourised_output_is_parsed_not_reported_absent() -> None:
    """Found by the offline replay: a colourised pytest puts an ANSI escape between FAILED and
    the node id. The vacancy pin held (None, never a lying []) — but the parser must also SEE
    through colour, or every tty-adjacent run reads as unassessable."""
    out = (
        "\x1b[31mFAILED\x1b[0m tests/test_x.py::\x1b[1mtest_y\x1b[0m - AssertionError\n"
        "1 failed in 0.1s\n"
    )
    assert seed_failures_from_output(out) == ["tests/test_x.py::test_y"]
