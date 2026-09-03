# ADR-0081: The control liveness ladder — prove a control can fire before measuring it

- Status: accepted
- Date: 2026-08-02
- Owners: @Ashura
- Related issue: the Gate 2 pivot (claim-contract arc; measurement integrity)
- Related: [ADR-0078](ADR-0078-terminal-gate-visibility.md) (instance #3, fixed),
  [ADR-0077](ADR-0077-language-native-convergence-signal.md) (whose decision-6 measurement was
  void — instance #4), [ADR-0072](ADR-0072-structural-spec-oracle.md) (activated on n=3 noise),
  [ADR-0049](ADR-0049-change-coverage-gate.md) (guard-style precedent)

## Context

Four times in one week, a control or measurement *looked* live and structurally could not fire:

1. `reviewer_advisory` — live UI toggle, documented in TM-0001 as a mitigation, **zero engine
   reads** (C0, never C1).
2. ADR-0071/0072 "held pending measurement" — env-settable all along, **never run** (C1–C2,
   never C3).
3. `gate_reasons` — `[]` on all 526 instrumented runs because a parking gate never resumes;
   `critic_vetoed` False on 643/643 **by construction** (the observation point was unreachable —
   C5 failure; fixed by ADR-0078).
4. `honest_stop_no_signal` — its only behavioural read sits in a branch (`_no_signal_path`) that
   post-#81 never executes on the case used to "measure" it; its reason string appears in
   **0 of 1,233 scorecards**; the ON/OFF A/B ran byte-identical code and its numbers drove a
   hold decision (C4 failure — arms never diverged).

Each was found by accident, one at a time. The class is systematic; the guard must be too.
Correctness is the product blocker, but **measurement liveness is the meta-blocker**: no
correctness control can be trusted, activated, or held until the control is proven able to fire
and the experimental arms proven to have executed different code.

## Decision

1. **The ladder.** Every knob-gated control and every A/B experiment is classified:
   - **C0 DECLARED** — exists in config/UI.
   - **C1 READ** — ≥1 engine read exists.
   - **C2 INFLUENTIAL** — the read has a control/data-flow path to a behavior sink (graph
     node/edge choice, prompt content, tool/permission set, gate input, interrupt payload,
     terminal disposition, counted signal).
   - **C3 EXERCISED** — a fixture executes that path in CI.
   - **C4 ARM-DIVERGENT** — ON and OFF produce different **execution fingerprints** on a
     sentinel fixture.
   - **C5 OUTCOME-OBSERVABLE** — the intended measurement can observe the distinction at its
     actual observation point.
2. **The fingerprint is the deterministic projection only**: nodes entered, conditional edges
   taken, settings reads, DECLARED state keys written, interrupt kind, terminal disposition.
   **Never prompt hashes or model-call payloads** — those differ run-to-run under a stochastic
   model even on identical code paths, which would mark every A/B divergent and void the check
   in the opposite direction.
3. **Invalid experiments are named, not scored.** A bench A/B whose arms produce identical
   fingerprints on the sentinel emits `INVALID_EXPERIMENT_IDENTICAL_EXECUTION` and **no
   effectiveness result**. Instance #4 would have been voided automatically: both arms enter
   `_no_signal_path` zero times.
4. **The roadmap invariant:** *no roadmap/ADR claim may cite a control experiment unless arm
   divergence (C4) was proven for that experiment.* A threat-model mitigation may not be
   recorded as active below C4.
5. **Scope: bench-first.** The ladder lands as a bench/CI facility (fingerprint capture in the
   harness — the ADR-0078 seam; a per-knob sentinel-fixture registry; a guard script in the
   `check_*.py` family reporting each posture knob's highest proven rung). Product-runtime
   fingerprinting is explicitly deferred — the four incidents all lived in bench/measurement.

## North Star implementation test

- **Artifact:** the per-knob liveness record (rung + sentinel + last-proven fingerprint pair);
  the per-experiment divergence verdict.
- **Authority:** the guard script + harness own the verdict; deterministic.
- **Independence:** the experimenter doesn't certify their own experiment — the fingerprint does.
- **Evidence:** fingerprint pairs; CI runs of sentinel fixtures.
- **Failure:** identical arms ⇒ INVALID, no score; unproven rung ⇒ claim not citable. Fails closed.
- **Audit:** fingerprints are stored with the scorecards they validate.
- **Model substitution:** the projection is model-free by construction (decision 2).
- **Scope:** bench-first; no runtime overhead on the product path.

## Consequences

- Every existing posture knob gets an honest rung label; some will land at C3 and expose missing
  sentinels — that backlog is the point, not a regression.
- ADR-0079/0080's own controls (checkability verdict, clarification path, per-claim gating) must
  enter at C4+ before any effectiveness claim — this ADR is deliberately sequenced with them.
- Cost: one sentinel fixture per load-bearing knob; fingerprint capture reuses the ADR-0078
  capture seam. Small, and paid once.

## Amendment 1 (2026-08-04) — the ladder covers any verdict, not just bench experiments

**Status: accepted (owner, 2026-08-04).** Decision 5 scoped the ladder *bench-first*: "Product-runtime fingerprinting is
explicitly deferred — the four incidents all lived in bench/measurement." That was the right call on
the evidence available. Two further instances have since been found, and neither was in bench:

- **Instance #5 — `sandbox-e2e` (#58), in CI.** The job whose purpose is running the Docker- and
  Postgres-gated tests skipped ~105 of them and reported **success**, for seven weeks. Root cause: CI
  declared stock `postgres:16` while the memory store's `init()` runs `CREATE EXTENSION vector`. The
  exception was raised on every run since 2026-07-16 and printed **zero times** — eight copy-pasted
  `_reachable()` helpers each swallowed it.
- **Instance #6 — `check_structural_compliance`, in the product oracle path.** It returned `True` =
  *satisfied* after executing **zero predicates** (a "short orchestrator" ask with no helper count
  and no HEAD baseline). That verdict is the sole input to the #60 refactor vouch, so it reached
  `oracle_verified` and could clear `oracle_unverified` at the gate — independence evidence
  manufactured from nothing, in direct contradiction of the module's own docstring.

Both are the class ADR-0081 exists to prevent; both sat outside the scope its Decision 5 drew. The
scope was the blind spot.

### Amended decisions

**5 (replaces "bench-first").** The ladder applies to **any control that emits a verdict another
decision trusts** — a knob-gated behaviour, a gate input, an oracle, a scanner, a CI job, a test
gate. Product-runtime *fingerprinting* remains deferred (it was never the cost driver); what
generalises is the requirement to state a rung and prove it. Controls that are not knobs are
recorded in `docs/architecture/control-register.md`, which carries the column the knob registry has
no place for: **what the control reports when it checked nothing.**

**6 (new) — the no-vacuous-verdict rule.**

> A verdict is only as strong as the number of checks that actually executed.
> **Zero executed checks is never a pass.**

A control that can conclude must be able to say how many checks it ran, and must refuse to conclude
positively when that count is zero. The rule exists because the natural spelling of "no complaints"
in Python — an empty `reasons` list, `all([])`, `not any([])`, a loop over an empty collection, a
pytest run where everything skipped — is *indistinguishable* from "every check passed". Empty input
is therefore the default suspect in any review of a verdict producer, and "what does this report on
empty input?" is a required question at the North Star **Failure** test.

Deny-by-default direction, stated once so it is not re-litigated per control:

- For **scrutiny** (does this deserve examination?), ambiguity resolves toward *examine it*.
- For **protection** (is this something we must not break?), ambiguity resolves toward *protect it*.

These pull opposite ways on the same input, which is why a single predicate serving both is a smell —
see the `is_test_file` residual recorded in the control register.

**7 (new) — Decision 3 is mechanical.** Decision 3 said an arm-identical A/B "emits
INVALID_EXPERIMENT_IDENTICAL_EXECUTION and no effectiveness result". Until 2026-08-04 that was a
human procedure: `experiment_verdict` had zero production callers and the one real use was run by
hand. ~~`liveness.experiment_report()` now validates before scoring and returns `effect is None` when
the arms never diverged.~~ A control whose enforcement depends on someone remembering is at C1,
whatever its ladder row says.

### Consequences

- The control register becomes a maintained artifact, and adding a control means stating its
  zero-input behaviour *first* — if the honest answer is "it would report a pass", that is the defect.
- Some existing verdict producers land below C4 with honest prose evidence. That backlog is the
  point; `scripts/check_control_liveness.py` grandfathers the six posture knobs already below C4 in a
  **shrink-only** list, so the debt is visible and cannot quietly grow.
  **Ratchet state, 2026-08-18 (`docs/audits/adr-corpus-review-2026-08-18.md`): it has not shrunk — not once.**
  `git log -S'GRANDFATHERED' -- scripts/check_control_liveness.py` returns exactly ONE commit,
  `bc33be8` (2026-08-04) — the commit that created the list. All six knobs still sit at
  `C2_INFLUENTIAL` under the identical note "C3/C4 sentinels not yet written". "Shrink-only" bounds
  the debt but assigns it to nobody: the six sentinels appear in no issue and nowhere in the roadmap.
  A ratchet no one turns is a backlog that reads as a control — the shape this ADR exists to name,
  occurring in this ADR's own guard.
- Decision 4 (no claim citable below C4) is enforced **forward**: new claims need C4, existing
  sub-C4 citations are marked rather than struck. Retroactive audit was considered and deferred by
  the owner on 2026-08-04.
