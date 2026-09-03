#!/usr/bin/env python3
"""Control-liveness guard (ADR-0081) — which rung has each posture knob actually PROVEN?

Prints the registry and FAILS on three things:

1. a knob the autonomous posture flips with NO liveness record at all — the unmeasured-control
   failure the ladder exists to prevent;
2. a **new** posture knob below C4 — the forward ratchet. The knobs already below C4 when the
   ratchet landed are listed in ``GRANDFATHERED`` and reported, not failed: that backlog is the
   point, but it may only ever shrink. Delete a name once its sentinel exists; adding one is a
   deliberate act that shows up in review;
3. an ``evidence`` string that names a test which does not exist. Seven of twelve rows rest on
   prose like "verified by inspection"; those are allowed (they are honest about being prose),
   but a row that *claims* a test must point at a real one, or the record is worse than silence.

Wave 1 was report-only and wired into nothing, so the guard that catches controls-that-cannot-fire
could not itself fire (#58's shape, one level up). **It is now wired** — `make lint` runs
`check-liveness` (Makefile `lint:` prerequisites).

This docstring itself claimed "wired into nothing" for some time AFTER the wiring landed, and was
corrected 2026-08-06 by the doc-claims pass. Noted because it is the exact defect class the guard
family exists to catch, occurring in a guard's own documentation.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "core"))

from mosaera_core.bench.liveness import REGISTRY, registry_by_knob
from mosaera_core.config import Settings, apply_oracle_posture

_ROOT = Path(__file__).resolve().parents[1]

# The six POSTURE knobs already below C4 when the ratchet landed (2026-08-04). This list may
# only SHRINK: each name is a missing sentinel, and removing one means the sentinel now exists.
# A new posture knob below C4 is a failure, not an addition here. Non-posture knobs are not
# governed by this ratchet at all — they do not flip behaviour by default.
GRANDFATHERED: frozenset[str] = frozenset(
    {
        "reason_on_stall_enabled",
        "oracle_coverage",
        "oracle_mutation_check",
        "tester_repairs_tests",
        "proctor_faithfulness_guard",
        "refactor_oracle_scaffold",
    }
)

# "path/to/test_x.py::test_name" or "test_x.py::test_name" — the shape a row uses when it
# claims a test rather than describing prose evidence.
_TEST_REF = re.compile(r"([\w/\\.-]*test_[\w.-]+\.py)::([\w\[\]-]+)")


def _missing_evidence(evidence: str) -> list[str]:
    """Test references in ``evidence`` that name a file or test which does not exist."""
    missing: list[str] = []
    for rel, test in _TEST_REF.findall(evidence):
        name = Path(rel).name
        hits = list(_ROOT.rglob(name))
        if not hits:
            missing.append(f"{rel} (no such file)")
            continue
        if not any(
            test.split("[")[0] in h.read_text(encoding="utf-8", errors="replace") for h in hits
        ):
            missing.append(f"{rel}::{test} (file exists, test not found in it)")
    return missing


def main() -> int:
    base = Settings(
        autonomous_verified=True,
        tester_enabled=False,
        reason_on_stall_enabled=False,
        oracle_coverage=False,
        oracle_mutation_check=False,
    )
    flipped = sorted(
        f
        for f in type(base).__dataclass_fields__
        if getattr(base, f) != getattr(apply_oracle_posture(base), f)
    )
    by_knob = registry_by_knob()

    width = max(len(r.knob) for r in REGISTRY)
    print("Control-liveness registry (highest PROVEN rung per knob; ADR-0081):\n")
    for r in REGISTRY:
        posture = "posture" if r.knob in flipped else "       "
        print(f"  {r.knob:{width}}  {r.rung:22}  [{posture}]  {r.evidence}")
        if r.note:
            print(f"  {'':{width}}  {'':22}             {r.note}")

    failures: list[str] = []

    missing_record = [k for k in flipped if k not in by_knob]
    if missing_record:
        failures.append(f"posture knobs with NO liveness record: {missing_record}")

    below_c4 = {
        r.knob for r in REGISTRY if r.knob in flipped and not r.rung.startswith(("C4", "C5"))
    }
    new_below_c4 = sorted(below_c4 - GRANDFATHERED)
    if new_below_c4:
        failures.append(
            f"NEW posture knobs below C4: {new_below_c4} — a posture knob must be proven "
            "arm-divergent before it flips behaviour by default (ADR-0081 Decision 4)"
        )

    for r in REGISTRY:
        for gap in _missing_evidence(r.evidence):
            failures.append(f"{r.knob}: evidence names a test that does not exist — {gap}")

    stale = sorted(GRANDFATHERED - below_c4)
    if stale:
        print(
            f"\nOK: {stale} reached C4+ — remove from GRANDFATHERED so the ratchet holds the gain."
        )
    remaining = sorted(below_c4 & GRANDFATHERED)
    if remaining:
        print(f"\nOK (report): the sentinel backlog, grandfathered and shrink-only: {remaining}")

    if failures:
        print("\nFAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nLiveness guard OK: every posture knob has an honest record.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
