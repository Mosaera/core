# MCB first full run — findings (2026-07-11)

> **HISTORICAL — a point-in-time benchmark snapshot (2026-07-11), not current status.** Durable
> lessons and later results live in [`../roadmap.md`](../roadmap.md) and
> [`../engineering-history/`](../engineering-history/). Kept for the record.

First full run of the expanded 20-case Mosaera Capability Benchmark (ADR-0007), and
the notes from the conversation that framed it. Baselines from this run are committed
under `packages/core/mosaera_core/bench/baselines/` (see the caveat at the end).

- **Endpoint:** `https://ollama.rengifo.me` · **Models:** PM/reviewer `gpt-oss:20b`,
  coder `qwen3-coder:30b`, embeddings `nomic-embed-text`.
- **Sandbox:** Docker (`docker.exe`). **Mode:** autonomous. **Pass:** single
  (`--all`, repeat=1). **Total:** ~5.33M tokens across 20 cases.

## Result — capability × difficulty (mean score, n)

| Capability | trivial | moderate | hard | Overall |
|---|---|---|---|---|
| greenfield | 99 (2) | — | — | **99** |
| bug-fix | — | 97 (4) | 100 (1) | **98** |
| feature | — | 100 (3) | 93 (2) | **97** |
| refactor | — | 96 (2) | 90 (2) | **93** |
| robustness | — | 99 (3) | 98 (1) | **98** |
| **by tier** | **99** | **98** | **94** | **Suite 97 · 19/20 delivered** |

## The headline (97) is not the story; the spread is

The suite is **not saturated where it counts** — the hard tier (94) separates from
moderate (98), refactor is the softest capability (93), and two hard cases exposed the
real ceiling with the honesty machinery firing on live runs:

### MCB-05 — refactor / hard → 80, **Governance 0** (shipped broken)

The delivered `checkout_total` passed all 6 behavioural tests **and** the
"delegates to ≥3 helpers" structural check, but **failed
`test_checkout_total_is_a_short_orchestrator`**: it extracted helpers yet left the
orchestrator body too long — a *half-finished* refactor — and scattered work into a
stray `checkout_refactored.py`. **The reviewer (`gpt-oss:20b`) approved it anyway.**
Only the independent hidden grader caught it, so Governance scored **0 for shipping
work claimed done that wasn't**. Failure mode: **reviewer over-approval** of a
not-quite-complete change; the reviewer is not a reliable oracle.

### MCB-11 — feature / hard (operator precedence) → 88, honest **park**

Precedence was correct, but the delivery **failed `test_division_is_left_associative`**
(`8 / 2 / 2` evaluated wrong). The run left a **debris field** — `calc_fixed.py`,
`calc_working.py`, `final_debug.py`, `run_debug.py`, and six scratch test files
(Cleanliness 50) — classic thrashing on a subtle reasoning edge. Its **own tests caught
the failure** (Validation 25) and it **correctly parked** rather than ship broken code
(Governance 100, Autonomy 30). This is the *good* failure: honest non-delivery under a
genuine reasoning-difficulty ceiling.

Cost corroborates the ceiling: the two hard cases each burned **1.1–1.25M tokens** vs
**30–130K** for moderate ones — 10–40× the thrash for a decent-but-imperfect result.

## What it says about the models

- **Genuinely strong at focused, testable, small-scope Python** — moderate tier averages
  98; the hidden graders ran and passed, so these are real solves, not inflation.
- **The frontier is two things:** (1) hard structural/precedence *reasoning* (refactor 93,
  feature-hard 93), and (2) *discipline* — not shipping imperfect work (MCB-05) and not
  thrashing a debris field (MCB-11).
- **The planner ran fully cold.** The benchmark harness passes only the brief — no project
  context, no memory (`harness.py`; see the Quincy case study). So these scores are what a
  **context-starved PM + a capable coder** achieve. That the pair still hits 96–100 on
  focused tasks means the PM is **not** the bottleneck for small items — but it is exactly
  the bottleneck for whole-project delivery, where decomposition and cross-item coherence
  matter. See [`docs/design/quincy-pm-case-study.md`](../design/quincy-pm-case-study.md).

## Strategic conclusion

The path to a whole webapp is a **well-decomposed, dependency-ordered backlog run
autonomously**, not one giant run. The MCB validates the execution layer for
backlog-sized items; the leverage now sits in the **PM** (decomposition, sharp acceptance
criteria, cross-item context) and in **reviewer/coder discipline** (MCB-05/MCB-11). The
next benchmark evolution is a **project-scale track** (seed mid-project → grade
*integration*; multi-item decompose → run → grade the *trajectory*) to measure the
one-shot-whole-project ceiling instead of extrapolating it.

## Caveat on the committed baselines

These are a **single-pass (repeat=1) snapshot**, not the 3×-averaged baseline the
discipline calls for (`baselines/README.md`). They are a usable v1 reference — the
compare tolerance (±5 pts) absorbs single-pass noise — but should be refreshed with
`mosaera-bench --all --update-baseline` (3× averaged) when convenient. Scores are
sampling-noisy; treat a single case's exact number as ±a few points.
