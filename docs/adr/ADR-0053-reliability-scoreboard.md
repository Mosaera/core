# ADR-0053: The reliability scoreboard — clean-conclusion rate as the #43 arc's definition of done

- Status: accepted
- Date: 2026-07-17
- Owners: Mosaera core
- Related issue: #43 (run-reliability arc)
- Related threat model: — (measurement only; no trust-surface change)

## Context

The #43 arc's target is a *number*: ~99% of runs reach a clean terminal state — deliver, or park
honestly with an accurate reason — **without looping or thrashing**. But we could not see that number.
Each run already classifies its own terminal state (ADR-0006's `termination_reason` + `run_events`), and
the MCB benchmark (ADR-0007/0027) already drives representative runs and grades them against a hidden
acceptance suite — yet nothing aggregated "how did runs *conclude*" into a rate. Without the scoreboard we
were fixing reliability blind and had no regression signal and no evidence of when the arc is *done*.

## Decision

Add a **reliability scoreboard** to the existing MCB suite rollup — pure aggregation over signals the run
already produces, no new run-state and no second harness.

- **Five terminal buckets** (`bench/reliability.py::classify_outcome`, pure over the run's `final` +
  the hidden grader, mirroring `diagnose_bottleneck`):
  - `clean_deliver` — approved AND the grader passes (or no grader) — true success.
  - `honest_park` — did not deliver, but stopped promptly on an accurate reason.
  - `thrash_park` — did not deliver AND ground to the no-progress breaker (`stalled`) or the iteration
    cap (the gate's own `iteration_limit` reason).
  - `false_ship` — approved BUT the hidden grader fails — a *dishonest* success.
  - `crash` — an exception escaped the run.
- **Clean-conclusion rate** = `(clean_deliver + honest_park) / runs` — the two buckets that satisfy the
  arc ("either stop when they should, or truly succeed"). `false_ship` / `thrash_park` / `crash` are the
  failures to drive down. This is the scoreboard headline; the #43 target is ~0.99.
- **Wired through the existing rollup at three seams:** tag each run's `outcome` in the scorecard `meta`
  (`cli.py::_run_once`); aggregate the buckets across repeats when averaging (`compare.average` — the
  easy-to-miss seam, or the rate would silently drop the N repeats); and sum + report in the suite
  (`suite.build_suite` → `SuiteReport.clean_conclusion_rate` + per-bucket `outcomes`), rendered in the
  suite Markdown/JSON, the CLI print, and the `history.jsonl` trend log so the trajectory is trackable.

## Options considered

- **Extend the MCB suite rollup (chosen).** Reuses the harness, the grader (ground truth for
  `false_ship` vs `clean_deliver`), and the trend log. Smallest surface; the reliability lens rides the
  same `--all` run operators already do.
- **A separate reliability harness.** Rejected — it would duplicate case-running, grading, and trend
  machinery, and drift from the capability numbers it must sit beside.
- **Reuse the API runner's `_termination_reason`.** Rejected — it lives in `apps/api` (a higher layer);
  `core`/`bench` importing it violates the one-way layer rule. The classifier is re-derived in `core`
  from the same `final` signals (a small, acceptable duplication of a pure function; a future cleanup
  could lift a shared classifier into `core` and have the runner consume it).

## Security implications

None — measurement only. The classifier is pure and read-only over a finished run's state + the grader
verdict; it changes no gate, policy, or delivery path. `false_ship` is defined by the *hidden* grader, so
it cannot be gamed by the run under test.

## Operational implications

The scoreboard appears whenever `mosaera-bench` runs more than one case (`--all`), in the suite
Markdown/JSON and `history.jsonl`. No migration, no new dependency. Like the rest of the benchmark it is
heavy/opt-in (needs a model + Docker) and is NOT part of `make test` — the pure classifier + aggregation,
however, are unit-tested offline.

## Consequences

- **Good:** #43 becomes evidence-driven — a baseline number, a per-bucket breakdown that ranks what to
  fix next (false-ship vs thrash vs crash), and free regression tracking across releases.
- **Follow-up:** run `mosaera-bench --all` to record the baseline; then measure-then-fix the top
  offenders (#45 whole-suite validation for `false_ship`; the early degenerate/repeated-plan breaker +
  Proctor red-hunt bound for `thrash_park`) until the rate holds ≥99%. A suite-level baseline/regression
  gate on the clean-conclusion rate (mirroring the per-case `compare()`) is possible later but is new
  surface — deferred until there's a stable number to gate on.
