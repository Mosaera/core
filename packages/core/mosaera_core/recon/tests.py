"""The ``tests`` dimension — reuse #29's coverage map (ADR-0047 §3).

ADR-0047 names this the map's most valuable dimension and gates it on the coverage arc
(`#29`), which has since merged. So this module measures rather than guesses: it runs
the suite under coverage **in the sandbox** and reports real line coverage, not a
count of files named ``test_*``.

The coverage arc is also the *good* precedent for honesty, and this dimension inherits
it directly. ``run_coverage`` returns ``None`` when it could not measure — the suite
failed, the datafile never appeared, the sandbox image lacks ``coverage`` (which is
the case today, pending the CODEOWNERS Dockerfile MR). Every one of those is
``unavailable``. A project whose suite does not run is not a project with clean tests,
and the map must not say so.
"""

from __future__ import annotations

from mosaera_core.coveragemap import CoverageMap, run_coverage
from mosaera_core.sandbox import SandboxWorker
from mosaera_core.testintegrity import is_test_file
from mosaera_core.tools.repo import Workspace

from . import _fingerprint, _fs
from .types import DimensionResult, Observation

DIMENSION = "tests"

_MAX_REPORTED = 10

# The coverage verdict is produced by RUNNING the suite, so its inputs are not just the
# `*.py` files: the test-runner + coverage config decide WHICH tests run and WHICH lines
# count, and the lockfiles pin the dependency set the suite runs against. A `.coveragerc`
# `omit =` or a `pytest.ini` `testpaths` edit changes the measured number while touching
# no `.py`, so leaving them out of the key serves a stale coverage number as fresh
# (under-invalidation — the dangerous direction; red-team #41).
_COVERAGE_INPUTS = (
    "pytest.ini",
    "tox.ini",
    "setup.cfg",
    "pyproject.toml",
    ".coveragerc",
    "uv.lock",
    "poetry.lock",
    "Pipfile.lock",
    "requirements.txt",
)


def _coverage_percent(cmap: CoverageMap) -> tuple[int, int]:
    """``(covered, executable)`` line totals across non-test sources."""
    covered = 0
    executable = 0
    for path, lines in cmap.executable_lines.items():
        if is_test_file(path):
            continue
        executable += len(lines)
        covered += len(lines & cmap.covered_lines.get(path, set()))
    return covered, executable


def recon_tests(workspace: Workspace, sandbox: SandboxWorker | None) -> DimensionResult:
    """Observe the project's real test coverage."""
    root = workspace.root
    python_files = [f for f in _fs.walk(root).files if f.endswith(".py")]
    config_inputs = [c for c in _COVERAGE_INPUTS if _fs.exists(root, c)]
    fingerprint = _fingerprint.fingerprint_files(root, [*python_files, *config_inputs])

    test_files = [f for f in python_files if is_test_file(f)]
    if not python_files:
        return DimensionResult.finding(
            DIMENSION,
            fingerprint,
            [Observation(text="no Python sources to test", provenance="tool:walk")],
        )

    if sandbox is None:
        return DimensionResult.could_not_run(
            DIMENSION,
            fingerprint,
            ["no sandbox — coverage must be measured by running the suite"],
            [
                Observation(
                    text=f"{len(test_files)} test file(s) present (not executed)",
                    provenance="tool:walk",
                )
            ],
        )

    cmap = run_coverage(workspace, sandbox)
    if cmap is None:
        # Unmeasured. NOT "no coverage" and emphatically not "clean" — we do not know.
        return DimensionResult.could_not_run(
            DIMENSION,
            fingerprint,
            ["coverage could not be measured (suite failed, or the sandbox lacks coverage.py)"],
            [Observation(text=f"{len(test_files)} test file(s) present", provenance="tool:walk")],
        )

    covered, executable = _coverage_percent(cmap)
    if executable == 0:
        return DimensionResult.could_not_run(
            DIMENSION, fingerprint, ["coverage ran but measured no executable source lines"]
        )

    percent = round(100 * covered / executable)
    observations = [
        Observation(
            text=f"line coverage is {percent}% ({covered}/{executable} executable lines)",
            provenance="tool:coverage",
        ),
        Observation(
            text=f"{len(cmap.lines_by_test)} test(s) executed "
            f"across {len(test_files)} test file(s)",
            provenance="tool:coverage",
        ),
    ]

    uncovered_files = sorted(
        path
        for path, lines in cmap.executable_lines.items()
        if not is_test_file(path) and not (lines & cmap.covered_lines.get(path, set()))
    )
    if uncovered_files:
        observations.append(
            Observation(
                text=f"{len(uncovered_files)} source file(s) have no coverage at all: "
                f"{', '.join(uncovered_files[:_MAX_REPORTED])}",
                provenance="tool:coverage",
                severity="medium",
            )
        )

    return DimensionResult.finding(DIMENSION, fingerprint, observations)
