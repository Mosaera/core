# `sandbox-e2e` green by vacancy — root cause (#58), 2026-08-04

**Verdict: the CI Postgres service was the wrong image.** `.gitlab-ci.yml` and
`.github/workflows/ci.yml` both declare stock `postgres:16`, which does not ship **pgvector**. The
memory store's `init()` runs `CREATE EXTENSION IF NOT EXISTS vector`
(`packages/memory/mosaera_memory/store/_base.py:262`) and its models map `Vector(768)`
(`models.py:13,387`), so the DDL raised on every connection attempt, every `requires_db` test
self-skipped, and the job reported success. Docker was never implicated.

The local dev container is `pgvector/pgvector:pg16`. CI is `postgres:16`. That one-word divergence
is the whole defect, and it hid for **~7 weeks** (since `079899a0`, 2026-07-16).

## The evidence, in one line

Pipeline **#828**, the first run with the gate instrumentation:

```
------------------------------ integration gates -------------------------------
  mode: MOSAERA_INTEGRATION=skip (missing = skipped)
  requires_docker: AVAILABLE
  requires_db: UNAVAILABLE — database at MOSAERA_TEST_DB_URL is unreachable or unmigratable:
    NotSupportedError('(psycopg.errors.FeatureNotSupported) extension "vector" is not available
    DETAIL: Could not open extension control file
      "/usr/share/postgresql/16/extension/vector.control": No such file or directory.')
1401 passed, 116 skipped
```

Before the instrumentation the same job said only `1398 passed, 116 skipped` and `Job succeeded`.
The issue recorded the root cause as *"not yet established … both could be failing"*; one
instrumented run answered it, which is the argument for diagnosing before fixing.

## Counts

| run | passed | skipped |
|---|---:|---:|
| CI #826 (pre-instrumentation) | 1398 | 116 |
| CI #828 (instrumented, cause named) | 1401 | 116 |
| local, same selection, services up, `required` | **1515** | **2** |

**114 recoverable tests had never executed in CI.** All 114 pass — nothing was hiding behind the
vacancy, but nothing was watching either. The 2 residual skips are by design
(`MCB-26: kind 'sql' is not host-gradeable`; on the CI host also `MCB-23: no 'node' for the node-cli
grader`).

## Why it stayed invisible for seven weeks

1. `addopts = "-q …"` suppressed skip **reasons**, so a vacant run and a real one logged identically.
2. The gates were **eight copy-pasted `skipif`s**, each probing at its own module import, and each
   `_reachable()` swallowed its exception whole — the `FeatureNotSupported` above existed on every run
   since July and was never printed once.
3. Nothing asserted a run/skip count. pytest's exit-5 cannot fire while ~1400 ungated tests pass.
4. The job config *looked* right — it builds all four images, declares a Postgres service, sets
   `MOSAERA_TEST_DB_URL`, has no `allow_failure`. Static review could not see this; only inspecting
   what actually executed could. Same shape as the ADR-0070 ★ LESSON.

## The fix, in the order it must be applied

**Order matters.** Setting `MOSAERA_INTEGRATION=required` before correcting the image would make
`sandbox-e2e` permanently red — correctly, but unhelpfully.

1. **Correct the service image** (CODEOWNERS-protected, both files):
   `postgres:16` → `pgvector/pgvector:pg16`, matching the dev container.
2. **Then arm the gate:** `MOSAERA_INTEGRATION: required`, so the job can never again pass by not
   running its tests.

**Applied and MEASURED (pipeline #832).** `mode: MOSAERA_INTEGRATION=required (missing = error)` ·
`requires_docker: AVAILABLE` · `requires_db: AVAILABLE` · **1507 passed, 10 skipped** — against 1398
passed / 116 skipped before. **109 tests that had never executed in CI now run, and all pass.**

Every remaining skip is by design and named in the log: 2 × MCB-23 (the host has no `node` for the
node-cli grader), 2 × MCB-26 (`sql` is not host-gradeable), and 6 × SqlPack requiring a non-root
sandbox — the distinction deliberately preserved when the gates were centralised, since CI sets
`MOSAERA_SANDBOX_USER=root` and Postgres refuses to `initdb` as root. Had those been treated as
missing preconditions rather than a by-design incompatibility, this job would now be red for no good
reason.

*Prediction accuracy, for the record:* ~1515 passed / ~2 skipped was forecast from the local floor.
Actual 1507 / 10 — the local measurement could not see the CI-specific by-design skips (no `node` on
the runner, sandbox-as-root). The direction was right; the floor was three classes deeper than one
machine could show.

Note the originally proposed `pg_isready` precondition would **not** have caught this: the server was
up and accepting connections the whole time. The failure was one DDL statement deeper. A liveness
check has to probe the thing the tests actually need, not a proxy for it.

## Landed in this pass (unprotected files, MR !323)

`-rs`; a gate summary printed on **every** run; the gates centralised into two markers probed once
with the underlying exception carried into the reason; `MOSAERA_INTEGRATION=required` honoured;
`test_integration_gates.py` pinning skip / error / opt-in.

## The invariant

*Evidence-Gated Advancement*, turned on our own instruments. A control point that cannot fire is not
a control point — and for seven weeks this one reported success for work it never did. The rule that
replaces it is ADR-0081's, in its own words: **absence of evidence is not evidence.**
