#!/usr/bin/env python3
"""God-file guard: fail if a source module exceeds MAX_LINES.

Enforces the modularity rule (see ``coding-standards.md`` and ``CLAUDE.md``): a source
file that grows past MAX_LINES is almost always doing too much and must be split into
cohesive modules (a facade + per-concern modules, or module-scope functions) so that a
change to one concern can't destabilise unrelated code.

Files that already exceed the limit and PREDATE the rule are GRANDFATHERED — they are
being worked down by the de-god-filing phases. The guard blocks NEW god-files; the
grandfathered set may only SHRINK. Never add to GRANDFATHERED — split the file instead.

**The ratchet is a RECORDED SIZE, not a name (2026-08-07 audit).** It used to be a bare set of
paths, which enforced only one direction: a file that dropped under the limit failed as stale, but
a listed file could GROW without bound and nothing noticed. A ratchet that only catches you fixing
things is not a ratchet. Each entry now carries the size it was recorded at, and exceeding that
size fails — so a grandfathered file may shrink or hold, never grow.

**Tests have their own, looser ceiling rather than no ceiling at all.** They were excluded
entirely on the reasoning that "long table-driven test files are acceptable" — which is true up to
a point and had let ``apps/api/tests/test_api.py`` reach 5702 lines, 11x the production limit and
37% of every test line in the repo. A test file that large is unnavigable, and the guard could not
see it. Same recorded-size ratchet: shrink or hold.

Covers the Python engine (``*.py``), the TS/TSX web app, and ``scripts/`` — a 691-line "script" is
a god-file wherever it lives. Run: ``python scripts/check_file_sizes.py`` (wired into ``make
lint``, which CI runs).
"""

from __future__ import annotations

from pathlib import Path

MAX_LINES = 500
# Tests earn a looser bar — a table-driven suite legitimately runs long — but not an unbounded one.
MAX_TEST_LINES = 1_500
ROOT = Path(__file__).resolve().parent.parent
SCAN_ROOTS = ("packages", "apps", "scripts")
# Both the Python engine and the TS/TSX web app — a god-file is a god-file in either language.
_SCAN_GLOBS = ("*.py", "*.ts", "*.tsx")

# Excluded from the rule entirely: generated/cache dirs, Alembic migrations (generated),
# benchmark case FIXTURES (they import run-workspace-only modules and are not shipped code), the
# built web bundle, and vendored shadcn/ui primitives (a generated component library, not our
# code). Tests are NOT here — they get MAX_TEST_LINES instead of an exemption.
_EXCLUDE_SUBSTR = (
    "/__pycache__/",
    "/migrations/",
    "/bench/cases/",
    "/.venv/",
    "/node_modules/",
    "/dist/",
    "/components/ui/",
)
# Test locations: Python under `/tests/`, the web app under `/test/`, plus co-located
# `*.test.tsx` / `*.spec.ts`. Story files are fixtures, not code, and stay exempt.
_TEST_SUBSTR = ("/tests/", "/test/")
_TEST_NAME_SUBSTR = (".test.", ".spec.")
_EXCLUDE_NAME_SUBSTR = (".stories.",)

# Over-limit files that predate the rule that now covers them, each to be split later, recorded
# at the size they were admitted. A RATCHET IN BOTH DIRECTIONS: over the recorded size fails
# (you grew it), at or under the ceiling fails as stale (you fixed it — delete the entry).
# Do NOT add entries — split the file instead. When you DO shrink one, lower its recorded size
# in the same commit: leftover slack is just room to grow back into, which is the hole this
# mechanism was rebuilt to close.
#
# The Python engine was fully worked down (repo.py was the last, split in Phase 5). The three TS
# files predate the guard's extension to the web app; the script and the test files predate its
# extension to `scripts/` and to tests (2026-08-07). Each is the same one-time grandfathering
# Python got when the guard was introduced.
GRANDFATHERED: dict[str, int] = {
    # --- web app (guard extended to TS/TSX) ---
    "apps/web/src/api/client.ts": 1040,  # gate→api/gate.ts, delivery→api/delivery.ts (ADR-0103)
    "apps/web/src/components/backlog/BacklogItemSheet.tsx": 753,
    "apps/web/src/components/pm/PmComposer.tsx": 592,
    # --- scripts/ (guard extended 2026-08-07) ---
    # --- tests (given MAX_TEST_LINES instead of an exemption, 2026-08-07) ---
    "apps/api/tests/test_api.py": 5642,  # 37% of every test line in the repo; split by route group
    "packages/core/tests/test_graph_integration.py": 2538,
    "packages/memory/tests/test_store.py": 1734,
}


