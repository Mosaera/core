# ADR-0055: Engine versioning — 0.x, maturity-anchored, stamped with the benchmark

- Status: accepted
- Date: 2026-07-17
- Owners: Mosaera core
- Related issue: — (process/infra; tracked on the roadmap)
- Related threat model: — (no trust-surface change)
- Extended by: [ADR-0088](ADR-0088-engine-maturity-channel.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.

## Context

We want to know *how the engine progresses* over time. A version number only means something once you
can measure the thing it labels — and we just built that: the reliability scoreboard (ADR-0053, a
clean-conclusion rate) on top of the MCB capability benchmark (ADR-0007). Before this there was no
measured baseline to attach a version to.

## Decision

Version the engine as a **measured milestone**, not a consumer API contract:

- **`0.x`, maturity-anchored, starting at `0.5.0`.** Not `0.0.x` — that register reads "experimental toy",
  and Mosaera is a working autonomous engine (91.7% clean-conclusion) with a full trust/oracle stack. It
  is *pre-stable*, not *pre-anything*. `0.5.0` acknowledges the substantial un-versioned pre-history
  (~50 ADRs / many arcs) — "past the halfway mark to production-stable."
- **MINOR bump per completed arc/wave** (not per merge). e.g. the reliability arc closing at ~99% earns a
  MINOR. Milestone-based fits Mosaera's wave structure better than CalVer or per-PR patches. *(Amended
  2026-07-23 — see the Amendment below: post-`0.6.0`, arcs bump **PATCH**, not MINOR.)*
- **`1.0` = the SWE team is production-stable** — reliability holds ~99% clean-conclusion and the roadmap's
  "Python stable" gate is met.
- **Single source of truth: `mosaera_core.__version__`.** Kept in lockstep with the workspace pyproject
  versions (all 7 packages move together — one product). A bump edits `__init__.py` + the pyprojects.
- **Stamp the version into the progress artifacts** — the feature that makes a version worth having:
  the scoreboard trend (`_suite/history.jsonl` + the rollup JSON/MD/CLI), every run report, the API
  `/config` (so a deploy self-identifies in the UI), and `mosaera --version`. Every measured outcome is
  therefore attributable to the engine version that produced it — the x-axis of "how it progresses".
- **`CHANGELOG.md`** carries one entry per release with its **benchmark snapshot** (clean-conclusion +
  capability + outcome buckets), so the history is measured, not narrative.
- **Git tags `v0.x.y`** at arc boundaries mark the durable points (deferred: CI-wired bumping + tag
  automation).

## Options considered

- **`0.x` maturity-anchored at `0.5.0` (CHOSEN).** Honest register + proportionate to the work; the trend
  (0.5 → … → 1.0) tells the progress story.
- **`0.0.x` (REJECTED).** Wrong register — signals an experimental toy for a system that autonomously
  ships code at 91.7% clean.
- **Strict semver for external consumers (PREMATURE).** No published public API to break yet
  (self-hosted, single-tenant). The internal seams (`get_chat_model`, the gate policy, `RunState`, the
  LanguagePack) have contracts, but versioning them for outside consumers is a future concern.
- **CalVer `YYYY.MM` (REJECTED).** Progress here is arc/milestone-based, not calendar-based.

## Security implications

None — a display/metadata string. No trust boundary, no gate, no secret.

## Operational implications

No migration, no new dependency. A version bump is: edit `mosaera_core/__init__.py::__version__` + the 7
`pyproject.toml` versions (a small `scripts/bump_version.py` can follow), add a `CHANGELOG.md` entry with
the fresh benchmark snapshot, and tag `v0.x.y`. ~~Not wired into CI yet (a bump is a deliberate act).~~ **Corrected 2026-08-18** (`docs/audits/adr-corpus-review-2026-08-18.md`) — the helper shipped and the *check* is CI-wired: `scripts/bump_version.py` does bump / `--check` / `--verify-record`, and `.gitlab-ci.yml`'s `version-record` job runs it with `--strict`. The *bump* and the *tag* remain deliberate human acts. "the 7 `pyproject.toml` versions" also under-counts — the invariant now spans 9 files.

## Consequences

- **Good:** progress becomes a labeled trend — `v0.5 → 91.7% clean / 88 cap`, and forward. The scoreboard
  and reports self-identify their engine version.
- **Follow-up:** a `bump_version.py` helper; CI-wired bump/tag on arc completion; when there's a stable
  measured state (reliability ~99% + Python stable), cut `1.0`.

## Amendment (2026-07-23): PATCH per arc after 0.6.0

Owner steer (2026-07-19), recorded here so the ADR stops contradicting the decision: **going forward,
completed arcs bump `PATCH` (`0.6.0 → 0.6.1 → …`), not MINOR.** The MINOR (and MAJOR) digits are
**rationed toward a production-proven-at-scale `1.0`** — proven across multiple projects of different
types, languages, and dependency shapes (matches the ADR-0061 any-repo gate). Rationale: *"v1 should be a
production-level full release,"* and the engine is not close, so incremental arcs no longer earn a MINOR.
This refines the original "MINOR per completed arc/wave" bullet above; everything else in the Decision
(maturity-anchored `0.x`, single-source `__version__`, benchmark-snapshotted CHANGELOG, `1.0` =
production-stable) is unchanged. `1.0` remains the production-stable milestone; the path there is now
`0.6.x` PATCH increments, not `0.7/0.8/...` per arc.
