# ADR-0068: The tamper-guard false-positive — the engine must not rewrite its own authored tests

- Status: accepted
- Date: 2026-07-20
- Owners: Mosaera core
- Related issue: the run-reliability arc `#43`; a fix to the `#54`/ADR-0058 test-integrity surface, the
  `#60`/ADR-0066 refactor scaffold, and the hygiene gate
- Related threat model: TM-0001 (the tamper/integrity surface — updated)
- Red-team: **DONE** (3 agents — hygiene / CRLF / run-once+scaffold lenses): **2 FIX-NOW fixed +
  re-verified** (an oracle pre-plant hole the idempotent `_write` opened; a resume-time protected-set
  gap), rest FALSE-POSITIVE/ACCEPT. See §Red-team disposition.

## Context

The thrash-cause instrumentation (ADR-0053 scoreboard gains `thrash_cause` + the terminal
`gate_reasons`/`stalled`) measured that **~100% of the instrumented `thrash_park` is one self-inflicted
bug**: every thrash stalls at **iteration 2** with `stall_reason="pre-existing/protected tests … were
modified: …"` naming an **engine-authored** test (the scaffold's `tests/test_refactor_golden_*`; a
Proctor `test_*`) on code the hidden grader confirms CORRECT (Impl ≥85). The engine kills correct runs
by flagging its OWN tests. This is the regression behind 65.3% → ~57%.

**Root cause — DOMINANT (nailed by a file-based capture of the golden test at authoring vs check):**
`author_tests_node` writes the scaffold's golden test with `tests_baseline = hash(v1)` (its `_CASES`
rendered with **single** quotes). The **hygiene gate** then runs `autofix` = `ruff format` on the run's
changed files (`nodes_impl.hygiene_node` → `hygiene.autofix`), and the golden test is in that diff — so
ruff rewrites its quotes **single→double**. Same length, different bytes → the baselined test's hash
changes → `tampered_files` trips → `stalled` → `thrash_park`, at iteration 2. Proven: the captured
author-time content had `('grade_letter', …)`, the check-time content `("grade_letter", …)`. The coder
is never the writer (`ctx.protected_tests` refuses its tools; coder-edits-the-module-only never trips).
**The engine authors → formats → then flags its own format change.**

Two secondary facets surfaced during the investigation (both real, neither the dominant live cause):
a **CRLF↔LF hash fragility** (`hash_files` hashed raw bytes, unlike `tampered_integrity`); and a
**re-plan scaffold re-freeze** (a gate-deny re-plan re-enters `author_tests`, and the scaffold, reading
the now-refactored module, re-freezes it — a tautological oracle + a second trip).

## Decision 1 — hygiene never reformats the engine's protected tests (the fix, MEASURED)

`hygiene_node` filters `ctx.protected_tests` out of the files it autofixes/lints. Those are the ORACLE,
authored by the tester/scaffold, not the coder's code; the coder can't touch them anyway, so leaving
them exactly as authored keeps `tests_baseline` valid. **Measured:** MCB-13 `thrash_park` (4/4 before) →
`clean_deliver`/`honest_park` with the tamper trip gone.

## Decision 2 — newline-normalize the authored-test hash (defensive)

`hash_files` normalizes `CRLF→LF` before the SHA-256 (`tools/repo/diff.py`), matching
`tampered_integrity`'s hash space (ADR-0058). Removes the CRLF↔LF false-trip class; a real
content/assertion change still trips (unit-verified). Not the dominant cause, but a real latent-bug
hardening.

## Decision 3 — author_tests runs once (correctness)

