"""No-progress detection for the run graph.

A run has resource ceilings (iterations, coder steps, spend, wall-clock) but those
only answer "spent too much" — not "this isn't going anywhere". When a task is
beyond what the coder can do (e.g. an unsatisfiable request, or a fix it can't
find), the graph otherwise loops to the iteration cap producing the SAME failing
outcome every time, burning tokens and — if a spend ceiling is set — asking a human
to fund more of the same loop.

These helpers fingerprint each attempt's outcome and count consecutive identical
ones, so the graph can trip a circuit breaker and park HONESTLY ("I can't complete
this — here's why") instead of thrashing. Pure and deterministic — no model call.
"""

from __future__ import annotations

import hashlib
import re

from mosaera_core.testreport import TestReport

_DIGITS = re.compile(r"\d+")
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Canonicalize an outcome so the SAME failure/rejection fingerprints identically
    despite run-to-run noise: lowercase, drop digits (timings, counts, line numbers,
    temp-dir suffixes), collapse whitespace."""
    return _WS.sub(" ", _DIGITS.sub("", text.lower())).strip()


def fingerprint(kind: str, text: str) -> str:
    """A stable fingerprint of an attempt's outcome. ``kind`` (e.g. "test"/"gate")
    keeps the two loops' signals from colliding."""
    return hashlib.sha256(f"{kind}\x00{normalize(text)}".encode()).hexdigest()


def bump_stall(prev_fp: str, curr_fp: str, count: int, limit: int) -> tuple[int, bool]:
    """Fold one outcome into the stall counter. An outcome identical to the previous
    one increments the streak; a different one resets it. Trips once ``limit``
    identical outcomes have been seen (limit<=1 disables tripping)."""
    streak = count + 1 if curr_fp and curr_fp == prev_fp else 0
    stalled = limit > 1 and streak >= limit - 1
    return streak, stalled


_FAIL_COUNT = re.compile(r"(\d+)\s+(failed|error)", re.IGNORECASE)


def parse_failing_count(test_output: str) -> int | None:
    """The number of FAILED + ERROR tests from a pytest summary line (``=== 3 failed, 5 passed
    …``), or ``None`` if no such count is present (a non-pytest validator, or unparseable). Used
    for the coder's convergence signal (#55) and the progress-based no-convergence breaker (#56).
    The fingerprint deliberately STRIPS digits, so this is the one place counts are read back."""
    total = 0
    seen = False
    for n, _kind in _FAIL_COUNT.findall(test_output):
        total += int(n)
        seen = True
    return total if seen else None


def bump_progress(best: int | None, streak: int, now: int, limit: int) -> tuple[int, int, bool]:
    """Fold one failing-count into the progress tracker (the honest-stop breaker, #56 ADR-0060).

    BEST-SO-FAR semantics, not prev-vs-now: an attempt only counts as progress when it beats the
    best count ever seen this episode, so an oscillating coder (5 → 6 → 5) is correctly a
    non-converging streak — the two-value #55 window can't see that. Returns
    ``(new_best, new_streak, tripped)``; trips once ``limit`` consecutive non-improving attempts
    have been seen (exact ``bump_stall`` off-by-one semantics: ``limit <= 1`` disables tripping),
    so ``stall_limit`` is the shared K and the sensitivity dial scales both breakers together."""
    if best is None or now < best:
        return now, 0, False
    streak += 1
    return best, streak, limit > 1 and streak >= limit - 1


def wont_converge(history: list[int], remaining: int, min_history: int = 3) -> bool:
    """Projected non-convergence for the honest-stop (#65): a run making REAL but too-slow progress
    that will NOT reach 0 failing within ``remaining`` fix attempts, so it should conclude early
    (an honest_park) instead of grinding to the iteration cap (a thrash_park). This is the gap
    ``bump_progress`` misses — it resets its streak on ANY improvement, so 12→10→8→6→… never trips.

    CONSERVATIVE by construction (it must never kill a run that would converge): it projects at the
    AVERAGE improvement rate achieved so far, which is OPTIMISTIC because the tail of convergence
    almost always DECELERATES (the last failing tests are the hardest). If even that optimistic
    projection can't reach 0 in the remaining attempts, the run genuinely isn't on track. Requires
    ``min_history`` points to estimate a rate; a stagnant/oscillating run (no net progress) is left
    to the streak breaker, so this only ever ADDS trips for the slow-non-convergence case."""
    if len(history) < min_history or remaining <= 0:
        return False
    first, current = history[0], history[-1]
    if current <= 0:
        return False  # already converged / about to
    improvement = first - current
    if improvement <= 0:
        return False  # no net progress → the streak breaker's job, not this one
    avg_rate = improvement / (len(history) - 1)  # optimistic (tail decelerates)
    return current / avg_rate > remaining


