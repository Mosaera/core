"""`mosaera-pmbench` — run the PM behaviour suite against a live model.

Not part of `make test`: it needs a model, which makes it slow and non-deterministic.
Its OFFLINE half —
case soundness and the scorer's arithmetic — does run there
(`packages/core/tests/test_pmbench.py`), so a broken case is caught by CI even though a score is
not.

Default is `--repeat 5` and a printed SPREAD rather than a single number, because the first thing
anyone needs from a new instrument is its noise floor. A dimension whose run-to-run spread is wider
than the change it is meant to detect cannot support a claim, and reporting one number would hide
that. No baseline is committed until the floor is known.
"""

from __future__ import annotations

import argparse
import json
import time

from mosaera_core.config import Settings
from mosaera_core.pmbench import DIMENSIONS, available_pm_cases
from mosaera_core.pmbench.arms import ALPHA

from mosaera_api.pmbench_run import run_comparison, run_sweep, write_sweep


def _spread(passes: list[dict], name: str) -> str:
    cases = max(
        (p["dimensions"][name]["total"] for p in passes if name in p["dimensions"]), default=0
    )
    seen = [p["rates"][name] for p in passes if p["rates"].get(name) is not None]
    if not seen:
        return "  (no case asserts this)"
    lo, hi = min(seen), max(seen)
    if lo == hi:
        band = ""
    elif cases == 1:
        # One case cannot have variance — it flips. Calling a binary flip "variance" reads as
        # instrument noise and would excuse a real disagreement as measurement error.
        band = f"  flips (1 case, {sum(1 for v in seen if v == 1.0)}/{len(seen)} passes)"
    else:
        band = f"  spread {hi - lo:.2f}  <-- larger than one case; not a usable signal"
    return f"  {lo:.2f} to {hi:.2f} over {len(seen)} pass(es){band}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the QMB PM behaviour suite.")
    ap.add_argument("case", nargs="?", help="a single case id (default: all)")
    ap.add_argument("--repeat", type=int, default=5, help="passes (default 5 — the noise floor)")
    ap.add_argument("--no-write", action="store_true", help="do not persist the sweep")
    ap.add_argument(
        "--arm",
        action="append",
        default=[],
        metavar="MODEL",
        help="pin a model for an arm; give twice to COMPARE two models",
    )
    ap.add_argument(
        "--null-control",
        action="store_true",
        help="run --arm's model against ITSELF to measure the noise floor first",
    )
    ap.add_argument(
        "--null-floor",
        type=int,
        default=None,
        metavar="N",
        help="discordant count a prior null control measured; reported with the comparison so "
        "its noise is stated rather than assumed",
    )
    args = ap.parse_args()

    cases = [args.case] if args.case else available_pm_cases()
    if not cases:
        print("no QMB cases found")
        return 1

    if args.null_control or len(args.arm) == 2:
        model_a = args.arm[0] if args.arm else None
        if model_a is None:
            print("--null-control and a comparison both need --arm MODEL")
            return 1
        model_b = None if args.null_control else args.arm[1]
        out = run_comparison(
            cases, model_a, model_b, repeat=args.repeat, null_floor=args.null_floor
        )
        for arm in out["arms"]:
            per_call = arm["seconds"] / arm["calls"] if arm.get("calls") else 0.0
            print(
                f"arm: {arm['model']}  {arm['repeat']} passes  {arm['seconds']}s"
                + (f"  {arm['calls']} calls ({per_call:.1f}s each)" if arm.get("calls") else "")
                + (f"  {arm['tokens']:,} tok" if arm.get("tokens") else "")
                + (f"  ${arm['usd']:.4f}" if arm.get("usd") else "")
                # Marked, never silently blended: an on-box arm's dollars are imputed.
                + (f"  ~${arm['shadow_usd']:.4f} shadow" if arm.get("shadow_usd") else "")
                + (f"  UNUSABLE {len(arm['unusable'])}" if arm["unusable"] else "")
            )
        if out["kind"] == "null_control":
            total = out["discordant"] + out["concordant"]
            print(
                f"\nNULL CONTROL: {out['discordant']} discordant of {total} paired trials, "
                f"split {out['split'][0]}/{out['split'][1]}, p={out['p_value']:.3f}"
            )
            print(f"  {out['note']}")
            if out["calibrated"]:
                print("\n  This run declined to name a winner, as it should.")
                print("  One clean null control is reassurance, not proof: repeat it.")
            else:
                print("\n  *** This run NAMED A WINNER between one model and itself.")
                print(f"  *** p={out['p_value']:.3f} against alpha={ALPHA}. A calibrated test does")
                print(f"  *** this about {ALPHA:.0%} of the time by chance, so ONE such result")
                print("  *** cannot distinguish bad luck from a systematic order effect.")
                print("  *** Repeat the null control before trusting OR condemning the test.")
        else:
            print(
                f"\ndiscordant {out['discordant']}  concordant {out['concordant']}  "
                f"p={out['p_value']:.4f}"
            )
            primary = out["primary"]
            if out["winner"]:
                print(f"\nWINNER on the primary dimension ({primary}): {out['winner']}")
            else:
                print(f"\nNO WINNER on the primary dimension ({primary}) — {out['verdict']}")
                if out["needed"]:
                    print(f"  would have needed ~{out['needed']} discordant trials")

            print("\n  per dimension (only the primary may name a winner):")
            for dim, d in sorted(out["by_dimension"].items()):
                mark = "PRIMARY  " if dim == primary else "secondary"
                lead = ""
                if d["split"][0] != d["split"][1]:
                    ahead = out["arms"][0 if d["split"][0] > d["split"][1] else 1]["model"]
                    lead = f"  leans {ahead}"
                print(
                    f"    {mark} {dim:<11} {d['split'][0]}/{d['split'][1]}"
                    f"  p={d['p_value']:.3f}{lead}"
                )
            if out["heterogeneous"]:
                print(
                    "\n  *** The dimensions lean in OPPOSING directions, so the pooled split is\n"
                    "  *** their difference and summarises nothing. Read the rows, not the total."
                )
            print(
                f"  split {out['split'][0]}/{out['split'][1]} "
                f"({out['arms'][0]['model']} / {out['arms'][1]['model']})"
            )
            for note in out["notes"]:
                print(f"  note: {note}")
            if out["disagreements"]:
                print("\n  the trials they disagreed on:")
                for d in out["disagreements"]:
                    print(
                        f"    {d['case']} {d['dimension']:<11} pass {d['pass']}  -> {d['passed']}"
                    )
        # A comparison costs real GPU time — 43 minutes for the first one — so it is written even
        # when the verdict is "too close to call". Discarding the evidence is why that run could
        # not be audited afterwards.
        if not args.no_write:
            path = write_sweep(out, Settings.from_env().home, time.strftime("%Y%m%d-%H%M%S"))
            print(f"\nwrote {path}")
        return 0

    result = run_sweep(cases, repeat=args.repeat)
    print(f"model: {result['model']}   cases: {len(cases)}   passes: {args.repeat}\n")
    for name in DIMENSIONS:
        print(f"{name:>11}:{_spread(result['passes'], name)}")

    failures = sorted(
        {c for p in result["passes"] for d in p["dimensions"].values() for c in d["failures"]}
    )
    if failures:
        print(f"\nfailed at least once: {', '.join(failures)}")
    unusable = sorted({c for p in result["passes"] for c in p["unusable"]})
    if unusable:
        print(f"UNUSABLE (model call failed, not scored as zero): {', '.join(unusable)}")

    if not args.no_write:
        path = write_sweep(result, Settings.from_env().home, time.strftime("%Y%m%d-%H%M%S"))
        print(f"\nwrote {path}")
    else:
        print(json.dumps(result["passes"], indent=2)[:0] or "", end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
