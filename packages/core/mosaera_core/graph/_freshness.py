"""Does this evidence describe the tree we are about to ship? (ADR-0108 + successor)

`RunState` is last-write-wins and nothing clears an evidence channel on a re-plan, so a verdict
outlives the tree it measured. ADR-0106 closed that for `tests_passed`; ADR-0107's `scan_attempted`
closed the ABSENT case. This closes the STALE case, and the two are different questions: absent
merely suppressed the operator's question, stale delivered.

One origin, two writers, one comparison seam — the writer stamps its own tree hash beside its own
verdict, and exactly one reader compares.

WHAT "THE TREE" MEANS, and the mistake worth not repeating. The first cut asked `file_listing`, a
PRESENTATION helper. Two red-team rounds then found five separate defect classes, all downstream of
that one choice — blind past 300 paths, blind to `_SKIP_DIRS` at any depth, an empty listing hashing
to `sha256("")`, an operator sentence that could not distinguish *moved* from *never stamped*, and
fixtures built in the pin's own model so nothing caught any of it. Round 2 reproduced the original
CRITICAL straight through the fix with the coder's ordinary `write_file`. The STOP rule fired; the
successor replaced the SOURCE rather than patching a sixth instance. `evidence_hash` mirrors
`_stage_all` — git's view, the same source of truth as delivery — so "the tree the evidence
describes" and "the tree that ships" are one origin by construction.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def live_tree(ctx: Any) -> str:
    """The fingerprint of what would ship right now, or ``""`` when there is none.

    Thin on purpose: `evidence_hash` owns the definition and the fail-closed contract, so there is
    one place to read and one place to change. The `try` is belt-and-braces — `evidence_hash`
    already returns `""` rather than raising.
    """
    try:
        return str(ctx.workspace.evidence_hash())
    except Exception:
        return ""


def is_fresh(ctx: Any, state: Mapping[str, Any], key: str) -> bool:
    """Whether the evidence stamped under ``key`` describes the CURRENT tree.

    FAILS CLOSED. A missing stamp, an empty stamp, or an unreadable workspace is NOT fresh — an
    unreadable tree costs a park rather than granting a pass, which is the direction ADR-0076
    requires and the direction `pinned_coder_validation` already takes.

    Stat-only `(path, size, mtime_ns)`: a same-size write with a RESTORED mtime is invisible.
    Verified reachable by red team, but only with a capability no role has — no allowlist carries a
    shell or `utime`, `sandbox_exec` mounts the workspace read-only, and install/test run BEFORE
    `scan`, so the dangerous give-up edge offers no execution window at all. Hostile-repo-only, and
    strictly weaker than what a content hash would cost on the hot path. Recorded, not closed.
    """
    stamped = str(state.get(key) or "")
    live = live_tree(ctx)
    return bool(stamped) and bool(live) and stamped == live
