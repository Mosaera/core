"""Preserve the delivered work product before measurement destroys it.

Split from `bench/cli.py` at the god-file ceiling. `overstrict_vs_reference` overlays the case
reference solution onto the workspace and the coder's writes are not always staged — so without
this, an unstaged delivery is unrecoverable the moment it is measured (found on MCB-05's false
ships, which could not be diagnosed for exactly that reason).
"""

from __future__ import annotations

import contextlib

from mosaera_core.bench.harness import RunOutcome
from mosaera_core.config import Settings

# A delivered diff is unbounded; the store is not. 512 KiB holds every MCB diff many times over.
_MAX_PATCH_BYTES = 512 * 1024


def _save_delivered_patch(run: RunOutcome, settings: Settings, case_id: str, stamp: str) -> None:
    """Write the delivered diff beside the scorecard, before the reference overlays the tree.

    Best-effort and never raises: losing the patch must not cost the run its scorecard. Bounded
    so a runaway diff cannot fill the store."""
    if run.workspace is None:
        return
    with contextlib.suppress(Exception):
        diff = run.workspace.diff_all()
        if not diff:
            return
        out = settings.home / "benchmarks" / case_id / f"{stamp}.patch"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(diff[:_MAX_PATCH_BYTES], encoding="utf-8")
