# Benchmark baselines

Committed capability baselines, one `<CASE>.json` per benchmark case, used by
`mosaera-bench <CASE> --compare` (a.k.a. `make bench-compare <CASE>`) to catch
capability/cost regressions.

These live in-repo (not under the git-ignored `.mosaera/`) so a baseline travels
with the code that produces it.

## Workflow

1. On a machine with a model (e.g. `MOSAERA_OLLAMA_BASE_URL=https://ollama.rengifo.me`)
   and Docker, generate/refresh a baseline (averaged over 3 runs by default):

   ```
   uv run mosaera-bench MCB-01 --update-baseline
   ```

2. **Review the scorecard, then commit** `baselines/MCB-01.json`. A baseline is a
   deliberate record of "this is the capability/cost we expect" — never auto-commit it.

3. Before a release, run `make bench-compare MCB-01` (or `--all`). Scores are
   sampling-noisy, so the compare tolerates a small drop (default: −5 points per
   score, +25% cost) and averages runs; it exits non-zero only on a real regression.

## The full suite

The suite now spans a capability taxonomy (`greenfield | bug-fix | feature |
refactor | robustness`) across difficulty tiers (`trivial | moderate | hard`); see
`../cases/README.md`. Generate/refresh every baseline and see the capability picture
with:

```
uv run mosaera-bench --all --update-baseline
```

`--all` prints a **capability × tier matrix** and a suite headline, and writes the
rollup + a `history.jsonl` trend row under `.mosaera/benchmarks/_suite/`. Expect a
spread, not a flat 97: the hard tiers exist to have headroom, and a local model
honestly failing or parking a hard case is a correct reading — commit the baseline
that reflects reality, then watch the matrix move as the engine matures.

Every case's grader is proven sound (fails-on-bare, passes-on-reference) so a baseline
only ever records model/engine capability, never a broken grader: the Python/Node
graders host-side in `packages/core/tests/test_bench_cases.py` (part of `make test`,
where the toolchain exists), and the SQL grader — which needs a live Postgres — in the
docker-gated `test_langpack_e2e.py` (GitLab `sandbox-e2e` + locally).

## Cross-language cases (MCB-23 Node/TS, MCB-26 SQL)

These grade on the per-language sandbox images (`mosaera-sandbox-node:dev` /
`-sql:dev`), so generating their baseline needs those images built (`dev-up.sh`) in
addition to a model + Docker. Their scorecards are cross-language (Style/Types/etc. go
N/A where a Python-specific dimension doesn't apply), so read them on their own terms,
not against the Python cases. Baselines are **model-specific** — regenerate them on your
canonical model/endpoint rather than trusting a baseline produced elsewhere.
