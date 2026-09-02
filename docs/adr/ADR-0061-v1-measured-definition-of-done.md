# ADR-0061: v1.0 — the measured definition of "production-stable"

- Status: accepted
- Date: 2026-07-19
- Owners: Mosaera core
- Related issue: the road-to-v1.0 arc (roadmap "Road to v1.0"); north stars NS-1/NS-2/NS-3
- Supersedes nothing; **binds** the meaning of `1.0` first named in ADR-0055 (versioning) and
  `docs/architecture/north-star.md`.

## Context

The engine is versioned `0.x`, maturity-anchored, with **`1.0` = "the SWE team is production-stable"**
(ADR-0055). That phrase was never given teeth. This ADR defines `1.0` as a **measured bar** — four
thresholds on a held-out benchmark — so "are we v1?" is a number, not a vibe, and so no release can be
called v1 on the strength of a demo. It is the anti-gimmick contract: **every claim toward v1 is measured
on inputs the coder cannot see or game, or it does not count.** (0.6.0's discipline — a frozen classifier,
a hidden grader, a `false_ship` gate, reverting a correctness-costing optimization — is the machinery this
ADR makes standing policy.)

## The reframe this ADR commits to

The engine is **not the code-writer.** The intelligence is a swappable model (the `get_chat_model` seam,
ADR-0002). What a serious buyer purchases is not "an AI that writes code" (a commodity) but:

> **A governed system that makes a frontier model provably deliver correct, industry-standard code on the
> buyer's own codebase, under the buyer's compliance regime, with a full audit trail — and that honestly
> refuses when it cannot.**

So v1 is defined along the axes we actually own — **trust, verification, project-knowledge, and
governance** — not along model capability (which we consume, route, and make reliable, but do not build).

## Decision — the four v1.0 gates (all must be green on the held-out benchmark)