def _included(rel: str) -> bool:
    if any(s in f"/{rel}" for s in _EXCLUDE_SUBSTR):
        return False
    return not any(s in rel.rsplit("/", 1)[-1] for s in _EXCLUDE_NAME_SUBSTR)


def _is_test(rel: str) -> bool:
    """Whether ``rel`` is test code, and so judged against ``MAX_TEST_LINES``."""
    name = rel.rsplit("/", 1)[-1]
    return any(s in f"/{rel}" for s in _TEST_SUBSTR) or any(s in name for s in _TEST_NAME_SUBSTR)


def limit_for(rel: str) -> int:
    return MAX_TEST_LINES if _is_test(rel) else MAX_LINES


def _line_count(path: Path) -> int:
    with path.open(encoding="utf-8", errors="replace") as fh:
        return sum(1 for _ in fh)


def audit() -> tuple[list[tuple[str, int, int]], list[tuple[str, int, int]], set[str]]:
    """``(offenders, grown, stale)`` — the guard's whole verdict, as data so tests can drive it."""
    offenders: list[tuple[str, int, int]] = []
    grown: list[tuple[str, int, int]] = []
    seen_grandfathered: set[str] = set()
    candidates: set[Path] = set()
    for root in SCAN_ROOTS:
        for pattern in _SCAN_GLOBS:
            candidates.update((ROOT / root).rglob(pattern))
    for path in sorted(candidates):
        rel = path.relative_to(ROOT).as_posix()
        if not _included(rel):
            continue
        count = _line_count(path)
        limit = limit_for(rel)
        if rel in GRANDFATHERED:
            recorded = GRANDFATHERED[rel]
            if count > limit:
                seen_grandfathered.add(rel)
                if count > recorded:
                    # The hole this closes: a listed file used to be able to grow forever.
                    grown.append((rel, count, recorded))
        elif count > limit:
            offenders.append((rel, count, limit))
    return offenders, grown, set(GRANDFATHERED) - seen_grandfathered


def main() -> int:
    offenders, grown, stale = audit()

    rc = 0
    if offenders:
        print(f"God-file guard FAILED: {len(offenders)} file(s) over their limit.")
        print("Split each into cohesive modules (see coding-standards.md 'Modularity'):")
        for rel, n, limit in sorted(offenders, key=lambda x: -x[1]):
            print(f"  {n:>5}  (limit {limit})  {rel}")
        rc = 1

    if grown:
        print("\nRatchet: these GRANDFATHERED files GREW. The list is a debt being paid down,")
        print("not a licence — shrink them, or split them, but do not raise the recorded size:")
        for rel, n, recorded in sorted(grown, key=lambda x: -(x[1] - x[2])):
            print(f"  {n:>5}  (recorded {recorded}, +{n - recorded})  {rel}")
        rc = 1

    if stale:
        print("\nRatchet: these GRANDFATHERED files are now under their limit — delete them")
        print("from GRANDFATHERED in scripts/check_file_sizes.py so they stay under the guard:")
        for rel in sorted(stale):
            print(f"  {rel}")
        rc = 1

    if rc == 0:
        print(
            f"God-file guard OK: nothing over {MAX_LINES} lines "
            f"({MAX_TEST_LINES} for tests), and no grandfathered file grew."
        )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
