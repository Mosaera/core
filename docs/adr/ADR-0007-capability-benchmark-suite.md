# ADR-0007: Capability benchmark — existing-codebase cases, taxonomy, and suite tracking

- Status: accepted
- Date: 2026-07-11
- Owners: Alejandro Rengifo
- Related issue: MCB expansion (this MR)
- Related ADR: [ADR-0006](ADR-0006-durable-transcript-and-honest-outcomes.md) (honest outcomes — the benchmark measures the same `approved` vs parked/incomplete signal)

## Context

The Mosaera Capability Benchmark (`packages/core/mosaera_core/bench/`) drives the
**real** governed loop — the same `build_graph` pipeline, the real `DockerSandbox`,
real role models, and the real `autonomous_resolution` gate the API worker uses —
and grades the delivered code with a deterministic scorecard (no LLM judge in the
number; the reviewer verdict is quarantined in a reported-only `signal` bucket). The
*machinery* is production-faithful and objective.

The *content* was not. The suite was two **greenfield** cases (a todo CLI, a static
landing page): both scaffold from an empty repository, both trivial tier, and the
one committed baseline sat at 97/100 — near-saturated, with no headroom to locate a
capability or detect a regression. It could show "can scaffold a small project," not
the bug-fixing, feature-extension, refactoring, and hardening of an **existing,
unfamiliar codebase** that dominate real engineering. A deep-dive (three parallel
audits of the execution path, task set, and scoring) confirmed: grounded engine,
trustworthy scoring, thin syllabus. We want a benchmark that *locates* where we
stand and *tracks* it as the engine matures.

Two structural soundness gaps also surfaced in the scorer:

- **Whole-tree craftsmanship.** The bench scored Style/Types/Complexity/Cleanliness
  over the *whole* delivered tree. Fine for greenfield (everything is new), but for
  an existing-codebase case it would judge the agent on pre-existing seed debt it
  never touched.
- **Grader-didn't-run governance fallback.** When the hidden grader could not run,
  `Governance` fell back to the run's *self-reported* `tests_passed` — a signal the
  run controls — letting a run self-certify honest delivery.

## Decision

**1. Existing-codebase cases via a committed seed repo.** A case may ship a `seed/`
directory — a real, small starting project (with its own tests) that the harness
copies, commits, and clones, so the run performs an ordinary clone with a valid HEAD
and the agent must **read before it writes**. Absent `seed/`, the harness keeps the
greenfield empty-repo path. The seam is one function (`_seed_for_case`) in the
harness; nothing else in the graph/sandbox/gate path changes, so existing-codebase
runs remain production-faithful.

**2. A capability taxonomy + difficulty tiers.** Each case declares a `capability`
(`greenfield | bug-fix | feature | refactor | robustness`) and a `tier`
(`trivial | moderate | hard`) in `case.toml`. The first expansion adds ~14
existing-codebase cases weighted to the four real-world capabilities across moderate
and hard tiers (~~the two greenfield cases remain the trivial floor~~ — **corrected 2026-08-18**,
`docs/audits/adr-corpus-review-2026-08-18.md`: MCB-01 ships no `case.toml` and MCB-02's declares neither
field, so both predate the taxonomy, and no case currently uses the `trivial` tier). The set is
Python-first; other languages/domains are a later expansion.

**3. Case soundness is proven offline.** A case ships a `reference/` overlay (a
known-good solution) used *only* by an offline self-test
(`tests/test_bench_cases.py`, part of `make test` — no model, no Docker). For every
seed case it asserts the two invariants that make the grader trustworthy: the hidden
grader **fails on the bare seed** (so a do-nothing run cannot score) and **passes on
the reference** (so the case is winnable). Refactor cases — whose behaviour is
preserved, so behavioural tests pass on the untouched seed — carry an additional
**structural** grader assertion (via `ast`: the function is decomposed / delegates to
N helpers / the long branch ladder is gone) that fails on the seed.

**4. Suite rollup + trend log.** `bench/suite.py` aggregates the per-case scorecards
into a capability × tier matrix, per-capability means, a suite headline, and a
delivery count, and appends a compact row to a history log
(`.mosaera/benchmarks/_suite/history.jsonl`) each run — the "are we maturing"
signal. `mosaera-bench --all` prints the matrix and writes the rollup.

**5. Two scorer corrections.** Craftsmanship is now scored over the run's **changed
files** (from the diff), not the whole tree, so a case is judged only on what the
agent wrote (equivalent for greenfield, fair for seed cases). When the hidden grader
did not run, ground truth is **unknown**: `Governance` is now **N/A** (it drops out
of the weighted mean) rather than trusting the run's self-reported `tests_passed`.

## Options considered

- **Vendor slices of real OSS repos as seeds.** Rejected for the first tranche:
  license/attribution burden, non-determinism, network/deps, and uncontrolled
  difficulty. Synthetic-but-realistic in-repo seeds are deterministic, license-clean,
  and let us dial difficulty precisely. Real-repo cases remain a future option.
- **LLM-judged acceptance / partial credit.** Rejected — it would put model opinion
  into the number. Acceptance stays a deterministic hidden pytest suite; the sole
  LLM signal (the reviewer verdict) stays reported-only.
- **Grade a refactor by behaviour alone.** Rejected — behaviour is preserved by a
  refactor, so the grader would pass on a do-nothing run. Hence the structural
  assertion. It is an objective proxy (decomposition/complexity), not a proof of
  "good taste"; acknowledged as such.
- **Keep whole-tree craftsmanship / keep the self-report fallback.** Rejected as the
  two soundness gaps above.

## Security implications

Low, and net-positive for honesty. Case fixtures (`seed/`, `grader/`, `reference/`)
are excluded from the repo's ruff/mypy/pytest (they import modules that only exist in
a run workspace) — they are data, never imported by the product. Seeds are
stdlib-only and self-contained (no network, no third-party deps), so a seed cannot
smuggle egress or supply-chain surface into a run; the sandbox containment from
TM-0001 is unchanged. The governance-fallback fix removes a way a run could
self-certify success when its work was unverifiable.

## Operational implications

- **Baselines are regenerated by the operator** on a machine with a model + Docker
  (`mosaera-bench <CASE> --update-baseline`, or `--all`), then committed under
  `bench/baselines/`. The moved-to-changed-files craftsmanship scoring shifts the
  existing MCB-01 baseline slightly, so baselines should be refreshed. Local models
  are expected to *fail or park* the hard cases — that is the intended signal and the
  headroom the old suite lacked; an honest low score on a hard tier is a correct
  reading, not a regression.
- `make test` now proves every seed case's grader is sound offline, so a broken case
  is caught in CI without a model or a daemon.
- Adding a case is a documented, self-validating recipe
  (`bench/cases/README.md`): brief + seed + hidden grader + reference, gated by the
  two invariants.

## Consequences

The benchmark can now locate capability across real-world task types and difficulty,
and the suite rollup + history make maturation trackable release over release. The
headline is still a deterministic, gaming-resistant measure of "did it deliver
working code" — Implementation (×3) is a real hidden acceptance suite, Governance
(×2) punishes shipping broken work, and neither can be inflated on a non-working
deliverable. The ceiling of any single case reflects its grader's depth (sound but
finite), so the suite's value grows with case count and coverage; this ADR
establishes the structure to keep adding cases cheaply and safely.
