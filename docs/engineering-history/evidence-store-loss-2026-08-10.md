# The evidence store was destroyed by a convenience symlink (2026-08-10)

**Status: RECORDED, UNRECOVERABLE, mechanism IDENTIFIED and CLOSED 2026-08-11 (`4e61c6c`) — after it
recurred.** Roughly 2,500 benchmark scorecards, the run checkpoints,
`settings.json` and the workspace tree under `<repo>/.mosaera/` were lost. This record exists so the
cause is not re-derived and the residual exposure is not forgotten.

## What happened

While setting up the control-liveness audit, a git worktree was given a symlink to the **live**
evidence store so the audit script could be run without passing `--home` on every invocation:

```
cd /path/to/worktree && ln -sfn /path/to/main/.mosaera .mosaera
```

The full test suite was then run in that worktree. Afterwards the main checkout's `.mosaera` was a
**47-byte regular file** containing its own path, and the directory was gone.

The operator (an AI agent) created the symlink for convenience. There was no backup.

## The mechanism — reconstructed 2026-08-11 (this section supersedes the original "not reconstructed")

This record originally declined to guess at the write. **It has now been identified, and reproduced
deterministically.** It was not the test suite and not a stray application write. It was `git`:

1. The symlink was **committed** — accidentally, as an unrelated side effect of `a9f7fe3`, the
   control-liveness audit commit itself.
2. `.gitignore` read **`.mosaera/`**. A trailing slash matches a *directory only*, so a **symlink**
   of that name was never ignored and `git add -A` swept it in without comment.
3. This repository carried **`core.symlinks=false`** — WSL-era residue; the box has been native
   Linux since 2026-07-28. Under that setting git does not create a symlink on checkout. It writes
   a **regular file containing the target path** — 47 bytes, exactly what was found.

So any `git checkout` or `git merge` of a branch carrying that blob silently replaced the live
evidence store with a text file. No warning, no error, nothing to notice.

**Reproduced 2026-08-11.** A routine `git merge` of `docs/evidence-store-exposure` into `staging`
replaced the freshly rebuilt 125-card corpus with the identical 47-byte stub. It was recovered in
full only because a backup had been taken hours earlier. The bug outlived the incident that
disclosed it by one day, because the corrective action taken on 2026-08-10 addressed the *operator
behaviour* (never link a working area at live data) and the committed blob was never noticed.

**Corrected on 2026-08-11** (`4e61c6c`): `git rm --cached .mosaera`; the ignore rule lost its
trailing slash; `core.symlinks=true`; and a guard test with its own positive control
(`packages/core/tests/test_evidence_store_not_tracked.py`) that fails if the store is tracked, if
any form of the path is un-ignored, or if `core.symlinks` is false off-Windows.

**The lesson is narrower and sharper than the original one.** "Do not link a working area at live
data" was true but insufficient — by the time it was written the damage was already *committed*, and
a prose rule in `CLAUDE.md` cannot detect a blob in the index. What was missing was a mechanical
check. This is the session's recurring shape one more time: a control that existed only as a
statement, believed to be in force, with nothing that could observe it failing.

## What was lost, and what survived

| lost | survived |
|---|---|
| ~2,500 scorecards — the whole measurement corpus | **25 regression baselines**, committed under `packages/core/mosaera_core/bench/baselines/` |
| `runs/` checkpoints, `workspaces/`, `projects/`, reports and logs | `docs/engineering-history/` — the *conclusions* of every past measurement |
| `settings.json` (model config + a plaintext provider key) | 29 cards in a sibling worktree (that day's ADR-0099 corpus verification) |

**Regression detection was not lost.** `mosaera-bench --compare` reads the committed baselines, so
the capability that guards against regressions is independent of the store. That was luck rather
than design, and it is the single most important structural fact in this record.

## Recovery: none existed

The host runs a filesystem with automatic snapshots, so recovery looked plausible. It was not: the
snapshot configuration covered the root subvolume only, and the working tree lives on a separate
subvolume with no configuration and no snapshots. There was no point-in-time protection anywhere the
work actually lives.

**The finding is larger than this incident.** Hundreds of snapshots created an impression of safety
that did not extend to the data being protected. Recorded here because "we have snapshots" was
believed and untested — the same shape as the five inert controls found the same day: a mechanism
credited for coverage it never had. The gap is closed by giving the working subvolume its own
snapshot configuration.

## What the loss actually costs

The conclusions survive; the ability to **re-derive** them does not. Figures such as the 45-of-61
no-op escalations, the 34% over-park rate, the 50-run `oracle_unverified` sole-cause population, and
`critic_vetoed` falling 13% → 0% now rest on written records rather than on data anyone can re-query.

In a project whose central discipline is *do not trust a number you cannot re-check*, that is the
real damage — larger than the disk space and not fixed by re-running anything, because the
longitudinal facts concern a version boundary that no longer exists.

**Re-derivable cheaply:** current-state rates. One `--all --repeat 2` is ~50 runs and about two hours,
and it is *methodologically better* than what was lost — every figure derived from the old corpus
carried the caveat that it pooled many code versions, whereas a fresh sweep is single-version.

**Not re-derivable at all:** anything longitudinal. Of the two that mattered, one is already actioned
(the escalation defect is fixed and merged) and the other is better answered by a positive control
than by corpus archaeology — which is what the control-liveness work was already moving toward.

## Why nothing caught it

Every control in this system watches the **delivered code**. None watches the **record**. A run that
destroys the evidence store still reports a clean gate, because the gate has no opinion about the
store it writes to.

That is the same shape as the five inert-mechanism findings from the same day: the thing that records
the truth is less protected than the thing being judged.

## What changed as a result

- **Threat model** — the evidence store is now a named asset in
  [TM-0001](../threat-models/TM-0001-mosaera-lite-repo-agent.md), with a threat row recording that it
  is cwd-relative, holds credentials, is the *parent* of the sandbox's writable area, and that its
  destruction is invisible to every gate.
- **Execution contract** — `CLAUDE.md` gained the operating rule: never create a writable path from a
  working area to live data; pass an explicit destination to anything that writes; back up
  irreplaceable state before running anything that could write to it.
- **Product** — every run record now stores the **absolute resolved** evidence-store path it wrote
  to, so a misdirected write becomes detectable after the fact. Recording before enforcement.

## What did NOT change, deliberately

**Refusing a symlinked or unexpected home was considered and not taken.** It would have prevented
this incident outright, but it risks breaking legitimate deployments that place `MOSAERA_HOME` on
other storage, and no evidence exists about how operators actually deploy. Enforcement without that
evidence would be the same premature move this project has recorded elsewhere.

**The exposure is therefore still open.** There is no backup, no retention policy and no integrity
check on the evidence store. The recorded-home field makes a misdirected write *diagnosable*; it does
not make it *impossible*. Both remain open questions.
