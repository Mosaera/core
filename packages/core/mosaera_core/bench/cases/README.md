# MCB benchmark cases

Each case is a self-contained task the governed loop is run against. A case is a
directory `MCB-NN/` with a fixed layout. Cases are **fixtures**, excluded from the
repo's ruff/mypy/pytest (see the root `pyproject.toml`), so they may import modules
(`metrics`, `checkout`, …) that only exist inside a run workspace.

## Layout

```
MCB-NN/
  brief.md      # the task handed to the agent (the only thing it sees)
  case.toml     # kind / capability / tier / budgets
  seed/         # the STARTING repo — cloned into the workspace; the agent reads it
  grader/       # HIDDEN acceptance suite (pytest); injected at grade time only
  reference/    # a known-good solution OVERLAY; used ONLY by the offline self-test
```

- **Greenfield** cases (MCB-01, MCB-02) omit `seed/` and `reference/`: the agent
  scaffolds from an empty repo. Everything else ships a `seed/`.
- `seed/` is a real, working (or deliberately-buggy) small project, ideally with its
  own `tests/` so the agent has context. It must be clean, self-contained, and
  standard-library-only unless the case is specifically about dependencies.
- `grader/` is the ground truth. It is **never** shown to the agent. It is injected
  as `_mcb_grader/` at grade time and run with the workspace as cwd, so it imports
  the delivered code by its real module name.
- `reference/` is an **overlay**: its files are copied on top of `seed/` to produce
  the solved state. Include only the files that change. It is never used in a real
  run — only the self-test uses it to prove the grader is sound.

## case.toml

```toml
kind = "python"          # "python" | "python-cli" | "static-site"
capability = "bug-fix"   # greenfield | bug-fix | feature | refactor | robustness
tier = "moderate"        # trivial | moderate | hard
max_iterations = 6
budget_usd = 1.0
budget_tokens = 400000
budget_iterations = 6
```

`kind = "python"` (or `python-cli`) makes the craftsmanship/testing scorecard
dimensions apply. `capability`/`tier` place the case in the suite rollup matrix.

## The two soundness invariants (enforced offline by `tests/test_bench_cases.py`)

Every case with a `seed/` + `reference/` MUST satisfy both — a case that violates
either is not trustworthy:

1. **The grader FAILS on the bare seed.** The target behaviour/structure is genuinely
   absent, so a do-nothing run cannot score Implementation=100. For bug-fix /
   feature / robustness this is automatic (the behaviour is missing). For **refactor**
   the behavioural tests pass on the seed too, so the grader MUST also assert a
   structural property (e.g. via `ast`: the function is decomposed, delegates to
   >= N helpers, the long if/elif chain is gone) that fails on the seed.
2. **The grader PASSES on the reference.** A correct change actually satisfies it, so
   the case is winnable.

Validate a case offline (no model, no Docker) with:

```
uv run --no-sync pytest packages/core/tests/test_bench_cases.py -k MCB-NN -q
```

Author graders as behavioural black-box tests where possible (drive a CLI via
subprocess, or call the public API and assert results), independent of and broader
than the seed's own visible tests — so a run that games the visible test (deletes /
weakens it) still fails here.

## Baselines

Baselines are generated on a machine with a model + Docker (`mosaera-bench MCB-NN
--update-baseline`) and committed under `bench/baselines/`. See that directory's
README. The suite rollup (`mosaera-bench --all`) prints the capability x tier matrix
and writes it under `.mosaera/benchmarks/_suite/`.
