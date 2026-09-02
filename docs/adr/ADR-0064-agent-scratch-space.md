# ADR-0064: The agent scratch space — the first workbench opening

- Status: accepted
- Date: 2026-07-19
- Owners: Mosaera core
- Related: ADR-0063 (capability through auditability — this is sub-arc 1, the `/scratch` mount),
  ADR-0059 (`#55` coder toolkit — the read-only probe this complements), issue `#59`.
- Trust boundary: RELAXES the coder's write-refusal for one namespace and touches the delivery
  computation → red-team REQUIRED (ADR-0063: each opening is its own red-teamed MR). Done (below).

## Context

ADR-0063's cheapest, highest-leverage opening. The `#55` trace found the coder smuggling debug scripts
into `tests/` because it had no sanctioned scratch space — the harness had stripped the workbench a
capable engineer needs. Give it one: **a writable, ungated, never-shipping, logged scratch dir**, with
the *delivery boundary* (not process-restriction) as the safety mechanism.

## Decision

The scratch space is **`.mosaera/scratch/`** inside the run clone — a workspace directory, NOT a Docker
tmpfs. (`.mosaera` is already in `workspace._SKIP_DIRS`, so it is auto-hidden from listing/search/tamper;
namespaced, so it can't collide with a target repo's own `scratch/`; and the "excluded from the
deliverable diff" requirement points at a workspace dir, since a tmpfs is ephemeral-per-exec and would
drag in the CODEOWNERS `infra/` Dockerfiles + the WSL mount gotcha.)

- **Writable, any name.** `_disallowed_scratch` (`tools/repo/factory.py`) exempts paths under
  `.mosaera/scratch/`, so the coder may write `debug_*.py` / fixtures / notes there — the refusal still
  guards the shipped tree. Gated by `coder_scratch_enabled` (default on, posture-tunable).
- **Never shipped or graded — enforced at the DELIVERY SEAM (load-bearing).** `workspace._stage_all`
  does `git add -A` then `git reset -q -- .mosaera`, and `commit_all` additionally asserts no
  `.mosaera/` path is staged (`_assert_no_scratch_staged`) — **failing closed**. `.git/info/exclude`
  (`clone.py`, now root-anchored `/.mosaera/`) is only a *first* layer; it is NOT the guarantee (see
  red-team). Because grading parses `diff_all()`, this one seam covers both delivery and grading.
- **Never collected by validation.** `--ignore=.mosaera` is added to the whole-suite pytest args
  (`languages/python.py`) and the coverage run (`coveragemap.py`), so a scratch `test_*.py` cannot be
  collected regardless of the untrusted repo's `norecursedirs` (see red-team).
- **`.git/` is off-limits.** `_scope_reason` refuses any write under `.git/`, so the coder cannot edit
  `.git/info/exclude` (defense in depth for the first layer).
- **Logged.** Scratch writes/edits emit a distinct `scratch_write` activity (path-level; full
  content-audit is the ADR-0063 audit-log sub-arc, `#61`).
- **The coder contract.** The persona (`coder_system`) directs throwaway files to `.mosaera/scratch/`
  and away from `tests/`/the source tree — the behavioural fix for the `#55` abuse.

## Red-team disposition (2 adversarial passes, pre-merge)

**Two CONFIRMED FIX-NOW — both fixed + regression-tested; the design's original single mechanism was
insufficient:**

- **Delivery escape (HIGH):** the coder writes a `.gitignore` with `!.mosaera/` — which **outranks**
  `.git/info/exclude` in git's precedence — and `git add -A` then ships the scratch content (proven
  end-to-end). A pre-tracked source `.mosaera/scratch/` file (info/exclude covers only *untracked*
  paths) is a second vector. **Fix:** move enforcement to the delivery seam (`_stage_all` reset +
  fail-closed assertion), which defeats both. Regression tests:
  `test_scratch_gitignore_negation_cannot_ship`, `test_pretracked_source_scratch_cannot_exfil`.
- **Oracle poisoning (MEDIUM):** the run's validation invokes bare `pytest` from the workspace root, so
  collection is governed by the untrusted repo's `norecursedirs` — which *replaces* pytest's default
  `.*` prune. A repo that overrides it makes pytest collect `.mosaera/scratch/test_*.py`, letting a
  throwaway scratch test fake-red/green the oracle. **Fix:** `--ignore=.mosaera` (additive; does not
  override the repo config, per ADR-0054). Test: `test_pytest_plan…` asserts the flag.

**REFUSED (guards held):** `.git/` case/normalization bypass, symlink escape, `.mosaera/scratch/` prefix
escape, scratch-exemption widening past scope/protected/`write_prefix`, and `sandbox_exec` + scratch
persistence/exfil.

**LOW (fixed):** over-broad `.mosaera/` match at nested depth → anchored to `/.mosaera/`;
`quality._EXCLUDE` gained `.mosaera`; `edit_file` now tags scratch writes too.

**ACCEPT (documented residual):** an explicit `--test-cmd` CLI override bypasses the LanguagePack
`--ignore` (user-owned command; the autonomous/API/bench paths use the default plan and are covered). A
source that *pre-tracks* an unchanged `.mosaera/scratch/` file ships it unchanged (its own content, not
coder exfil; the seam blocks any coder modification).

## Consequences

- The coder gets the scratch workbench a real engineer has, and the `#55` `tests/`-abuse is closed by a
  sanctioned alternative — capability up, with the delivery boundary + audit as the safety, not
  process-restriction (ADR-0063 in practice).
- **The containment guarantee is the delivery seam, asserted and fail-closed** — not git's ignore
  precedence, which the coder can outrank. This is the reusable lesson: enforce at the boundary where
  delivery happens, positively, rather than trusting a layered default.

## Rejected

- **A Docker `--tmpfs /scratch`** — ephemeral-per-exec (doesn't solve persistent experimentation),
  needs the CODEOWNERS `infra/` Dockerfiles, and inherits the WSL `/mnt/c` mount gotcha.
- **Relying on `.git/info/exclude` alone** — red-team-confirmed insufficient (a `.gitignore` negation
  outranks it; it misses tracked paths). Kept only as a cosmetic first layer.
- **Relaxing the guided-mode write-gate for scratch** — deferred (autonomous doesn't need it; keeping
  the gate shrinks the trust-boundary surface).
