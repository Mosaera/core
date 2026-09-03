"""Per-test red-verify: WHICH authored tests fail against the pre-implementation seed.

Split from `oraclecheck` at the god-file ceiling. One cohesive question (P2 Stage A): the seed is
the reference for every behaviour the task does not change, so a seed failure on such a test is
provably over-strict with no hidden grader — `authored_overstrict` does that split downstream.
"""

from __future__ import annotations

import re
import sys
from typing import TYPE_CHECKING

from mosaera_core.validation import resolve_plan, run_plan

if TYPE_CHECKING:
    from mosaera_core.sandbox import SandboxWorker
    from mosaera_core.tools.repo import Workspace

# Failing test ids from pytest's short summary ("FAILED path::name - ..."). Deliberately the
# same shape as `bench/grade._FAILED_ID`, and deliberately NOT imported from there: `bench` is
# the measurement layer and the engine must not depend on it. Kept in sync by the shared test.
_SEED_FAILED_ID = re.compile(r"(?:FAILED|ERROR)(?::\s+|\s+)(?:collecting\s+)?(\S+)")
# ANSI escapes are stripped BEFORE matching: a colourised pytest ("\x1b[31mFAILED\x1b[0m …")
# puts an escape between FAILED and the node id, and the vacancy contract then honestly
# returned None for a run that plainly named its failures — correct, but blind. Found by the
# offline replay, where the pin did exactly its job before this fix existed.
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def seed_failures_from_output(output: str) -> list[str] | None:
    """Failing node ids from a pytest run's output, or ``None`` when nothing parseable.

    ``None`` and ``[]`` are DIFFERENT evidence and must stay so (P2 Stage A): ``[]`` means the
    run parsed and named no failures; ``None`` means we could not read it — collapsing them is
    the absence-read-as-fact class this branch keeps finding. A green run's output carries no
    FAILED lines, so callers must gate ``[]`` on the run having genuinely passed.
    """
    if not output or not output.strip():
        return None
    output = _ANSI.sub("", output)
    ids = _SEED_FAILED_ID.findall(output)
    if ids:
        return sorted(set(ids))
    # No FAILED lines: only a run that says it PASSED (or collected nothing to fail) earns [].
    if re.search(r"\b\d+ passed\b", output) or "no tests ran" in output:
        return []
    return None


def authored_seed_results(
    workspace: Workspace, sandbox: SandboxWorker, authored: list[str]
) -> tuple[bool | None, list[str] | None]:
    """(is_red, seed_failures) for the authored suite against the PRE-implementation tree.

    One pytest run answers two questions that were previously collapsed into one boolean:
    whether the suite is red at all (the ADR-0013 red-verify), and WHICH authored tests fail
    against the seed. The second is P2's raw signal: for a test that exercises only behaviour
    the task does not change, the current code IS the reference — a seed failure there is
    provably over-strict, no hidden grader needed (`authored_overstrict` does that split).

    - ``(True, [ids...])`` — red, with the failing tests named when parseable.
    - ``(False, [])``      — green-without-code (tautological suite).
    - ``(None, None)``     — could not be assessed.

    Same one-sided contract as before: only ever REJECTS a suite proven green-without-code.
    """
    if not authored:
        return None, None
    # Scope to the authored tests only, network-off: pytest is in the sandbox image, and a custom
    # test_cmd plan is a single network-off step (ValidationStep.network defaults to False).
    plan = resolve_plan(workspace, [sys.executable, "-m", "pytest", "-q", *authored], install=False)
    outcome = run_plan(plan, sandbox, cwd=workspace.root)
    if outcome.passed is None:
        return None, None
    return not outcome.passed, seed_failures_from_output(outcome.output or "")