_FAILED_TEST = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.MULTILINE)


def parse_failing_tests(test_output: str, cap: int = 5) -> list[str]:
    """The failing test node-ids from pytest's short summary (``FAILED path::name``), capped and
    de-duplicated in order. The honest-stop's deterministic diagnosis: which tests trap the coder
    — strictly better data than the LLM park-note it replaced (#56), at zero model cost."""
    out: list[str] = []
    for m in _FAILED_TEST.finditer(test_output):
        node_id = m.group(1).rstrip(":").strip()
        if node_id and node_id not in out:
            out.append(node_id)
        if len(out) >= cap:
            break
    return out


def first_error_lines(text: str, cap: int = 2) -> str:
    """A short, concrete signature of an UNCOUNTABLE failure (#81).

    The count path's give-up reason names a trend ("failing count 12 → 12 → 12"). The no-count path
    has no trend, so it names the failure itself instead — otherwise the human gets an anonymous
    "failed the same way 3 times" with no clue what the way WAS. Takes the last non-empty lines,
    which is where psql/tsc/a shell script put the actual error, and keeps digits (unlike
    ``fingerprint``) because the specifics are the whole point.
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return "no output"
    return " / ".join(lines[-cap:])[:160]


def generic_test_report(test_output: str) -> TestReport | None:
    """The pytest-shaped fallback interpretation, as a ``TestReport`` (#81).

    Composed from ``parse_failing_count`` + ``parse_failing_tests`` WITHOUT touching either, so a
    pack that routes here is byte-for-byte equivalent to the pre-#81 behaviour. Used by
    ``PythonPack`` (where the shape is native), by any pack that meets an unrecognised runner, and
    by the operator's ``--test-cmd`` plan, which by definition has no pack to interpret it.

    Returns ``None`` when nothing countable is present — the honest "this validator does not report
    a count" answer, which is what #81's no-signal path exists to handle.
    """
    count = parse_failing_count(test_output)
    if count is None:
        return None
    # parse_failing_count already SUMS failed+errors, so the split is not recoverable here; report
    # it all as `failed` and leave `errors` 0. `.failing` is the number the breakers consume, and
    # it is identical either way.
    return TestReport(failed=count, failing_ids=tuple(parse_failing_tests(test_output)))


# A coder that cannot proceed is instructed (repo.py _STUCK_HINT) to yield a
# 'SUMMARY: blocked — …' (it hit a wall it can't pass) or 'SUMMARY: escalate — …'
# (it needs a decision / scope change). This finally PARSES that convention so a
# yield can change routing instead of being buried in free-text.
_YIELD = re.compile(
    r"^\s*SUMMARY:\s*(blocked|escalate)\s*[—:-]+\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def parse_yield(summary: str) -> tuple[str, str]:
    """Extract a coder's structured hand-raise from its final SUMMARY.

    Returns ``(blocked_reason, escalate_reason)``; each is ``""`` when its marker
    is absent. The first occurrence of each kind wins. Pure and deterministic.
    """
    blocked = escalate = ""
    for kind, reason in _YIELD.findall(summary):
        reason = reason.strip()
        if kind.lower() == "blocked" and not blocked:
            blocked = reason
        elif kind.lower() == "escalate" and not escalate:
            escalate = reason
    return blocked, escalate


def stall_message(reason: str, coder_summary: str) -> str:
    """The honest capability-limit note surfaced at the gate / in the report."""
    msg = (
        f"Stopped — no progress: {reason}. "
        "This task appears beyond what I can complete automatically."
    )
    summary = coder_summary.strip()
    if summary:
        msg += f"\n\nForge's last report:\n{summary}"
    return msg
