"""Regression comparison for the MCB suite.

Averages repeated runs (scores are sampling-noisy by design), compares a fresh
scorecard against a committed baseline within tolerances, and persists baselines.
Baselines live in the repo (not git-ignored ``.mosaera/``) so they travel with the
code that produces them.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mosaera_core.bench.reliability import tally, worst_outcome
from mosaera_core.bench.scorecard import Dimension, Scorecard

_BASELINE_DIR = Path(__file__).parent / "baselines"

# Defaults: a score may drop by up to 5 points and cost may rise by 25% before it
# counts as a regression — scores vary run-to-run, so exact equality is wrong.
DEFAULT_SCORE_TOL = 5
DEFAULT_COST_TOL = 0.25


def baseline_path(case_id: str) -> Path:
    return _BASELINE_DIR / f"{case_id}.json"


def load_baseline(case_id: str) -> dict[str, Any] | None:
    path = baseline_path(case_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_baseline(card: Scorecard) -> Path:
    _BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    path = baseline_path(card.case_id)
    path.write_text(json.dumps(card.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def average(cards: list[Scorecard]) -> Scorecard:
    """Mean of N runs of the same case: per-dimension mean (ignoring N/A), mean
    overall, mean cost. Damps the run-to-run sampling noise."""
    if not cards:
        raise ValueError("cannot average zero scorecards")
    if len(cards) == 1:
        return cards[0]
    names = [d.name for d in cards[0].dimensions]
    dims: list[Dimension] = []
    for name in names:
        vals = [
            d.score for c in cards for d in c.dimensions if d.name == name and d.score is not None
        ]
        mean = round(statistics.mean(vals)) if vals else None
        dims.append(Dimension(name, mean, f"mean of {len(cards)} runs"))
    cost = {
        "total_tokens": round(statistics.mean(_nums(cards, "total_tokens"))),
        "usd": round(statistics.mean(_nums(cards, "usd")), 6),
        "calls": round(statistics.mean(_nums(cards, "calls"))),
    }
    overall = round(statistics.mean(c.overall for c in cards))
    first = cards[0].meta or {}
    delivered_runs = sum(1 for c in cards if (c.meta or {}).get("delivered"))
    # Reliability scoreboard (ADR-0053): the terminal buckets must survive averaging or the suite
    # never sees them — this is the easy-to-miss seam. Aggregate the N repeats' outcomes into a
    # count map, with the WORST that occurred as the representative (deny-by-default).
    run_outcomes = [
        str((c.meta or {}).get("outcome")) for c in cards if (c.meta or {}).get("outcome")
    ]
    # Held-out critic (#60, ADR-0065): the veto COUNT across the N repeats must survive averaging
    # (same easy-to-miss seam as `outcomes`) or the suite never sees the critic's fire rate.
    critic_vetoes = sum(1 for c in cards if (c.meta or {}).get("critic_vetoed"))
    # Behaviour-preservation Proctor (#60, ADR-0066): the count of repeats where the refactor
    # guidance was active — same survives-averaging seam.
    behavior_preservation_runs = sum(
        1 for c in cards if (c.meta or {}).get("behavior_preservation_detected")
    )
    # Terminal gate reasons (ADR-0078): same survives-averaging seam. Without this the aggregate
    # card — the one `--compare`/`--update-baseline` actually write, since repeat defaults to 3 —
    # loses the WHY of every park, which is exactly what the capture was for. A tally, not a
    # representative: a park is usually blocked by several reasons at once, and which of them was
    # "the" cause is not a question the data answers.
    #
    # A plain Counter, NOT `tally` — that one is fixed to the five OUTCOME buckets and would
    # silently drop every gate reason. Sorted so the serialization is stable and diffable.
    park_reasons = dict(
        sorted(
            Counter(
                str(r) for c in cards for r in ((c.meta or {}).get("gate_reasons") or [])
            ).items()
        )
    )
    # Over-park (the outcome-fidelity count): the survives-averaging seam AGAIN. A count that is
    # not aggregated here never reaches the suite rollup — and over-park is precisely the number
    # that spent a week invisible because nothing crossed `parked` with `grader_passed`.
    over_parks = sum(1 for c in cards if (c.meta or {}).get("over_park"))
    # Execution fingerprints (ADR-0081): the survives-averaging seam again. The per-repeat
    # fingerprints are what `liveness.experiment_verdict` compares across A/B arms — averaging
    # them is meaningless, so carry the LIST (order = repeat order, None for a repeat that
    # predates capture).
    fingerprints = [(c.meta or {}).get("fingerprint") for c in cards]
    meta = {
        "runs": len(cards),
        # Carry the stable taxonomy so the suite rollup can group an averaged card;
        # delivered = a majority of runs delivered.
        "capability": first.get("capability", "greenfield"),
        "tier": first.get("tier", "trivial"),
        "kind": first.get("kind"),
        "delivered": delivered_runs * 2 >= len(cards),
        "outcomes": tally(run_outcomes),
        "outcome": worst_outcome(run_outcomes),
        "critic_vetoes": critic_vetoes,
        "park_reasons": park_reasons,
        "fingerprints": fingerprints,
        "behavior_preservation_runs": behavior_preservation_runs,
        "over_parks": over_parks,
    }
    return Scorecard(
        case_id=cards[0].case_id,
        overall=overall,
        dimensions=dims,
        cost=cost,
        meta=meta,
    )


def _nums(cards: list[Scorecard], key: str) -> list[float]:
    return [float(c.cost.get(key) or 0) for c in cards]


@dataclass(frozen=True)
class Comparison:
    regressions: list[str]
    notes: list[str]

    @property
    def regressed(self) -> bool:
        return bool(self.regressions)


def compare(
    fresh: Scorecard,
    baseline: dict[str, Any],
    *,
    score_tol: int = DEFAULT_SCORE_TOL,
    cost_tol: float = DEFAULT_COST_TOL,
) -> Comparison:
    """Regressions = a score dropping more than ``score_tol`` below baseline, or a
    cost rising more than ``cost_tol`` above it. Improvements are notes, not fails."""
    regressions: list[str] = []
    notes: list[str] = []

    b_overall = baseline.get("overall")
    if isinstance(b_overall, int):
        delta = fresh.overall - b_overall
        if delta < -score_tol:
            regressions.append(f"overall {fresh.overall} vs baseline {b_overall} ({delta:+d})")
        elif delta > score_tol:
            notes.append(f"overall improved {b_overall} → {fresh.overall} ({delta:+d})")

    b_dims = {d["name"]: d["score"] for d in baseline.get("dimensions", [])}
    fresh_dims = {d.name: d.score for d in fresh.dimensions}
    for name, b in b_dims.items():
        f = fresh_dims.get(name)
        if not isinstance(b, int) or not isinstance(f, int):
            continue  # N/A on either side → not comparable
        if f - b < -score_tol:
            regressions.append(f"{name} {f} vs baseline {b} ({f - b:+d})")

    b_cost = baseline.get("cost", {})
    for key in ("usd", "total_tokens"):
        base_cost = float(b_cost.get(key) or 0)
        fresh_cost = float(fresh.cost.get(key) or 0)
        if base_cost > 0 and fresh_cost > base_cost * (1 + cost_tol):
            rise = (fresh_cost / base_cost - 1) * 100
            regressions.append(
                f"cost {key} {fresh_cost:g} vs baseline {base_cost:g} (+{rise:.0f}%)"
            )

    return Comparison(regressions=regressions, notes=notes)
