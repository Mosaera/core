"""`mosaera-layer2-report` — Layer-2's standing performance, read off every scorecard ever written.

Layer 2 converts an honest park into a ship without a human. Whether it should be enabled is a
question about **how often it is right**, and until now that had no answer at all: `#76`'s DoD
measured 0 true conversions in 12 runs, the 2026-08-05 sweep recorded 0 conversion attempts, and a
scan of all 2,055 stored cards on 2026-08-08 found **zero cards where it was ever eligible**. The
per-run fields existed the whole time; nothing ever read them together.

That is this repo's most-repeated defect — a declared field with no consumer (F74) — sitting on the
one mechanism that can ship code unattended. This reads the fields.

**The measurement is a confusion matrix, not a rate**, and the asymmetry is the point: a conversion
the hidden grader FAILS is a false ship (the thing ADR-0061 gate 2 exists to drive to zero); a park
left standing on correct work is waste. One is a defect, the other is a cost, and a single number
would hide which.

Two genuinely independent judges make it meaningful. Layer 2 authors its own test to decide whether
to convert; the hidden grader — which the run never sees — decides whether that was right. Were they
the same artifact the matrix would prove nothing.

Cumulative by design: it reads `<home>/benchmarks/<CASE>/*.json`, so every future sweep deepens the
record without anyone remembering to log anything.

Run: ``uv run mosaera-layer2-report`` (all history) or ``--since 20260808`` for one sweep onward.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from mosaera_core.config import Settings


def _cards(root: Path, since: str) -> list[dict[str, Any]]:
    out = []
    for path in sorted(root.glob("*/*.json")):
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        meta = card.get("meta")
        if not isinstance(meta, dict):
            continue
        if since and str(meta.get("stamp", "")) < since:
            continue
        meta["_case"] = card.get("case_id") or path.parent.name
        out.append(meta)
    return out


def summarize(cards: list[dict[str, Any]]) -> dict[str, Any]:
    """The four cells, plus why the rest never got a chance.

    `verified` is the only verdict that ships. Everything else — `unverified`, `unavailable`, a
    decline, or never being eligible — leaves the park standing, which is the safe direction.
    """
    parks = [m for m in cards if m.get("outcome") == "honest_park"]
    eligible = [m for m in parks if m.get("layer2_class")]
    matrix: Counter[tuple[str, str]] = Counter()
    for m in eligible:
        shipped = "converted" if m.get("layer2_verdict") == "verified" else "left parked"
        passed = m.get("grader_passed")
        # `is True` / `is False`, never truthiness: a missing grader is None, and treating that as
        # "wrong" would score an unmeasured run as a correct refusal we never earned.
        graded = (
            "work was right"
            if passed is True
            else "work was wrong"
            if passed is False
            else "ungraded"
        )
        matrix[(shipped, graded)] += 1
    return {
        "cards": len(cards),
        "honest_parks": len(parks),
        "eligible": len(eligible),
        "matrix": matrix,
        "classes": Counter(str(m.get("layer2_class")) for m in eligible),
        "verdicts": Counter(str(m.get("layer2_verdict") or "none") for m in eligible),
        "declines": Counter(
            str(m.get("layer2_decline"))[:70] for m in parks if m.get("layer2_decline")
        ),
        # WHY an attempt decided as it did — the half that was missing until 2026-08-08.
        # `unverified` covers "the code failed the test", "the test is a rubber stamp" and "the
        # check could not run", which have opposite implications for what to fix.
        "reasons": Counter(str(m.get("layer2_reason") or "(not recorded)")[:70] for m in eligible),
        "mutation": Counter(
            {True: "caught", False: "SURVIVED", None: "inconclusive"}.get(
                m.get("layer2_mutation_caught"), "n/a"
            )
            for m in eligible
        ),
    }


def _bound(successes: int, trials: int) -> str:
    """The 95% upper bound on the failure rate when zero failures were seen (rule of three).

    Printed beside every clean result on purpose. "0 false ships" out of a handful of conversions
    bounds the true rate near 50%, not near 0, and reporting the count without the bound is exactly
    the overclaim ADR-0061's gate-2 amendment exists to stop: *a rate is only a result when the
    distribution it bounds is named.*
    """
    if trials <= 0:
        return "no conversions — nothing is bounded"
    if successes:
        return f"{successes}/{trials} FALSE SHIPS — the knob stays off"
    return f"0/{trials} false ships; 95% upper bound ~{300 / trials:.0f}% — NOT zero"


def render(summary: dict[str, Any]) -> str:
    m = summary["matrix"]
    conv_right = m[("converted", "work was right")]
    conv_wrong = m[("converted", "work was wrong")]
    kept_right = m[("left parked", "work was right")]
    kept_wrong = m[("left parked", "work was wrong")]
    lines = [
        "  Layer-2 disposition — standing record",
        f"    scorecards read      {summary['cards']}",
        f"    honest parks         {summary['honest_parks']}",
        f"    ELIGIBLE for rescue  {summary['eligible']}",
        "",
        "                       grader: work was RIGHT   grader: work was WRONG",
        f"    converted (shipped)  {conv_right:^21} {conv_wrong:^21}",
        f"    left parked          {kept_right:^21} {kept_wrong:^21}",
        "",
        f"    the win     : {conv_right} correct deliveries rescued from a park",
        f"    the failure : {_bound(conv_wrong, conv_right + conv_wrong)}",
        f"    the waste   : {kept_right} correct deliveries still discarded",
        f"    correct nos : {kept_wrong} wrong deliveries correctly refused",
    ]
    if summary["classes"]:
        lines += ["", f"    by class    : {dict(summary['classes'])}"]
        lines += [f"    verdicts    : {dict(summary['verdicts'])}"]
    if summary.get("reasons"):
        lines += ["", "    why each ATTEMPT decided as it did:"]
        lines += [f"      {n:4}  {r}" for r, n in summary["reasons"].most_common(6)]
        lines += [f"    mutation check: {dict(summary['mutation'])}"]
        gap = summary["verdicts"].get("not_measured", 0)
        if gap:
            lines += [
                f"    of which {gap} are NOT_MEASURED — the oracle could not form a question about",
                "    the change at all. A gap in the ORACLE, not a verdict on the test, and",
                "    it still declines (deny-by-default). Read it as coverage owed, not a refusal.",
            ]
    if summary["declines"]:
        lines += ["", "    why it was never attempted (eligibility):"]
        lines += [f"      {n:4}  {r}" for r, n in summary["declines"].most_common(6)]
    if not summary["eligible"]:
        lines += [
            "",
            "    NEVER ELIGIBLE. Either no park reached a convertible class, or the sweep ran",
            "    without --layer2. That is a real result, not a missing measurement — record it.",
        ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mosaera-layer2-report",
        description="Layer-2's conversion record against the hidden grader, over all stored cards.",
    )
    parser.add_argument(
        "--since", default="", help="only cards stamped at/after this (e.g. 20260808)"
    )
    args = parser.parse_args(argv)

    root = Settings.from_env().home / "benchmarks"
    if not root.is_dir():
        print(f"no benchmark cards under {root}")
        return 1
    print(render(summarize(_cards(root, args.since))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
