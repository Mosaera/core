"""Coder self-heal prompt(s) kept out of the node modules so they're unit-testable
outside the graph."""

from __future__ import annotations

from collections.abc import Sequence

from mosaera_core.graph._baseline import regression_note


def _convergence_line(now: int | None, prev: int | None, repeat: int = 0) -> str:
    """A one-line failing-count trend so the coder can tell converging from spinning (#55).

    ``repeat`` (#81) covers the case where there is NO count: how many times in a row the
    validator produced the identical outcome. Without it the coder got literally nothing on that
    path — raw psql/tsc text and no indication its last edit changed anything — which is half of
    why those runs spun until the breaker tripped. Unreachable when ``now`` is not None, so this
    is a no-op for pytest by construction.
    """
    if now is None:
        if repeat > 0:
            return (
                f"The validation output was IDENTICAL to your last attempt ({repeat + 1} in a "
                "row) — your last edit changed NOTHING the validator can see. Find a DIFFERENT "
                "root cause before editing again."
            )
        return ""
    if prev is None:
        return f"Failing tests: {now}."
    if now < prev:
        return f"Failing tests: {now} (was {prev} — you're getting CLOSER; keep going)."
    if now > prev:
        return f"Failing tests: {now} (was {prev} — that got WORSE; reconsider your last change)."
    return (
        f"Failing tests: {now} (was {prev} — NO change; your last edit didn't help — "
        "find a DIFFERENT root cause before editing again)."
    )


def fix_instruction(
    test_output: str,
    *,
    diagnose: bool = False,
    failing_now: int | None = None,
    failing_prev: int | None = None,
    repeat: int = 0,
    regressions: Sequence[str] = (),
) -> str:
    """The coder's self-heal prompt for a failing validation suite. Beyond "fix the
    tests", it offers an escalation valve (ADR-0012/0013): a protected acceptance test can
    over-specify beyond the task's stated contract (e.g. demand exit code EXACTLY 2 when the
    task only says "non-zero"). The coder can't edit tests, so no correct change satisfies
    it — thrashing to the iteration cap then parks. The `SUMMARY: escalate` hand-raise (the
    same one the author_tests handoff uses) is parsed by capture_node and routes to the
    supervisor, which re-scopes (the tester re-authors) instead of the run parking.

    ``regressions`` names tests that PASSED before this run and fail now. It leads the prompt
    because it is the one fact that redirects the search: on 2026-08-20 a coder iterated three
    times on its acceptance tests while its change had broken the CLI's existing subcommands, then
    concluded the environment was at fault. It had no way to know which is which; now it is told.

    ``diagnose`` (#55, ADR-0059, coder_diagnose_loop): push the coder through the disciplined
    loop — understand the exact diff, form a one-line HYPOTHESIS, make ONE surgical change —
    instead of guess-and-rerun, and show it the failing-count trend so it can tell whether it
    is converging."""
    regressed = regression_note(regressions)
    if diagnose:
        conv = _convergence_line(failing_now, failing_prev, repeat)
        lead = (
            "The validation suite failed. Before editing: read the EXACT expected-vs-actual below "
            "(the output now shows full assertion diffs); if unsure what your code produces, run a "
            "sandbox_exec snippet to see it. Then state, in ONE line, "
            "'HYPOTHESIS: <the root cause>' and make the single surgical change that addresses it "
            "— do NOT guess-and-rerun; do not weaken or delete tests.\n\n"
        )
        if conv:
            lead += conv + "\n\n"
    else:
        lead = (
            "The validation suite failed. Fix the failing tests — change only what is "
            "needed, do not weaken or delete tests.\n\n"
        )
    return (
        (regressed + "\n\n" if regressed else "")
        + lead
        + "If (and only if) a failing test demands MORE than the task's stated contract — "
        "so no correct change could satisfy it without contradicting the task (e.g. it "
        "asserts an exact exit code, error string, or format the task never specified) — "
        "do not thrash. Reply exactly 'SUMMARY: escalate — <test name> over-specifies "
        "beyond the contract: <what it demands vs what the task states>'.\n\n"
        f"Validation output:\n{test_output}"
    )
