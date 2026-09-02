# Runbook: releasing a version — the CONOPS

**What this is.** The operational *when / who / how* of moving the engine's version and maturity
channel. The *what and why* live in the decisions and are not restated here:

- [ADR-0055](../adr/ADR-0055-engine-versioning.md) — the versioning scheme (`0.x`, maturity-anchored,
  single source of truth, PATCH-per-arc after `0.6.0`, benchmark-snapshotted CHANGELOG).
- [ADR-0088](../adr/ADR-0088-engine-maturity-channel.md) — the maturity channel and its ladder.
- [ADR-0061](../adr/ADR-0061-v1-measured-definition-of-done.md) — the four measured gates that define
  `1.0`.

**Current state** is not duplicated here either — read it from the engine:

```bash
uv run python scripts/bump_version.py --check     # e.g. "Version consistency OK: 0.6.0 (beta) across 9 files."
uv run mosaera --version                          # e.g. "mosaera 0.6.0 (beta)"
```

---

## 1. What earns which digit

Versions are **monotonic** and never renumber downward — `__version__` is stamped into run receipts
(`make_receipt_id`), the benchmark trend `.mosaera/_suite/history.jsonl`, and the
`runs.engine_version` column, all of which depend on the ordering.

| Move | What earns it | Frequency |
|---|---|---|
| **PATCH** `0.6.0 → 0.6.1` | A **completed arc** — an issue/wave closed with its acceptance criteria met. Not a merge, not an MR. | The normal case |
| **MINOR** `0.6.x → 0.7.0` | An [ADR-0061](../adr/ADR-0061-v1-measured-definition-of-done.md) **v1.0 gate goes green** on a held-out run. MINOR is *rationed* toward `1.0` (ADR-0055 amendment 2026-07-23) — a good arc does not earn one. | Rare, ~4 times total |
| **MAJOR** `→ 1.0.0` | **All four** ADR-0061 gates simultaneously green on one held-out benchmark run. | Once |

The version is always a plain `X.Y.Z`. **Never** a pre-release suffix — maturity lives in
`__maturity__`, and a SemVer-style `0.6.1-beta.1` is invalid PEP 440 that `uv` silently normalizes to
`0.6.1b1` in metadata while the source keeps the hyphen. `bump_version.py` rejects it; so does
`test_version_is_a_plain_release_not_a_prerelease`.

## 2. What earns a maturity move

Independent of the number, on ADR-0088's ladder: `alpha` → `beta` → `rc` (3 of 4 gates) → `stable`
(all four ⇒ `1.0.0`). A channel move needs the **same** evidence a version bump needs (§3) — it is a
claim about the engine, and *Evidence-Gated Advancement* applies to those too.

## 3. The evidence a release requires

**A bump without a benchmark snapshot is not a release.** The CHANGELOG entry must name:

- **the suite** (e.g. MCB ×3), **the run count** (e.g. 72 runs), and **the posture configuration**
  (oracle setting, sensitivity, escalation on/off);
- the outcome buckets and the clean-conclusion rate, compared against the previous release;
- for any `false_ship` claim, the residual rate **as a bound on that named distribution** — read by
  the rule of three (~3/n at 95% when the observed count is 0). Per the ADR-0061 gate-2 amendment, *a
  rate is only a result when the distribution it bounds is named*; "≈ 0" with no n and no
  configuration is the failure mode that amendment exists to close.

Run the benchmark **before** merging the bump, not after. The 0.6.0 release found a mechanism-killing
truncation bug precisely because the benchmark ran first.

## 4. Who authorizes

The **owner**. A version number and a maturity channel are outward claims about the system's
trustworthiness; no agent, and no green pipeline, grants one. CI *verifies* consistency and that a
bump carries a CHANGELOG entry — it never bumps and never tags (*Deterministic Final Authority*).

## 4b. Where the cadence actually stands — RESOLVED 2026-08-08 by `0.6.1`

