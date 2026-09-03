# The control register — what can actually fire

**Status: Operational.** One row per control that emits a verdict. The question this file exists to
answer in a lookup rather than an investigation: *when this says green, what did it actually check?*

A control is anything whose output another decision trusts — a knob-gated behaviour, a gate input, a
scanner, an oracle, a CI job, a test gate. For each, three things matter and only three:

1. **Rung** — the ADR-0081 ladder (C0 declared → C5 outcome-observable), highest **proven**, never
   hoped-for.
2. **Evidence** — what proved it. A test id, or honest prose that says it is prose.
3. **Zero-input behaviour** — what it reports when it checked *nothing*. This column is the one that
   keeps catching us: it must never read as a pass.

The per-knob rungs live in `packages/core/mosaera_core/bench/liveness.py::REGISTRY` and are
machine-checked by `scripts/check_control_liveness.py` (forward ratchet: a **new** posture knob
below C4 fails; the six already below are grandfathered and shrink-only; evidence naming a
non-existent test fails). This file covers what that registry does not: the controls that are not
knobs.

## Why this exists

Six instances of one defect class, found one at a time over three weeks:

| # | Control | It reported | It had actually done |
|---|---|---|---|
| 1 | `reviewer_advisory` | a live mitigation in TM-0001 | nothing — zero engine reads |
| 2 | ADR-0071/0072 "held pending measurement" | held | never run |
| 3 | `gate_reasons` / `critic_vetoed` | `[]` / `False` | unreachable observation point |
| 4 | `honest_stop_no_signal` A/B | a hold decision | byte-identical arms |
| 5 | **`sandbox-e2e` (#58)** | **success, for 7 weeks** | **skipped ~105 Docker/DB tests** |
| 6 | **`check_structural_compliance`** | **satisfied → vouched** | **zero predicates executed** |

ADR-0081 named the class and built the ladder for 1–4, which all lived in bench/measurement. #5 lived
in CI and #6 in the product oracle path — both outside the ADR's bench-first scope. The register
covers every verdict-producing control precisely so the seventh is found by looking, not by luck.

## The rule

> **A verdict is only as strong as the number of checks that actually executed. Zero executed
> checks is never a pass.**

Empty input is the recurring trap because the natural Python spelling of "no complaints" — an empty
`reasons` list, `all([])`, `not any([])`, a loop that never runs — is indistinguishable from "every
check passed". Each control must therefore either count what it ran, or refuse to conclude.

## Register

### Verdict producers (product path)

| Control | Rung | Zero-input behaviour | Evidence |
|---|---|---|---|
| `check_structural_compliance` | C4 | **`unevaluable`** — counts executed predicates; zero → `None` (fixed 2026-08-04; previously `True` = satisfied, which *vouches*) | `test_structural_spec.py::test_shrink_ask_without_a_baseline_is_unevaluable_not_met`, `test_claim_oracles.py::test_a_shrink_ask_with_no_baseline_never_vouches` |
| `run_scan` | C4 | **`unavailable`** — zero scanners is not clean (fixed 2026-08-04) | `test_scan.py::test_run_scan_with_no_scanners_is_unavailable_not_clean` |
| `evaluate_claims` | C5 | `[]` rows → gate unchanged. Intentional (no claims ⇒ no claim gating), but **nothing asserts that a run which should have had claims did** | `test_gate.py` sentinels; the claims-gate A/B |
| `security_status` → `security_unverified` | C5 | `unavailable` parks in every mode — "we did not look" is not "clean" | `test_gate.py::test_security_unverified_parks_over_approve_and_green_oracle` |
| `standing_suite_is_independent_oracle` | C3 | credits a docs/test-only or empty change on requirements 1+2 — **deliberate and documented**, but see the accepted residual below | `oraclecheck` docstring; `test_oraclecheck.py` |
| `authored_suite_asserts_behaviour` | C3 | `None` on empty; both call sites read `is not True` — deny-by-default holds | verified in the 2026-08-04 sweep |
| `hygiene_findings` | C2 | clean on an empty file list. **Examined, not a defect:** a non-Python change has nothing to lint, which is not the same as failing to lint it — and forcing `unavailable` here would trip the hygiene loop on every docs-only change. Advisory loop regardless | 2026-08-04 sweep |
| `validation.py` config/HTML checkers | C2 | `exit 0` having parsed 0 files. **Bounded:** such a plan declares `strength="shallow"`, and the autonomous reviewer-silence backstop requires `"suite"` — so it cannot carry an unattended ship. Residual: within `shallow`, "parsed 0" and "parsed 12, all fine" are indistinguishable | open, bounded |

### Measurement

| Control | Rung | Zero-input behaviour | Evidence |
|---|---|---|---|
| `experiment_verdict` | C4 | **INVALID** on an empty arm — the correct pattern, and the one others should copy | `test_control_liveness.py::test_experiment_verdict_fails_closed_on_missing_fingerprints` |
| `experiment_report` (ADR-0081 D3) | C4 | INVALID ⇒ `effect is None`: an un-diverged A/B has **no numbers to quote** (added 2026-08-04; D3 was a human procedure before) | `test_control_liveness.py::test_identical_arms_yield_the_verdict_and_no_effect` |
| `check_control_liveness.py` | C4 | fails on a new sub-C4 posture knob and on evidence naming a non-existent test (was report-only, returning 0 on findings) | `test_control_liveness.py::test_the_guard_passes_on_the_real_registry` |

### CI / test gates

| Control | Rung | Zero-input behaviour | Evidence |
|---|---|---|---|
| `sandbox-e2e` | C2 | **skips its gated tests and reports success** — root cause: CI runs stock `postgres:16`, the store needs pgvector. The harness fix (skip reasons, one probe, `MOSAERA_INTEGRATION=required`) is in !323; **arming it needs the CODEOWNERS-protected image + variable change** | `docs/engineering-history/sandbox-e2e-vacancy-2026-08-04.md` |
| `quality` (`make ci`) | C4 | fails closed; its Docker/DB subset self-skips, now with printed reasons | pipeline #828 |
| `web` (vitest) | C3 | vitest exits non-zero on *no* test files; a **partial** glob collapse still passes | open, low |
| `secrets` (gitleaks) | C3 | fails closed without config; scans the working tree, **not** history; two files allowlisted by path | open, medium |

## Accepted residuals

**`is_test_file` matches a basename, not a location.** A *source* file named `test_*.py` is excluded
from nine scrutiny sites (mutation, coverage, structural, claim oracles), and an all-such change
then reaches `standing_suite_is_independent_oracle`'s documented empty-source credit — an
independence credit for a change nothing examined.

**Not fixed, deliberately.** A location rule (`tests/` in the path) would misclassify *colocated*
tests — `pkg/test_foo.py` beside its source is a standard pytest layout in the arbitrary user repos
this engine operates on. The damage would land in three places: real tests would be mutated as if
they were source, they would enter coverage and structural scrutiny sets, and worst,
`oraclecheck`'s `test_files = [p for p in integrity_baseline if is_test_file(p)]` would come back
empty → `return False` → independence denied → **over-parking correct work**, which is already the
dominant Gate-1 defect. The basename rule is the right heuristic for identifying tests in a repo
whose layout we do not control; the residual is the price.

> **STALE as of 2026-08-22 (ADR-0036 amendment), on the load-bearing leg.** That `oraclecheck` line
> no longer exists — it now reads `[p for p in integrity_baseline if not is_collection_control(p)]`,
> so the over-parking argument quoted above does not apply to that call site any more. The entry's
> *conclusion* still stands, but for a different reason than it gives: a basename rule is no longer
> the heuristic at all. The security sets read the TARGET's `python_files` via
> `pytestconfig.resolve_naming`, and `is_test_file` survives as the fallback plus the predicate for
> the scrutiny sites (coverage, destruction, nonuse, claim oracles), where the residual below is
> unchanged. ADR-0081:131 chains to this entry and inherits the correction.

**Fails safe:** the exposure needs a source file deliberately or unluckily named `test_*.py`. Revisit
if the coder is ever observed creating one — that is the adversarial shape, and it is worth a
targeted mitigation rather than a blanket reclassification.

## How to add a control

State its zero-input behaviour first. If the honest answer is "it would report a pass", that is the
defect — fix it before writing the row.
