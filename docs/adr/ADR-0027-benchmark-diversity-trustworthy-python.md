# ADR-0027: Benchmark diversity — trustworthy Python via representative project shapes (then cross-language)

- Status: accepted
- Date: 2026-07-13
- Owners: Alejandro Rengifo
- Related: [ADR-0007](ADR-0007-capability-benchmark-suite.md) (the benchmark suite this extends), [ADR-0025](ADR-0025-behaviour-smoke-gate.md) (the behaviour-smoke floor these cases finally exercise), [ADR-0016](ADR-0016-deterministic-model-escalation.md) (the escalation Rule-0 that the web-app case is expected to press on)

## Context

The Phase-2 measurement of the ADR-0025 correctness-oracle work (MCB-05/11/18, 2026-07-13) proved the
cloud-escalation tier fires end-to-end for the first time — but it also showed the benchmark **cannot measure the
thing we just built**: all 20 existing MCB cases are single-module Python (`checkout.py`, `metrics.py`, …) with
no runnable entrypoint, so the behaviour-smoke floor stayed inert on every one. The benchmark is blind to the
exact project shapes real work takes.

The direction (owner, 2026-07-13): **make Python delivery trustworthy end-to-end first — a Python project you
don't have to babysit — then stack Node / TS / Go on top for real apps.** So the benchmark's job now is to cover
real Python *shapes*, expose where trust actually breaks, and drive the engine fixes that close those gaps —
before any cross-language investment.

Today's honest Python ceiling (what this arc pushes): a mid-size, pure-Python, offline-pytest-testable CLI or
library (~1–2k LOC, ~10–15 files, stdlib + pip). The binding constraints, worst-biting first: (1) validation is
Python-pytest-offline or the gate parks; (2) the correctness oracle is LLM-authored (green ≠ works); (3)
multi-file architectural coherence is unproven past ~4 items; (4) the local coder is ~C+.

## Decision

Add **entrypoint-bearing, multi-file benchmark cases that sit at and just past that ceiling**, each a
self-validating MCB case (seed + hidden black-box grader + the two soundness invariants of ADR-0007), delivered
as small progressive MRs — measure, then fix what the measurement exposes:

- **MR-A (this MR) — `MCB-21`, a multi-module CLI package** (`journal`: `cli`/`store`/`model`, run as
  `python -m journal`), a `feature`/`moderate` tag+find add. First case whose entrypoint exercises the ADR-0025
  behaviour-smoke floor (verified: the planner emits a `cli-smoke: python -m journal --help` step), and whose
  black-box grader drives the real CLI end-to-end — so a cross-module wiring bug (a `str` where a `Path` is
  expected, the pyledger failure) fails the case even when unit tests pass.
- **MR-B — a pure-logic interpreter/evaluator case** (rock-solid oracle) to probe coherence/scale (constraint 3)
  with the coder isolated from oracle noise.
- **MR-C — a stdlib `http.server` web-app case** to stress the oracle gap (constraint 2); expected to *expose* a
  false-positive ship (behaviour-smoke starts it, but does the tester write a real integration test?).
- **MR-D — the engine fix MR-C justifies:** oracle-side escalation. The Phase-2 finding: a false-positive ship
  (MCB-05, even on Sonnet) is an *oracle* bottleneck, not a coder one — `diagnose_bottleneck` Rule 0 escalating
  the coder when the tester is off treats the wrong role. The fix is to strengthen the oracle (enable the tester /
  a grader-like behavioural check), not buy a bigger coder.

Cross-**language** cases (JS/TS, Go) are the *follow-on* arc, gated on the parked Node/infra track (!181) — Python
trustworthy first, then real apps on top.

**Status of this plan, noted 2026-08-18** (`docs/audits/adr-corpus-review-2026-08-18.md`):

- **MR-A — SHIPPED**: `packages/core/mosaera_core/bench/cases/MCB-21/` (the multi-module `journal` CLI).
- **MR-B — SHIPPED**: `packages/core/mosaera_core/bench/cases/MCB-22/` (the pure-logic `calc` case; its
  `case.toml` cites "ADR-0027 MR-B").
- **MR-C — NOT BUILT.** No `http.server` web-app case exists; the corpus skips from MCB-23 to MCB-26.
- **MR-D — NOT BUILT.** `diagnose_bottleneck` Rule 0 still reads
  `return "tester" if settings.tester_enabled else "coder"` in `packages/core/mosaera_core/bench/escalation.py`,
  i.e. the exact "treats the wrong role" behaviour MR-D was meant to fix. Neither MR-C nor MR-D is tracked on
  `docs/roadmap.md`.
- **The cross-language deferral above is DISCHARGED** by [ADR-0032](ADR-0032-adding-a-languagepack.md), which took
  the LanguagePack route rather than waiting on !181: `packages/core/mosaera_core/bench/cases/MCB-23/` (Node) and
  `packages/core/mosaera_core/bench/cases/MCB-26/` (SQL) are the `MCB-L-*` bar being met.

## Consequences

- The benchmark can finally measure the behaviour-smoke floor and multi-module coherence — the two things the
  pyledger case study flagged and the ADR-0025 work targeted.
- New cases are fixtures under `bench/cases/` (not CODEOWNERS-protected, excluded from repo lint/type/test);
  soundness is proven offline by `tests/test_bench_cases.py` in `make test` (no model, no Docker).
- MR-D may touch `bench/escalation.py` (Rule 0) — a diagnosis-ordering change, still no `packages/policies` edit.
- Honest scope: this measures and hardens the *reachable* Python ceiling; it does not by itself lift the
  parks-without-a-runtime limit (that's the cross-language arc) or replace the missing live independent oracle
  (only the benchmark's hidden grader is truly independent; a live equivalent remains future work).

## Alternatives considered
- **Jump straight to cross-language / Node.** Rejected per the owner's sequencing — Python isn't yet trustworthy
  enough to build real apps on; measuring and fixing Python first is the cheaper, higher-confidence path.
- **Re-run the existing 20 cases and call it coverage.** Rejected — they're single-module, so they can't exercise
  the floor or the coherence question no matter how often they run.