1. **Reliability gate — ~99% clean-conclusion.** Across the hard suite (repeat≥3), ≥~99% of runs reach a
   clean terminal state: deliver-correct **or** park-honestly with an accurate reason — *without thrashing*
   (`bench/reliability.py::classify_outcome`; the #43 scoreboard). 0.6.0 measured 65.3% (escalation OFF).
2. **Correctness gate — no unestablished material claim ships.** A delivered change is graded by a
   hidden suite the coder never saw. The gate is met when **no run delivers work carrying a material
   claim the evidence did not establish**, with the residual `false_ship` rate stated as a **bound on a
   named distribution** — the suite, the run count, and the posture configuration must all be cited, and
   the bound read by the rule of three (~3/n at 95% when the observed count is 0). It is the load-bearing
   v1 gate: "passes the given tests" is not "correct."

   *Amended 2026-08-05, and the reason matters.* The original wording — "`false_ship` ≈ 0 on held-out
   inputs" — named no suite, no n and no configuration, and that turned out to be exploitable by
   accident rather than by intent. The 6.9% attributed to MCB-05/15 was produced by a **defect of ours**:
   `check_structural_compliance` returned *met* after executing zero predicates, minting a structural
   vouch that cleared `oracle_unverified` and let the gate approve. Fixing that defect (2026-08-04)
   removed the only delivery channel those cases had, so `false_ship` became **unobservable rather than
   zero** — and under the old wording a suite of runs that can no longer deliver would have read as a
   pass. That is precisely the "demoed rather than measured" failure the no-gimmicks clause below
   forbids. A rate is only a result when the distribution it bounds is named.
3. **Any-repo gate — ≥2 languages on real brownfield.** The bar holds on **brownfield** repos (existing
   code, existing tests, real conventions) in **≥2 languages** (Python first, then TS/JS or SQL) — not toy
   greenfield. Measured on the demo-shape + brownfield-seed harness, not a curated happy path.
4. **Governance gate — fully auditable, ceremonied autonomy.** Every run is reconstructable from a
   tamper-evident, exportable audit log; unattended autonomy is granted only via the dual-control
   enablement ceremony (time-boxed, out-of-band activation), and posture is versioned policy-as-code with
   each control mapped to a named framework requirement (NIST 800-53, CMMC). (ADR-0046 direction.)

**v1.0 ships only when all four are simultaneously green on a held-out benchmark run**, recorded as the
release's benchmark snapshot (ADR-0055). Any gate demoed rather than measured **fails** — that is the
"no gimmicks" clause.

## The four pillars (what each gate requires, honestly)

- **Correctness oracle (gate 2 — the critical path).** "Done ⇒ correct" must be *proven*, not asserted.
  Load-bearing pieces, in evidence-strength order (see the ADR-0059/#55 verification research):
  rigorous **spec-derived acceptance tests the coder never sees** (the Proctor, made real — property /
  metamorphic, not just examples); **dynamic per-test verification** (the #54 successor) so a green suite
  cannot be a rubber stamp — this directly kills the MCB-05 executed-but-unasserted class; a **held-out
  critic** (LLM-as-judge, a *different* model than the coder, downgrade-only). Measured against a hidden
  grader. This is the arc that converts "passes the tests" into "code you'd stake a name on."
- **Project-knowledge (gate 3).** Onboarding: interview → multi-dimensional recon → a durable **map** +
  **charter**, so every run is scoped as *gap-analysis against the project's actual state* and respects the
  repo's own conventions ("industry-standard" is project-relative). (ADR-0047, #42/#6.) Plus language
  generalization via the LanguagePack seam, each with its own validation + oracle — **after** Python's
  oracle is provably solid (owner build-order).
- **Capability (gates 1 & 3 — mostly the model's job).** v1 code quality = a **frontier model** as the
  coder, local models for cheap/easy work, **escalation routing** for hard cases (ADR-0016/0022). The
  engine's contribution is **context quality** (repo-map, the exact failing diff, the spec, conventions —
  the AutoCodeRover/Aider lever) and reliable orchestration. 0.6.0's truncation fix is the archetype:
  better feedback → convergence. *Empirically confirmed:* the escalation-ON re-baseline (matrix B) lifts
  clean-conclusion from 65.3% toward ~90%+ — capability is a routing lever, not an engine rewrite.
- **Governance (gate 4).** Posture as versioned policy-as-code (Free/Business/Regulated), control-mapped;
  the dual-control enablement ceremony; the tamper-evident exportable audit log. The trust boundary +
  honest outcomes + sandbox + tamper guard already shipped are the foundation; this is the
  compliance-mapped, auditable skin over them. (ADR-0046, Waves B/C.)

## Sequencing (which gate gates which)

1. **Correctness oracle first** — nothing downstream is sellable until "done ⇒ correct." It is also the
   direct successor to 0.6.0's surfaced `false_ship`, so it has momentum.
2. **Project-knowledge (onboarding) + Python-solid** in parallel behind it — makes "any repo" real and
   makes "industry-standard" project-relative.
3. **Language #2** — only after the Python oracle is green (a shaky oracle in N languages is worse than a
   solid one in 1).
4. **Governance layer** — largely parallelizable once the core delivers; it is the enterprise wrapper, not
   a blocker on correctness.
5. **Capability/routing** runs continuously — it is configuration (which model, when to escalate), matured
   by measurement (matrix B), not a serialized arc.

## Consequences

- `1.0` is now falsifiable: a single held-out benchmark run either clears all four gates or it does not.
- The **correctness oracle** is confirmed as the highest-leverage next arc (gate 2 is the only gate 0.6.0
  outright fails, and the one that separates the product from a commodity).
- Every arc toward v1 inherits the **measured-or-it-doesn't-count** discipline; the reliability scoreboard
  gains a correctness (`false_ship`) companion metric as a first-class release gate.

## Rejected

- **"v1 = it writes good code."** Untestable and not our axis — the model writes the code; we make it
  trustworthy. v1 is defined on trust/verification/knowledge/governance.
- **A time-boxed v1 ("ship in N months").** v1 is a *measured threshold*, not a date; dating it invites
  exactly the gimmickry this ADR forbids.
- **Language breadth before oracle depth.** Sequenced against (a solid oracle in 1 language beats a weak
  one in many).
