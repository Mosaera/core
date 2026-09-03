"""Which backlog items are the same work? — item-to-item comparison, not spec reading.

Its own module rather than a fifth rule in `spec_lint`: every check there reads ONE item's spec
and asks whether it is checkable, decidable or buildable. This one compares items against EACH
OTHER, which is a different question with a different failure mode — and `spec_lint` is at the
modularity ceiling, so a rule of this size could not honestly live there anyway.

**Why not the existing Jaccard rule.** `spec_lint` already has a near-duplicate check: token-set
Jaccard over `title + acceptance`, above 0.5. Measured against the LedgerCLI backlog on 2026-08-19,
where seven duplicate pairs were confirmed by hand, it fired on **none of them**. The reason is
structural rather than a threshold being slightly wrong: these duplicates are re-creations, so one
side carries full acceptance criteria and the other carries none. The union balloons while the
intersection does not, and Jaccard — which divides by the union — is biased against exactly the
shape a re-created item has.

The obvious repair, the overlap coefficient (divide by the SMALLER set), inverts the bias: it
saturates whenever one item's text is short, and measured 54% precision, reporting six false pairs
driven entirely by short titles.

What works is weighting: words common across this project's backlog ("add", "create", "tests",
the package name) carry almost no evidence that two items are the same work, while rare ones
("egg-info", "pandas", "F401") carry nearly all of it. Inverse document frequency is the standard
statement of that, and it is deterministic, needs no model, and adds no per-defect pattern — the
thing ADR-0085 forbids.

**Measured, and the honest caveat.** On that corpus, IDF-weighted cosine at 0.3 scored 100%
precision and 86% pair recall, and grouping recovers the rest: a weak edge inside a group is
carried by its neighbours.

*How* the grouping is done turned out to matter more than the threshold. The first version shipped
single linkage (a union-find over every edge above the threshold) and it CHAINED on the live
backlog within hours — see `between()` for the case and the numbers. Average linkage fixes it and
is stable across a wider band: all five hand-confirmed groups at both 0.25 and 0.3, where single
linkage was wrong at both.

The threshold is still provisional. It was chosen after seeing the labels, on one small backlog,
and IDF over a handful of documents is unstable by nature — the false edge that broke single
linkage existed precisely because a boilerplate sentence looked rare in a 16-item corpus. Treat
0.3 as a starting point until a second project's corpus says otherwise. This is also why the
finding is an advisory report that never blocks a launch: the cost of a wrong grouping is a
suggestion the operator declines, not work that cannot start.

IDF is computed over the project's own backlog, so it adapts per project — and is unstable on a
very small one, which is a further reason the output only ever advises.
"""

from __future__ import annotations

import math
import re
from typing import Any

from mosaera_core.spec_lint import normalize

_WORD = re.compile(r"[a-z0-9]{3,}")

#: Provisional — see the module docstring. Raising it costs whole groups; lowering it admits the
#: generic-scaffolding pairs that IDF is here to suppress.
_COSINE_THRESHOLD = 0.3

#: Delivered work is not a duplicate of anything; comparing against it only invents pairs.
_SETTLED = frozenset({"done", "merged"})


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(normalize(text)))


def _item_text(item: dict[str, Any]) -> str:
    return f"{item.get('title', '')} {item.get('acceptance', '')}"


def duplicate_groups(
    items: list[dict[str, Any]], *, threshold: float = _COSINE_THRESHOLD
) -> list[list[int]]:
    """Groups of item ids that appear to be the same work. ``[]`` when nothing is similar.

    Connected components, not pairs: these arrive as generations — the same job re-created two or
    three times — and an operator wants "these three are one job", not three separate pair
    warnings. It also recovers recall, since one weak edge inside a group costs nothing when the
    other edges hold.

    Pure and deterministic: no store, no settings, no model. Ids come back sorted, and so do the
    groups, so the rendered text is stable between turns and does not churn the context.
    """
    live = [i for i in items if str(i.get("status", "todo")) not in _SETTLED]
    docs: dict[int, set[str]] = {}
    for item in live:
        toks = _tokens(_item_text(item))
        if toks:
            docs[int(item["id"])] = toks
    if len(docs) < 2:
        return []

    total = len(docs)
    freq: dict[str, int] = {}
    for toks in docs.values():
        for tok in toks:
            freq[tok] = freq.get(tok, 0) + 1

    def weight(tok: str) -> float:
        # +1 in the denominator and the trailing +1 keep this defined and positive for a token
        # present in every document, which would otherwise weigh exactly nothing and make two
        # boilerplate-only items look infinitely similar (0/0).
        return math.log(total / (1 + freq.get(tok, 0))) + 1.0

    norms = {i: math.sqrt(sum(weight(t) ** 2 for t in toks)) for i, toks in docs.items()}
    ids = sorted(docs)

    # The full pairwise matrix, computed ONCE. Merging below only reads it, so the cost stays
    # O(n^2) similarities rather than recomputing them on every merge pass.
    sims: dict[tuple[int, int], float] = {}
    for pos, a in enumerate(ids):
        for b in ids[pos + 1 :]:
            if norms[a] and norms[b]:
                shared = sum(weight(t) ** 2 for t in docs[a] & docs[b])
                sims[(a, b)] = shared / (norms[a] * norms[b])

    def between(x: list[int], y: list[int]) -> float:
        """AVERAGE similarity between two clusters — average linkage, not single.

        Single linkage (a union-find over any edge above the threshold) is what this function used
        to do, and it chains: ONE false edge welds two true groups into a blob. That is not a
        hypothetical. Shipped on 2026-08-19, it merged the .gitignore items with the unused-import
        items on the live backlog, because two of them happened to share the sentence "The existing
        test suite still passes unchanged - this item changes no runtime behaviour" — boilerplate
        that a 16-item corpus reads as rare, scoring 0.305 against a 0.3 threshold.

        Averaging over every cross-pair means one accidental edge is outvoted by the members that
        are genuinely unalike, while a group whose members mostly agree survives a single weak
        edge — which is the recall that made grouping worth doing. Measured on that same live
        backlog, average linkage reproduces all five hand-confirmed groups at BOTH 0.25 and 0.3,
        where single linkage was wrong at both.
        """
        pairs = [sims.get((min(a, b), max(a, b)), 0.0) for a in x for b in y]
        return sum(pairs) / len(pairs) if pairs else 0.0

    clusters = [[i] for i in ids]
    while True:
        best: tuple[float, int, int] | None = None
        for x in range(len(clusters)):
            for y in range(x + 1, len(clusters)):
                score = between(clusters[x], clusters[y])
                if score >= threshold and (best is None or score > best[0]):
                    best = (score, x, y)
        if best is None:
            break
        _, x, y = best
        clusters[x] = sorted(clusters[x] + clusters[y])
        clusters.pop(y)

    return sorted((c for c in clusters if len(c) > 1), key=lambda c: c[0])