`0.6.0` stood from 2026-07-19 while several arcs closed. The first bump under this SOP was gated on
two conditions. **One of them was a bad criterion, and saying why is the point of keeping this
section.**

- **The benchmark condition was right and was met.** MCB ×3 = 72 runs, 2026-08-08, snapshot in the
  CHANGELOG per §3. §5's *run the benchmark first* held.
- **The item-88 condition was wrong, and it was wrong in a way this repo now has a name for.** The
  gate read *"LedgerCLI item 88 delivering."* Item 88 was **unreachable**: its acceptance required
  untracking a git file, which no tool performs. It was driven five times for ~2.9M tokens and could
  never have delivered — the engine's correct behaviour was to refuse, and on the fifth drive an
  operator correctly declined to amend the blocking test, because authorizing it would have used a
  human signature to weaken a bar to fit a capability gap. Gating a release on an impossible event
  makes the release condition unfalsifiable, which is the failure this runbook exists to prevent.
  The finding became [ADR-0089](../adr/ADR-0089-intake-reachability.md); the whole class became
  #82.

**The rule this replaces it with:** a release condition must name **evidence the engine can produce**,
not an outcome it may be structurally unable to reach. A specific item delivering is a fine
*milestone* and a bad *gate*. Prefer a measured distribution over a single run.

- **The check itself was not trustworthy until 2026-08-07.** `verify_record` had four
  return-0-on-unavailable paths and **zero test coverage**, and its single CI run was vacuous — the
  version had not moved, so it took the `old == new` exit. `--strict` (which CI now passes) makes
  every "could not look" a failure there; local runs stay lenient. The four missing tests exist.

## 5. The procedure

```bash
# 0. Branch. (If another session holds `staging`, branch off `main` in a separate worktree.)
git switch -c release/vX.Y.Z

# 1. Run the benchmark and capture the snapshot. This comes FIRST — it may change the answer.

# 2. Move every version string at once. --maturity only if the channel is also moving.
uv run python scripts/bump_version.py X.Y.Z [--maturity alpha|beta|rc|stable]
#    Rewrites: mosaera_core/__init__.py, all 7 workspace pyprojects, apps/web/package.json,
#    and inserts a CHANGELOG heading with the snapshot left as an explicit TODO.

# 3. Fill in the CHANGELOG entry — the headline and the §3 snapshot. Do not leave the TODO.

# 4. The four gates.
make fmt-check && make lint && make typecheck && make test

# 5. MR, review, merge.

# 6. AFTER merge, tag it — by hand. bump_version.py deliberately will not.
git tag -a vX.Y.Z -m "X.Y.Z — <headline>" && git push origin vX.Y.Z
```

## 6. Gotchas

- **`uv run --no-sync ruff` skips all six guards** that `make lint` bundles (`check_file_sizes.py`,
  `check_layer_imports.py`, `check_doc_links.py`, `check_control_liveness.py`,
  `check_doc_claims.py`, `check_state_keys.py`). If you dodge the dev-server exe lock that way, run
  the six explicitly — they are the half of `make lint` that `ruff` alone never runs.
- **Pushing a tag fires a pipeline** — `.gitlab-ci.yml` has an `if: $CI_COMMIT_TAG` rule. Push tags
  only after the merge has gone green.
- **A version bump touches a hot file.** `packages/core/mosaera_core/__init__.py` is shared; if a
  concurrent session is mid-arc, whoever lands second rebases.
- **Do not add the maturity channel to the run seal.** It is kept out of the receipt preimage on
  purpose (ADR-0088 §7) — adding it rewrites every receipt id.

## 7. Version history

`CHANGELOG.md` is the record; git tags `vX.Y.Z` mark the commits. Tags for `v0.5.0` and `v0.6.0` were
backfilled after the fact — releases before 2026-08 were recorded in the CHANGELOG only.
