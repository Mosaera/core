"""Measure Proctor over-strictness for a benchmark run (#57, ADR-0062).

Two signals, both fed into the scorecard meta so a re-baseline can quantify the fix:

- **static** — how many authored acceptance assertions the deterministic detector
  (`mosaera_core.faithfulness`) flags as pinning incidental detail the spec leaves open. Cheap, no
  sandbox run; available for every case.
- **vs-reference (ground truth)** — how many of the run's *own authored tests* FAIL when run against
  the case's known-good ``reference/`` solution. The reference is correct by construction, so any
  authored test it fails is *provably* over-strict/unfaithful (it would reject a correct
  implementation). This is the honest lever the arc is measured on; ``None`` when the case ships no
  reference (greenfield MCB-01/02) or the check can't run.
"""

from __future__ import annotations

import re
import shutil
import sys

from mosaera_core.bench.cases import BenchCase
from mosaera_core.bench.harness import RunOutcome
from mosaera_core.config import Settings
from mosaera_core.faithfulness import authored_suite_overstrict_findings
from mosaera_core.sandbox import create_sandbox
from mosaera_core.validation import resolve_plan, run_plan

_FAILED = re.compile(r"(\d+) failed")
# The DENOMINATOR. `overstrict_vs_reference` returns a COUNT, and a model that authors more
# tests has more chances to be over-strict — so a count alone cannot separate "wrote worse
# tests" from "wrote more tests". That ambiguity decided the 2026-08-11 tester-model
# experiment: MCB-22 read +204% and remains uninterpretable because nothing recorded how many
# tests were authored.
_PASSED = re.compile(r"(\d+) passed")


def overstrict_static_count(run: RunOutcome, case: BenchCase) -> int:
    """Over-strict findings the deterministic detector raises on the run's authored suite."""
    authored = run.final.get("authored_tests") or []
    if run.workspace is None or not authored:
        return 0
    return len(authored_suite_overstrict_findings(run.workspace, authored, case.brief))


# One origin, defined by the WRITER. `layer2.assert_judgeable` imports it — a second copy of this
# string is how the marker and the check would silently stop referring to the same file.
POISON_SENTINEL = "_MCB_POISONED"


def overstrict_total(output: str) -> int | None:
    """Total authored tests that RAN against the reference — the denominator for the count
    `overstrict_vs_reference` returns. ``None`` when pytest reported neither tally."""
    failed = _FAILED.search(output)
    passed = _PASSED.search(output)
    if not failed and not passed:
        return None
    return int(failed.group(1) if failed else 0) + int(passed.group(1) if passed else 0)


def overstrict_vs_reference(
    run: RunOutcome, case: BenchCase, settings: Settings, backend: str
) -> tuple[int | None, int | None]:
    """Count authored tests that FAIL against the case's ``reference/`` solution (= provably
    over-strict). ``None`` when unmeasurable (no reference, no authored tests, or unrunnable).

    Runs LAST in ``_run_once`` -- it overlays the reference source onto the (already-graded) run
    workspace and re-runs the authored tests, so it DESTROYS the delivered code and leaves the
    correct answer in its place.

    That used to be justified as "fine, the workspace is discarded immediately after". **That was
    false** (measured 2026-08-09: 1,941 workspaces on disk, none discarded), and the real safety
    was worse than the excuse: it rested purely on this running at line 178 of a dict literal while
    the Layer-2 attempt runs at line 150. Layer 2 avoided judging reference code by luck of
    placement. Anything added after this point reads a tree in which the agent appears to have
    written a flawless solution.

    So the tree is now marked POISONED, and `layer2.assert_judgeable` refuses it. A sentinel
    survives a reordering; a comment does not.
    """
    authored = run.final.get("authored_tests") or []
    if run.workspace is None or not authored or not case.reference_dir.is_dir():
        return None, None
    # Overlay the correct reference implementation over the delivered code (same relative paths).
    for src in case.reference_dir.rglob("*"):
        if src.is_file():
            dest = run.workspace.root / src.relative_to(case.reference_dir)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    # Declare the tree poisoned BEFORE running anything, so a crash mid-measurement still leaves
    # the marker. Deny-by-default: the window where the answer is present but unlabelled is zero.
    (run.workspace.root / POISON_SENTINEL).write_text(
        "The case `reference/` solution was overlaid over the delivered code by "
        "`overstrict_vs_reference`. This tree is NOT the agent's work product and must never be "
        "judged, graded, converted or mutated.\n",
        encoding="utf-8",
    )
    sandbox = create_sandbox(
        backend,
        run.workspace.root,
        image=settings.sandbox_image,
        docker_bin=settings.docker_bin,
        default_timeout=settings.sandbox_timeout,
    )
    plan = resolve_plan(
        run.workspace,
        [sys.executable, "-m", "pytest", "-q", "--tb=no", "-p", "no:cacheprovider", *authored],
        install=False,
    )
    outcome = run_plan(plan, sandbox, cwd=run.workspace.root)
    if outcome.passed is None:
        return None, None
    total = overstrict_total(outcome.output)
    if outcome.passed is True:
        return 0, total
    m = _FAILED.search(outcome.output)
    return (int(m.group(1)) if m else None), total
