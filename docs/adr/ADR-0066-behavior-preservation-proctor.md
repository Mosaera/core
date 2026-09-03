# ADR-0066: The behaviour-preservation Proctor — a differential refactor oracle

- Status: accepted
- Date: 2026-07-20
- Owners: Mosaera core (correctness-oracle arc, run-reliability `#43`; the "rigorous spec-derived
  Proctor" phase — re-sequenced ahead of dynamic per-test verification by the MR-A smoke)
- Related: ADR-0062 (`#57` over-strictness DETECTION — this extends its detector + reuses its repair
  seam), ADR-0065 (the held-out critic — the backstop for any residual false-ship), ADR-0058 (the
  Proctor test-steward / validate-repair turn), ADR-0013 (the test-first Proctor), ADR-0057 (the
  autonomous oracle posture), ADR-0061 (v1 correctness gate). Owner decision: prompt-led + measured.
- **Not a trust-boundary change** — it changes how the Proctor is *guided* to author tests
  (persona + instruction) + adds a deterministic over-strictness *finding*; it touches no gate,
  policy, allowlist, or oracle-credit logic. Verification is by measurement, not a red-team gate.

## Context — the over-strict honest-park

The MR-A (held-out critic) smoke surfaced the *active* bottleneck on the one refactor case (MCB-05,
`capability="refactor"`): it **honest-parks** (`overstrict_vs_ref: 6`) instead of delivering the
correct refactor. Two root causes, both in how the Proctor authors the acceptance suite:

1. **Wrong hand-computed goldens.** The Proctor has **no `sandbox_exec`** (`policies/allowlist.py`),
   so for a refactor it *hand-computes* expected numbers (26.6, 53.6, … a chain of discount +
   shipping + tax) by LLM reasoning — and the weak local model gets them wrong. A correct refactor
   then "fails" those wrong assertions → no green suite → honest-park.
2. **Over-pinned structure.** For the loosely-worded "delegate to ≥3 helpers" requirement, the
   Proctor pins *specific private helper names* (`"_apply_discount" in source`); a correct refactor
   that names its helpers differently fails.

The critic (ADR-0065) cannot help here — it is veto-only, so it can turn a bad ship into a park but
cannot rescue correct code that the over-strict suite blocks from going green. This is a
*reliability* loss (correct work honest-parks), which is what the ~99% clean-conclusion bar is about.

## Decision

Teach the Proctor the classic safe-refactoring oracle — a **differential golden-master paired with a
loose structural check** — for behaviour-preserving tasks, prompt-led and measured. Five pieces:

1. **A deterministic detector** — `behavior_preservation.is_behavior_preserving(task, plan, design)`.
   Deny-by-default: fires only on an EXPLICIT preservation clause in the trusted spec ("without
   changing behaviour", "preserve behaviour", "same output", "pure refactor", …), never on the bare
   word "refactor" (a feature that mentions refactoring must not trip it). No LLM, no I/O.

2. **The differential golden-master pattern** (persona `tester.md` + injected instruction): while the
   original code still exists (author_tests runs before implement), FREEZE it — `read_file` the
   module and `write_file` a verbatim copy to `tests/_frozen_<module>.py` — then a test imports BOTH
   the changed module and the frozen copy and asserts they return EQUAL results across generated
   inputs (stdlib `random`/`@parametrize` — **not** `hypothesis`, which the sandbox image lacks — plus
   the spec's named edge cases). **No hand-computed values**, so the wrong-golden failure mode is
   gone; and it is STRONGER than hand-picked goldens (it catches any behaviour-changing mutation, so
   the mutation gate rewards it).

3. **The loose structural check** (paired): assert the PROPERTY the task states — a short orchestrator
   + ≥N module-level helpers, via `ast`/`inspect` — NEVER a specific private helper *name*. This is
   what REDS on the undecomposed seed, so the suite keeps its red-phase (a pure golden-master is green
   pre-impl → the `already_satisfied` misroute; the structural pairing is what avoids it).

4. **A new over-strictness finding** (`faithfulness.py`): emit `source_introspection` as a standalone
   `OverstrictFinding` — an assertion that pins a specific PRIVATE symbol NAME against module source
   (`"_helper" in src`, `hasattr(mod, "_x")`) the spec did not name (the exact MCB-05 over-pin).
   Deny-by-default/one-sided like the rest; a spec-quoted name and a public API name are never
   flagged. It NAMES the pin for the `#57` repair turn AND the ADR-0065 critic hint, and raises
   `overstrict_static` so the scoreboard measures it.

5. **Knob + posture + measurement** — `behavior_preservation_guard` (deny-by-default), ON in
   `apply_oracle_posture` for verified autonomous runs; a `MOSAERA_BENCH_BEHAVIOR_PRESERVATION_OFF`
   A/B lever + a `behavior_preservation_detected` per-run meta flag threaded through
   `compare.average()`.

**Prompt-led, not a mechanical rewrite.** The engine detects + NAMES + injects guidance; the Proctor
authors with judgment. This heeds the reverted-auto-rewriter lesson (`faithfulness.py`): "loosening
needs judgment, never a mechanical rewrite." (That reverted feature was also labelled "MR-C" in-code,
so this ships under its own name/ADR to avoid the collision.)

## Consequences

- **Targets the refactor honest-park directly**: a correct refactor can go green (differential
  golden-master ≠ wrong goldens; loose structural ≠ name pin), converting `honest_park → clean_deliver`
  on MCB-05 — the reliability win.
- **Correctness is not weakened**: the differential-across-inputs oracle is stronger than hand-picked
  goldens (it catches behaviour-changing mutations), the red-phase is preserved via the structural
  pairing, and the ADR-0065 critic remains the backstop. Measured: no new `false_ship`.
- **Deny-by-default containment**: the guidance reaches ONLY a spec-detected refactor; a feature /
  bug-fix authoring turn is byte-identical to before.
- **Honest risk (the #57 reliability caveat)**: the weak local model may not reliably execute the
  multi-step freeze-and-diff pattern from prompt guidance. Measured ON/OFF; if it does not land, the
  logged follow-up is the deterministic golden-master *scaffold* (the engine authors the differential
  test itself), the higher-ceiling option deferred at planning.

## Measured result — posture activation HELD (2026-07-20)

The MCB-05 ON/OFF smoke (the payoff test) **did not validate the prompt-led approach, and surfaced a
correctness regression signal** — so the posture activation was withdrawn (the guidance stays behind
its default-OFF knob; the detector + the `source_introspection` finding stay live).

| Arm | Outcome | `overstrict_vs_ref` |
|---|---|---|
| bp ON (run 1) | **`false_ship`** (delivered, hidden grader FAILED; critic did not veto) | 1 |
| bp ON (run 2) | `honest_park` | 2 |
| bp OFF (1 run, killed after) | `honest_park` | 1 |
| pre-ADR-0066 (MR-A smoke) | `honest_park` | 6 |

- **No reliability win**: NEITHER ON run delivered *correctly* (no `honest_park → clean_deliver`).
- **A false-ship on the ON arm the OFF arm did not show**: the weak local Proctor (`qwen3-coder`),
  told to author a differential golden-master + loosen, wrote a suite loose enough to let a WRONG
  refactor SHIP — the exact false-ship reopening the #57 auto-loosen revert was reverted for. The
  ADR-0065 critic (local `gpt-oss:20b`) failed to veto it (the predicted weak-local-critic limit).
- `overstrict_vs_ref` did drop (6 → 1–2), but noisily and not attributably (a 2-run sample), and a
  lower over-strictness that comes with a false-ship is not a win.

**Disposition (correctness-first, the #57 precedent):** withdraw the posture activation — the exact
"one-line knob rollback" this arc's changes carry. The prompt-led hypothesis is **refuted on the weak
local model**; the plan's own escalation condition ("if the weak model doesn't execute the pattern,
escalate to the deterministic scaffold") is now met. The **follow-up is the deterministic golden-
master scaffold** (the engine freezes the original + authors the differential test itself, so
correctness does not depend on the weak model authoring it), measured correctness-neutral before any
re-enable. The detector, the injected-guidance-behind-the-knob, and the `source_introspection`
over-strictness finding (pure DETECTION, no loosening) remain as the substrate for that work.

## The deterministic scaffold — the safe successor (2026-07-20)

The prompt-led form failed because it asked the WEAK model to author the differential oracle. The
successor moves the authoring INTO the engine: for a detected refactor, `refactor_scaffold.py`
deterministically writes a verbatim FROZEN copy of the target module + a generated test that (1)
asserts the changed module's public functions return the SAME value/exception as the frozen original
across many inputs, and (2) asserts the change DECOMPOSED (more top-level functions than the frozen
original — name-agnostic). It runs in `author_tests_node` (original code intact) and, when it
authors, **replaces** the weak Proctor's authoring for that run. Behind `refactor_oracle_scaffold`
(posture ON — it validated: reds on the seed, greens on a correct decomposition, catches a behaviour
change). The prompt-led `behavior_preservation_guard` stays OFF.

**General, not case-specific** (an explicit design goal): the target module is found by IMPORT, inputs
are lifted from the existing tests' LITERAL calls and mutated with generic numeric boundaries
(0/1/5/9/10/11/50/100) + bool flips + the signature's optional params, and the decomposition check is
name-agnostic. **Honest limits** (it no-ops → the Proctor authors, never a break): it fires only when
there are existing tests with LITERAL-arg calls to the module's public functions; it targets
ROOT-LEVEL modules; and its "decomposition" signal is "more top-level functions" (an extract-helpers
refactor — not a method/class reshuffle). Its behaviour coverage is only as wide as the existing
tests' inputs × the mutation spread — strong for numeric/boundary logic, weaker for opaque inputs.

## Verification

- The four gates via their equivalents (`ruff format --check` + `ruff check` + `check_file_sizes.py`
  + `check_layer_imports.py` + `mypy` + full offline `pytest`).
- Unit: the detector fires on MCB-05 and NOT on MCB-09/10/04; `source_introspection` flags a private
  name pin and NOT a spec-named or public name; the guidance injects only when guarded + detected.
- Live smoke (the payoff): `mosaera-bench MCB-05` ON vs `MOSAERA_BENCH_BEHAVIOR_PRESERVATION_OFF=1` —
  target `honest_park → clean_deliver` + `overstrict_vs_ref` ↓, correctness held; MCB-09/10 unaffected.
