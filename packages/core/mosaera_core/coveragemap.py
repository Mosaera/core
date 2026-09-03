"""Runtime coverage → a two-way code↔test map (oracle-make-real arc, #29, P0).

The durable replacement for the coarse static import heuristic (ADR-0044 Phase 2b): instead of
*guessing* whether a test references the changed code, RUN the suite under coverage and see which
changed lines actually executed **under a test**. This module is the primitive — the pure parsing
and mapping (unit-tested here) plus the sandbox orchestration (`run_coverage`, integration-tested
once the sandbox image carries `coverage`, the infra prerequisite).

Later phases build on this: P1 wires the change-coverage gate (credit only covered changed lines);
P2 persists the map as a durable test ledger; P3 authors deltas only for the uncovered lines.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from mosaera_core.validation import resolve_plan, run_plan

if TYPE_CHECKING:
    from coverage import CoverageData

    from mosaera_core.sandbox import SandboxWorker
    from mosaera_core.tools.repo import Workspace


@dataclass
class CoverageMap:
    """The two-way map from one instrumented run.

    - ``covered_lines[file]`` — executable lines that ran **under a test** (a non-empty coverage
      context; lines run only at import time don't count as tested).
    - ``tests_by_line[(file, line)]`` — the test contexts that hit that line.
    - ``lines_by_test[test]`` — the lines a given test hit (the basis for impact-based selection).
    - ``executable_lines[file]`` — all executable lines coverage identified (from source analysis),
      so a caller can tell an UNCOVERED-executable changed line from a non-executable one (comment,
      blank). Empty when analysis wasn't run (pure-parse path).
    """

    covered_lines: dict[str, set[int]] = field(default_factory=dict)
    tests_by_line: dict[tuple[str, int], set[str]] = field(default_factory=dict)
    lines_by_test: dict[str, set[tuple[str, int]]] = field(default_factory=dict)
    # Import-time (module/class scope) lines per file — structurally uncoverable under
    # `dynamic_context = test_function`. Filled by `run_coverage` from source, like
    # `executable_lines`. Empty means UNKNOWN, and the caller then judges every line.
    import_time_lines: dict[str, set[int]] = field(default_factory=dict)
    executable_lines: dict[str, set[int]] = field(default_factory=dict)


_FILE = re.compile(r"^\+\+\+ b/(.+)$")
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def changed_lines(diff: str) -> dict[str, set[int]]:
    """Added-side line numbers per file from a unified diff — the lines a change introduced/edited.
    Deletions contribute no new-side line (they don't advance the new counter). The caller filters
    vendored/test paths; this is the raw hunk math."""
    out: dict[str, set[int]] = {}
    cur: str | None = None
    newno = 0
    for line in diff.splitlines():
        m = _FILE.match(line)
        if m:
            cur = m.group(1)
            out.setdefault(cur, set())
            continue
        h = _HUNK.match(line)
        if h:
            newno = int(h.group(1))
            continue
        # Skip the no-newline marker + the ONE file-header form that reaches here: `+++ /dev/null`
        # (new side of a deletion). `+++ b/…` was already consumed by _FILE above; old-side `--- …`
        # headers fall through the `-` branch harmlessly (headers never add a new-side line). Match
        # `+++ /dev/null` EXACTLY — not any `+++`/`+++ ` prefix — so an added CONTENT line like
        # `++ danger()` (diff line `+++ danger()`, WITH a space) stays content instead of being
        # dropped + mis-numbering the rest of the hunk (finding A3, both no-space + space forms).
        if cur is None or line.startswith("\\") or line == "+++ /dev/null":
            continue
        if line.startswith("+"):
            out[cur].add(newno)
            newno += 1
        elif line.startswith(" "):
            newno += 1  # a context line advances the new-side counter
        # a "-" line (removed content OR an old-side `--- …` header) has no new-side number → ignore
    return {f: ls for f, ls in out.items() if ls}


def _rel(path: str, root: Path) -> str:
    """Normalize a measured-file path to a POSIX repo-relative key. With ``relative_files=true`` in
    the coverage config the paths are already relative; this just normalizes separators and strips
    an accidental absolute/root prefix."""
    p = path.replace("\\", "/")
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return p.lstrip("./")


def parse_contexts(data: CoverageData, root: Path) -> CoverageMap:
    """Build the ``CoverageMap`` from a loaded ``CoverageData`` — the per-line test contexts. Only
    NON-EMPTY contexts count (a line covered only at import time is not 'tested'). The
    ``executable_lines`` map is left empty here; ``run_coverage`` fills it from source analysis."""
    m = CoverageMap()
    for f in data.measured_files():
        rel = _rel(f, root)
        for lineno, ctxs in data.contexts_by_lineno(f).items():
            tests = {c for c in ctxs if c}
            if not tests:
                continue
            m.covered_lines.setdefault(rel, set()).add(lineno)
            key = (rel, lineno)
            m.tests_by_line.setdefault(key, set()).update(tests)
            for t in tests:
                m.lines_by_test.setdefault(t, set()).add(key)
    return m


def covered_uncovered(
    cov: CoverageMap, changed: dict[str, set[int]]
) -> tuple[dict[str, set[int]], dict[str, set[int]]]:
    """Split each file's changed lines into (covered-by-a-test, not-covered). 'Not covered' still
    mixes truly-uncovered-executable lines with non-executable ones (comments/blanks) — the caller
    intersects with ``cov.executable_lines`` when it needs the executable-only uncovered set."""
    covered: dict[str, set[int]] = {}
    uncovered: dict[str, set[int]] = {}
    for f, lines in changed.items():
        cl = cov.covered_lines.get(f, set())
        c, u = lines & cl, lines - cl
        if c:
            covered[f] = c
        if u:
            uncovered[f] = u
    return covered, uncovered


def change_is_covered(cov: CoverageMap, changed_source_lines: dict[str, set[int]]) -> bool | None:
    """The precise change-coverage verdict for the gate (#29, P1): does a test EXECUTE every changed
    source line?

    - ``True``  — every changed ``.py`` file's executable changed lines are covered by a test.
    - ``False`` — some changed ``.py`` file is UNMEASURED (no test runs it — the F1 case coverage
      exists to catch) OR has an executable changed line that ran under no test.
    - ``None``  — no changed ``.py`` source lines to judge (coverage is moot: docs/config-only or a
      no-op change) → the caller falls back to the coarse import heuristic / its inertness check.

    A changed file that no test imports is never measured, so its ``executable_lines`` is absent —
    treated as UNCOVERED, deny-by-default.

    RESIDUAL (ADR-0049 red-team A1): this is *line*-granular. A changed line on an unexecuted branch
    or a short-circuited sub-expression (``x or DANGER()``) can be credited because the enclosing
    statement ran. Line coverage structurally cannot see this; the precise successor is the mutation
    check — pair ``oracle_coverage`` with ``oracle_mutation_check`` for branch-precise crediting.
    """
    py = {f: ls for f, ls in changed_source_lines.items() if f.endswith(".py")}
    if not py:
        return None
    judgeable = 0
    for f, lines in py.items():
        execs = cov.executable_lines.get(f)
        if execs is None:
            return False  # coverage never measured this changed file → no test executes it
        # STRUCTURALLY UNCOVERABLE lines are not evidence of anything (#128). A module-scope
        # statement runs at import, before any `test_function` context exists, so it can never
        # appear in `covered_lines` — counting it as "ran under no test" refuses changes the suite
        # genuinely verifies. Excluded from the must-cover set, NOT credited: see below.
        import_time = cov.import_time_lines.get(f)
        must_cover = (lines & execs) - (import_time or set())
        judgeable += len(must_cover)
        if must_cover - cov.covered_lines.get(f, set()):
            return False  # an executable, coverable changed line ran under no test
    if not judgeable:
        # Every changed line was structurally uncoverable, so coverage has NO opinion here. `None`
        # is the existing "coverage is moot" contract and hands the decision to the caller's import
        # heuristic — which still requires baselined tests that assert something real AND reference
        # the changed module. Deny-by-default is preserved; nothing is credited by this branch.
        return None
    return True


def import_time_lines(source: str) -> set[int] | None:
    """Lines that execute at IMPORT time — outside every function body. ``None`` if unparseable.

    Why this exists (#128). `dynamic_context = test_function` records a context only while a test
    function is running, and `parse_contexts` counts a line as covered ONLY under a non-empty
    context: "a line covered only at import time is not 'tested'". A module-scope statement —
    ``__version__ = "1.5.0"``, ``__all__``, a module-level dict or regex, a decorator line, an
    import, a dataclass field default — runs during import, before any test context exists. It is
    therefore **executable yet structurally uncoverable**: no suite, however thorough, can ever put
    it in ``covered_lines``.

    Measured consequence before this existed: the gate CREDITED a comment change (a comment is not
    executable, so the intersection was empty and the check passed trivially) and REFUSED a
    ``__version__`` bump the standing suite genuinely did verify — reviewer APPROVE, critic 3/3,
    grader 2/2, and the run parked anyway (MCB-30 vs MCB-32, 3 runs each).

    Class BODIES count as import-time too: they execute when the module is imported. Only statements
    inside a function or method body can carry a test context.

    ``None`` is UNKNOWN, never "nothing" — an unparseable file must not be read as having no
    import-time lines, or a syntax error would silently re-enable the defect.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    in_function: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            # The body only — a decorator, the signature and its defaults all run at import time.
            for stmt in node.body:
                for sub in ast.walk(stmt):
                    start = getattr(sub, "lineno", None)
                    if start is None:
                        continue
                    in_function.update(
                        range(start, (getattr(sub, "end_lineno", None) or start) + 1)
                    )
    all_lines = {
        line for node in ast.walk(tree) if (line := getattr(node, "lineno", None)) is not None
    }
    return all_lines - in_function


# --- sandbox orchestration (integration path; needs `coverage` in the sandbox image) ---

# UNIQUE names so we never overwrite/delete a repo's own `.coveragerc` / `.coverage` (finding B2).
# `data_file` points coverage at our file; `relative_files` makes measured paths repo-relative so
# `covered_lines` keys match the diff's `+++ b/<path>`.
_RCFILE = ".mosaera-coveragerc"
_DATAFILE = ".mosaera.coverage"
_COVERAGERC = (
    "[run]\n"
    "dynamic_context = test_function\n"
    "relative_files = true\n"
    "branch = false\n"
    f"data_file = {_DATAFILE}\n"
)


def read_coverage_data(root: Path, datafile: Path) -> CoverageMap:
    """Parse a finished coverage data file into a ``CoverageMap`` — per-test contexts + executable
    lines. ``analysis2`` is given the ABSOLUTE path (``root / rel``): coverage stores paths relative
    (``relative_files``) but resolves ``analysis2`` against the process cwd — which is NOT the
    workspace root — so a relative path yields ``NoSource`` and silently empties
    ``executable_lines`` (finding B1: with it empty, the gate parks every tested change). Split out
    so it is unit-testable without the sandbox."""
    import coverage

    data = coverage.CoverageData(basename=str(datafile))
    data.read()
    cmap = parse_contexts(data, root)
    cov = coverage.Coverage(data_file=str(datafile))
    cov.load()
    for f in data.measured_files():
        try:  # best-effort per file — a non-Python / missing source just skips executable info
            _, executable, _excluded, _missing, _ = cov.analysis2(str(root / f))
        except Exception:  # noqa: S112 — best-effort; a per-file analysis miss just skips it
            continue
        rel = _rel(f, root)
        cmap.executable_lines[rel] = set(executable)
        # Import-time lines, from the SAME source analysis pass (#128). Read from disk rather than
        # inferred from coverage data, because the whole point is lines coverage can never report.
        # Best-effort and silent on failure: an unreadable file leaves the entry absent, which the
        # caller treats as UNKNOWN and judges every line -- the strict, pre-fix behaviour.
        try:
            it = import_time_lines((root / f).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            it = None
        if it is not None:
            cmap.import_time_lines[rel] = it
    return cmap


def run_coverage(workspace: Workspace, sandbox: SandboxWorker) -> CoverageMap | None:
    """Run the suite once under coverage in the sandbox and return the map, or ``None`` if it could
    not be measured. Writes a throwaway (uniquely-named) coverage config, runs ``coverage run -m
    pytest`` network-off under the SAME interpreter the real suite uses, reads the data on the host,
    and fills ``executable_lines`` from source analysis. Always cleans up its own rc + data files
    (never a repo's).

    Requires ``coverage`` in the sandbox image — the separate infra prerequisite (a CODEOWNERS
    Dockerfile MR). Until that image ships this returns ``None`` (no coverage tooling), the safe
    deny-by-default direction for the gate that consumes it.
    """
    import sys

    root = workspace.root
    # Run under the installed venv's python when present — that's where the real suite runs, because
    # the base image lacks the repo's third-party deps (matches languages/python.py); else the
    # sandbox's system python. Using host `sys.executable` (→ container system python) fails imports
    # for deps-bearing repos → a red run (finding B3).
    interp = ".venv/bin/python" if (root / ".venv" / "bin" / "python").exists() else sys.executable
    rc = root / _RCFILE
    datafile = root / _DATAFILE
    rc.write_text(_COVERAGERC, encoding="utf-8")
    try:
        plan = resolve_plan(
            workspace,
            # --ignore=.mosaera prunes the agent scratch space from collection (#59, ADR-0064) — the
            # coverage run shares the whole-tree pytest discovery, so it needs the same guard.
            [
                interp,
                "-m",
                "coverage",
                "run",
                f"--rcfile={_RCFILE}",
                "-m",
                "pytest",
                "-q",
                "--ignore=.mosaera",
            ],
            install=False,
        )
        outcome = run_plan(plan, sandbox, cwd=root)
        # Bail on ANY non-pass (None OR False): a red/broken coverage run (wrong interpreter, import
        # error, collection failure) must NOT be trusted as "measured nothing ⇒ uncovered" — that
        # would false-park a run whose real suite was green (finding B3). Fall back to heuristic.
        if outcome.passed is not True or not datafile.exists():
            return None
        return read_coverage_data(root, datafile)
    except Exception as exc:
        # Best-effort measurement — must never crash a green run. A corrupt / version-skewed
        # `.coverage` (host vs sandbox coverage) or any read/parse fault → UNMEASURED (None), not a
        # propagated crash the runner would record as status='error' + discard a deliverable diff
        # (holistic red-team B-1). None → the gate's heuristic fallback, exactly as when coverage is
        # off — deny-by-default, verdict-preserving.
        print(f"  WARNING: coverage measurement failed ({type(exc).__name__}); unmeasured.")
        return None
    finally:
        rc.unlink(missing_ok=True)
        datafile.unlink(missing_ok=True)
