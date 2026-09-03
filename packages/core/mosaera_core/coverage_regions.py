"""Adapt P1's line-level ``CoverageMap`` into P2's region-level ledger rows (#29 P3).

P1 (``coveragemap.CoverageMap``) produces a LINE→test map from one instrumented run; P2
(``mosaera_memory`` coverage ledger) stores a REGION→test map keyed ``file::qualname`` with
churn-stable fingerprints. This module is the adapter between them — the integration seam both arcs
deliberately left for P3 (see the review notes on issue #35):

- bucket each measured source file's covered lines into REGIONS (the enclosing function, via AST),
- normalize coverage's ``dynamic_context = test_function`` labels (dotted ``module.qualname``) into
  pytest NODEIDs (``path/to/test.py::qualname``) so impact-selection can actually re-run the tests.

Pure + I/O-free given the file sources: the caller reads the workspace and passes sources in, so
this stays unit-testable. Region identity + fingerprints reuse ``mosaera_memory._fingerprint`` — the
single source of truth for the region contract; do NOT re-implement them here (that is how the two
arcs would diverge, per the ADR-0049 cross-arc note).
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from mosaera_memory import _fingerprint as fp

from mosaera_core.coveragemap import CoverageMap


@dataclass(frozen=True)
class Region:
    """One ``(file, qualname)`` unit — a function/method, its 1-based line span, and its source."""

    file: str
    qualname: str
    start: int
    end: int
    source: str


@dataclass(frozen=True)
class LedgerRegion:
    """A covered region ready for ``CoverageMixin.upsert_coverage_region`` — identity + fingerprints
    + the nodeid-normalized tests that exercised it."""

    region_key: str
    region_fingerprint: str
    source_hash: str
    covering_tests: list[str]
    file: str
    qualname: str


def extract_regions(file: str, source: str) -> list[Region]:
    """Every function/method in ``source`` as a ``Region``, with its full source span. Module-level
    code outside any function is not a region (its coverage is import-time, not test-attributed).
    ``qualname`` carries the enclosing class/function path (``Cls.method``, ``outer.inner``); the
    span includes any decorators. Returns ``[]`` on a syntax error (nothing to attribute)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines = source.splitlines()
    out: list[Region] = []

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                qual = f"{prefix}{child.name}"
                start = child.lineno
                if child.decorator_list:  # decorators belong to the region's source
                    start = min(start, min(d.lineno for d in child.decorator_list))
                end = child.end_lineno or child.lineno
                out.append(
                    Region(
                        file=file,
                        qualname=qual,
                        start=start,
                        end=end,
                        source="\n".join(lines[start - 1 : end]),
                    )
                )
                walk(child, f"{qual}.")  # nested functions get a dotted qualname
            elif isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")

    walk(tree, "")
    return out


def _line_to_region(regions: list[Region]) -> dict[int, Region]:
    """Map each line in any region's span to its INNERMOST enclosing region. Applying larger spans
    first and smaller (nested) spans last means the innermost function wins an overlapping line."""
    by_line: dict[int, Region] = {}
    for r in sorted(regions, key=lambda r: r.end - r.start, reverse=True):
        for ln in range(r.start, r.end + 1):
            by_line[ln] = r
    return by_line


def _context_nodeids(cmap: CoverageMap, is_test: Callable[[str], bool]) -> dict[str, str]:
    """Map each coverage test-context label (dotted ``module.qualname``) to a pytest nodeid.

    The test FILE is recovered unambiguously from ``lines_by_test`` (a context also covers its own
    test file's lines), which sidesteps the label's lossy module prefix (the directory is dropped
    when the test dir is not a package). The qualname tail is the label with everything up to and
    including the file stem removed, ``.`` → ``::`` for class methods. A context whose test file is
    ambiguous or unfindable is skipped (its coverage still counts; only its nodeid is unknown)."""
    out: dict[str, str] = {}
    for label, keys in cmap.lines_by_test.items():
        if not label:
            continue  # import-time (empty) context — not a test
        test_files = {f for (f, _ln) in keys if is_test(f)}
        if len(test_files) != 1:
            continue
        testfile = next(iter(test_files))
        stem = Path(testfile).stem
        parts = label.split(".")
        if stem not in parts:
            continue
        tail = parts[parts.index(stem) + 1 :]
        if not tail:
            continue
        out[label] = f"{testfile}::{'::'.join(tail)}"
    return out


def regions_from_coverage(
    cmap: CoverageMap,
    file_sources: dict[str, str],
    is_test: Callable[[str], bool],
) -> list[LedgerRegion]:
    """Turn a ``CoverageMap`` into ledger-ready rows for the NON-test source files.

    For every source region with at least one covered line, emit its ``region_key`` /
    ``source_hash`` / ``region_fingerprint`` and the nodeid-normalized union of tests that executed
    any of its lines. A region no test covers is omitted (it is not 'verified' — the ledger stays
    deny-by-default). ``file_sources`` maps a repo-relative source path to its full current text; a
    covered file absent from it (unreadable) is skipped rather than guessed."""
    context_nodeid = _context_nodeids(cmap, is_test)
    out: list[LedgerRegion] = []
    for file, covered in cmap.covered_lines.items():
        if is_test(file) or file not in file_sources:
            continue
        line_region = _line_to_region(extract_regions(file, file_sources[file]))
        tests_by_region: dict[str, set[str]] = {}
        region_by_qual: dict[str, Region] = {}
        for ln in covered:
            region = line_region.get(ln)
            if region is None:
                continue  # module-level line — not a function region
            region_by_qual[region.qualname] = region
            ctxs = cmap.tests_by_line.get((file, ln), set())
            nodeids = {context_nodeid[c] for c in ctxs if c in context_nodeid}
            tests_by_region.setdefault(region.qualname, set()).update(nodeids)
        for qual, region in region_by_qual.items():
            out.append(
                LedgerRegion(
                    region_key=fp.region_key(file, qual),
                    region_fingerprint=fp.region_fingerprint(region.source),
                    source_hash=fp.source_hash(region.source),
                    covering_tests=sorted(tests_by_region.get(qual, set())),
                    file=file,
                    qualname=qual,
                )
            )
    return out
