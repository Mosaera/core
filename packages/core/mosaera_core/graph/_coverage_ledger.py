"""Best-effort persistence of a run's covered regions to the durable per-project ledger (#29 P3).

Extracted from ``nodes_impl`` (which owns the test-loop nodes) so that hot file stays under the
god-file ceiling. Called only by ``test_node`` after it pays for one instrumented coverage run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mosaera_core.graph.context import RunContext
from mosaera_core.testintegrity import is_test_file

if TYPE_CHECKING:
    from mosaera_core.coveragemap import CoverageMap


def persist_coverage_ledger(ctx: RunContext, cmap: CoverageMap) -> None:
    """Persist the coverage map's covered regions to the durable PER-PROJECT ledger (#29 P3), so
    coverage COMPOUNDS across runs (enables impact-based test selection + rot detection). Uses the
    P1→P2 adapter (line map → `file::qualname` regions + nodeid-normalized tests). Best-effort and
    deny-by-default: no store, no project (a headless CLI run), or an unreadable source → skip
    silently — the ledger just doesn't gain this run's data, and the gate is entirely unaffected.
    ALL of it (incl. the DB calls) is wrapped: a transient DB fault must never crash a GREEN run
    into status='error' + discard the diff (holistic red-team B-1) — mirrors the runner's `_safe`
    discipline. The coverage VERDICT is computed before this and is untouched by a skip."""
    memory = ctx.memory
    if memory is None:
        return
    try:
        run = memory.get_run(ctx.run_id)
        project_id = getattr(run, "project_id", None) if run is not None else None
        if not project_id:
            return
        from mosaera_core.coverage_regions import regions_from_coverage

        sources: dict[str, str] = {}
        for f in cmap.covered_lines:
            if is_test_file(f):
                continue
            path = ctx.workspace.root / f
            if path.is_file():
                try:
                    sources[f] = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue  # unreadable / binary — skip, don't guess its source
        for region in regions_from_coverage(cmap, sources, is_test_file):
            memory.upsert_coverage_region(
                project_id,
                region.region_key,
                region_fingerprint=region.region_fingerprint,
                source_hash=region.source_hash,
                covering_tests=region.covering_tests,
            )
    except Exception as exc:
        # Best-effort side-record: a DB/adapter fault must never crash a green run. The gate verdict
        # (already computed) is untouched; the ledger just skips this run's data.
        print(f"  WARNING: coverage-ledger persist skipped ({type(exc).__name__}).")
