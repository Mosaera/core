"""Deterministic test-input mining — the #62 generator's reusable core.

Split from `refactor_scaffold` so the Layer-2 disposition (`disposition.close_oracle_gap`) can hand
the SAME mined boundaries to its authored acceptance test. The 2026-08-09 Layer-2 deferral measured
0 conversions in 13 eligible parks because the freeform authoring could not form a mutation-catching
question; #62 measured that mined boundary triples take `mutation_caught` from 0/20 to 20/20 on the
same wall (engineering-history/mutation-guided-inputs-2026-08-03.md). Same evidence-raiser, second
consumer — "the AND stands, the evidence rises."
"""

from __future__ import annotations

import ast

_NUM_BOUNDARIES: tuple[int, ...] = (0, 1, 5, 9, 10, 11, 50, 100)
_MAX_MINED_LITERALS = 6


def mined_boundaries(src: str) -> tuple[int, ...]:
    """Numeric boundaries MINED from the module under refactor (#62).

    The generic `_NUM_BOUNDARIES` cannot reach a branch guarded by a limit it doesn't contain —
    measured: MCB-14 validates `0 <= age <= 150`, the generic set tops out at 100 and has no
    negatives, so NO generated input ever reached either `raise`, and a mutant that DELETED the
    validation call survived both the suite and the differential (the #60 wall's third leg,
    engineering-history/refactor-vouch-ab-2026-08-03.md).

    Every numeric literal in the source becomes a boundary TRIPLE (L-1, L, L+1) — the classic
    off-by-one triple around each real threshold, which is exactly what reaches the branch on
    both sides. Deterministic, source-derived, no RNG. Bounded so a constant-heavy module can't
    explode the case list.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return ()
    found: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            if isinstance(node.value, bool):
                continue
            found.append(int(node.value))
    out: list[int] = []
    for value in sorted(set(found))[:_MAX_MINED_LITERALS]:
        out.extend((value - 1, value, value + 1))
    # Preserve order, drop duplicates and anything the generic set already covers.
    seen: set[int] = set(_NUM_BOUNDARIES)
    mined: list[int] = []
    for value in out:
        if value not in seen:
            seen.add(value)
            mined.append(value)
    return tuple(mined)