`author_tests_node` early-returns when the tests are already authored (`if authored_tests: return {}`),
so a gate-deny re-plan does NOT re-run the scaffold — stopping it from re-freezing the refactored module
(frozen == refactored, a tautology) and re-writing a baselined test. Also removes the `already_satisfied`
re-plan misroute (the red-phase no longer re-runs against the coder's on-disk impl). On the early-return
it repopulates the process-local `ctx.protected_tests` from `state["authored_tests"]`/`proctor_edits`
(red-team FN2) so the coder's tool-refusal layer survives a resume. **The scaffold `_write` OVERWRITES,
never skip-if-exists** (red-team FN1): the run-once guard already prevents the re-freeze, and skip-if-
exists let an untrusted seed pre-plant a weak oracle at the scaffold's predictable path — overwriting
clobbers any plant so the strong differential always wins.

## Safety (why this does not weaken the tamper guard)

The guard's protection is UNCHANGED: the coder still cannot modify a protected test (the tool-level
`ctx.protected_tests` refusal + the `tests_baseline`/`integrity_baseline` compare both stand). Decision 1
only stops the ENGINE's own hygiene pass from reformatting the ENGINE's own tests — a real coder edit of
a protected test still trips (its diff is not in `ctx.protected_tests` for the coder, and the content
changes non-cosmetically). Decision 2 ignores only newline noise. Decision 3 keeps authoring coder-blind
and iter-1-only (as before).

## Red-team disposition (DONE — 3 agents, hygiene / CRLF / run-once+scaffold lenses)

**2 FIX-NOW fixed + re-verified; 2 false-positives; residuals ACCEPTed. STOP rule not tripped.**

- **FN1 (HIGH, FIXED):** the idempotent scaffold `_write` (skip-if-exists) opened an **oracle pre-plant
  hole** — the target paths are seed-predictable and repo content is untrusted, so a planted weak file
  became the engine's oracle (reproduced offline; the attack did NOT exist before this commit). **Fix:**
  `_write` OVERWRITES (Decision 3) — the strong differential clobbers any plant; the run-once guard
  already handles the re-freeze the idempotency was for, so nothing is lost. Regression-tested
  (`test_scaffold_overwrites_a_preplanted_oracle`).
- **FN2 (MED, FIXED):** `ctx.protected_tests` (process-local) was not rehydrated, so after a resume +
  re-plan the run-once early-return left the coder's tool-refusal layer empty (fail-safe — the tamper
  hash still caught it, but the "protection unchanged" claim was imprecise). **Fix:** the early-return
  repopulates `protected_tests` from `authored_tests`/`proctor_edits`.
- **Hygiene exclusion & CRLF normalization — FALSE-POSITIVE (verified):** the tamper guard fires
  independently of hygiene (gutted assert / deletion / reformat all still trip; CRLF-only correctly
  ignored); path formats are both POSIX (no straddle); the `\r\n`→`\n` normalization is a strict subset
  of CPython's own tokenizer normalization, so a hash collision implies a Python-identical program
  (no behaviour hideable, no `\r\r\n` laundering).
- **ACCEPT (fail-safe residuals):** a bare-`\r`/old-Mac ending over-flags (opposite of the security
  concern; ADR-scoped to `\r\n`); any hypothetical future path-format skew degrades to a false-positive
  park, never a missed tamper.

## Rejected

- **Format the authored tests at author-time (baseline the post-format content).** Would also work and
  would ship ruff-formatted authored tests — but it runs a formatter+lint-fix on the oracle (risking an
  F-class "unused import" removal) and is more code. Decision 1 (never touch the oracle) is minimal and
  trust-boundary-cleaner. Follow-up: have the scaffold EMIT ruff-style output so the DELIVERED authored
  tests are formatted for the target repo's CI.
- **Shipping run-once/CRLF alone as the fix (my first attempts).** Phase-0 REFUTED both against a live
  MCB-13 — the dominant cause was the hygiene formatter, found only by capturing author-vs-check content.
  (Exactly why Phase-0 runs BEFORE merge.)

## Consequences

- `hygiene_node` excludes protected tests; `hash_files` is newline-normalized; `author_tests_node` runs
  once (and repopulates `protected_tests` on resume); the scaffold `_write` OVERWRITES (never
  skip-if-exists — red-team FN1). No new knob, no migration. Classifier and gate untouched (the fix is
  upstream, in authoring/hygiene/hashing).
- Tests: `autofix` rewrites single→double quotes (the mechanism); `hash_files` is newline-agnostic but
  content-sensitive; the scaffold re-run is a no-op leaving the frozen original intact; `author_tests_node`
  re-authors nothing when already authored.
- Payoff: a fresh esc-OFF baseline (the tamper cluster converts to `clean_deliver`/`honest_park`,
  clean-conclusion recovers well above 65%, `false_ship` ≈ 0). Numbers land in CHANGELOG with the snapshot.
