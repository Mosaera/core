# ADR-0054: Whole-suite validation — let pytest discover, don't hard-code `tests/`

- Status: accepted
- Date: 2026-07-17
- Owners: Mosaera core
- Related issue: #45 (run-reliability arc #43)
- Related threat model: TM-0001 (the delivery gate / oracle)

## Context

The #43 reliability scoreboard's first baseline (ADR-0053): clean-conclusion **83.3%** (20/24), and
**3 of the 4 failures were `false_ship`** — delivered green, but the hidden grader fails. The biggest
lever toward ~99%.

Root cause: `PythonPack._pytest_plan` ran `pytest -q tests` whenever `tests/` held a test — so **every
test outside `tests/` never executed**. The live trigger (`20260717-190135`): a root-level
`test_password_persistence.py` encoding an old contract was never run, a change regressed it, and the run
shipped green. The `tests/`-scoping had been a workaround for a fixtures-only-`tests/` false-fail and
over-corrected into this false-ship.

## Decision

Validate with **pytest's own config-driven discovery** — run `pytest -q --import-mode=importlib` from the
workspace root with **no hard-coded `tests/` scope and no synthesized path args**. Bare `pytest`
discovers the whole tree (`tests/`, the root, any dir), so a test anywhere is validated, while
**honoring the repo's own `testpaths` / `python_files` / `norecursedirs`** and pytest's defaults (which
skip `.venv` / `node_modules` / `build` / `dist` / `venv`). `--import-mode=importlib` gives each test file
a path-unique module name so same-basename files across dirs (`tests/test_utils.py` + a root
`test_utils.py`) don't clash under pytest's default `prepend` import mode.

This is a **scope** fix, not a new oracle: once the whole suite runs, a regressing out-of-scope test
fails → `tests_passed=False` → `validation_failed` → the run parks. No gate/policy change; the plan stays
`strength="suite"`. It also fixes the original fixtures-only-`tests/` false-fail for free (root tests are
discovered).

## Options considered

- **Config-driven bare `pytest` (CHOSEN).** pytest already discovers the whole suite from rootdir,
  honors the repo's config, and reads the real filesystem. `--import-mode=importlib` closes the
  duplicate-basename case. Simplest (no discovery code).
- **Deterministic path discovery from the pristine listing (BUILT FIRST, then REVERTED by red-team).**
  A helper synthesized explicit pytest path args (containing dirs + root files, vendored dropped). The
  pre-merge red-team (below) proved this is *strictly worse* than bare pytest: passing explicit CLI paths
  **overrides the repo's `testpaths`/`python_files`**, reads a **300-file-capped** listing (a large repo's
  test tree can be truncated out → the regression is skipped → false-ship), and **collides on duplicate
  basenames**. It was reverted in favor of the option this ADR originally rejected.

## Red-team disposition (the oracle/validation scope is a trust boundary)

Three refute agents, one round; all three converged on one root class — *"synthesizing explicit pytest
path args is worse than pytest's own config-driven discovery."* Disposition:

- **`testpaths`/`python_files` override → false-park on committed `examples/`/`vendor/` tests** (proven):
  **FIX-NOW** — the redesign to bare `pytest` honors the repo's config, so it never runs out-of-scope
  foreign tests. End-to-end test added.
- **Duplicate-basename `import file mismatch` → false-park** (proven, a common layout): **FIX-NOW** —
  `--import-mode=importlib`. End-to-end test added.
- **300-file listing truncation → the real suite skipped → false-ship** (proven): **FIX-NOW** — bare
  pytest reads the disk, not the capped listing.
- **`_VENDOR_DIRS` "aligned with pytest norecursedirs" was false** for `site-packages`/`_mcb_grader`, and
  a first-party dir literally named `build`/`dist` was silently excluded: **MOOT** — `_VENDOR_DIRS` is
  deleted with the discovery helper; pytest's own `norecursedirs` governs recursion.
- **Command shape / relative-path resolution / oracle double-count / `testpaths`-re-skip-via-fallback:**
  **FALSE-POSITIVE** (verified — the authored-suite oracle path is untouched; there is no fallback branch
  now).

## Security implications

Narrows the top measured false-ship class. Deny-by-default holds — an ambiguous case runs *more* and a
failure parks. **Residuals (accepted, deny-by-default):** a *no-config* repo that commits broken
`examples/`/`vendor/` tests (no `testpaths` to scope them out) runs them → false-park (the safe side; the
author declared no scope). `--import-mode=importlib` could, rarely, false-park a repo that depends on
`prepend`-mode `sys.path` insertion — again the safe side. A first-party test dir named `build`/`dist`/
`venv` is skipped by pytest's own defaults (unchanged pytest behavior, not this change).

## Operational implications

No migration, no config, no new dependency. Behavior-preserving for the common shapes (the false-park
regression corpus passes unchanged); the intended change is that tests outside `tests/` now run and the
repo's own pytest config is honored.

## Consequences

- **Good:** the top false-ship class is closed with *less* code; a green run now means the repo's whole
  configured suite passed. Empirically proven: a failing root test fails validation; a `testpaths`-scoped
  repo doesn't false-park on a broken `examples/`; duplicate basenames don't collide.
- **Follow-up:** re-run `mosaera-bench --all` and confirm `false_ship` drops toward 0 and the
  clean-conclusion rate rises from 83.3%.
