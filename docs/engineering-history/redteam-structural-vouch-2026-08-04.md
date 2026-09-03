# Red-team — the structural-vouch verdict (2026-08-04)

**Scope:** the change to `check_structural_compliance` that made a verdict depend on how many
predicates actually executed. Trust-boundary file-domain (the verdict feeds
`satisfied_structural_claim_ids` → `structural_vouch_ids` → `oracle_verified` → the delivery gate),
so red-team-required as a definition-of-done gate. Durable, load-bearing → 3 rounds.

**Target:** *can a vouch still be manufactured, and does the fix create a false-park generator?*
Probes are in the session scratchpad (`rt1.py`, `rt2.py`, `rt3.py`); each is a direct call into the
module, no sandbox needed.

## R1 — can a vouch still be manufactured? **1 FIX-NOW**

| Probe | Before | After |
|---|---|---|
| A1 helper count satisfied, shrink unevaluable (no baseline) | **`True` — VOUCHED** | `None` |
| A2 explicit `<= N` with no baseline | `True` (correct — the number needs no baseline) | unchanged |
| A3 baseline located under a different file key | `True` (correct — a function may move files) | unchanged |
| A4 baseline present but unparseable | `None` | unchanged |
| A5 no work done at all | `False` | unchanged |

**FIX-NOW (A1): a partially-measurable ask vouched.** The brief asks for two things — a short
orchestrator **and** ≥ 3 helpers. With no baseline the shrink half cannot be measured, and passing
the helper count alone reported *"meets the requested structure"*. Half a look is not proof of the
whole shape, and this verdict vouches. Fixed by counting predicates **requested** as well as
executed: `checks_run < requested` ⇒ `None`. No vouch, and no false park either.

A pre-existing test (`test_compliant_refactor_is_met`) had encoded the over-claim — it asserted
`True` with no baseline, two lines below a sibling asserting that no baseline means abstain. It now
supplies the baseline and asserts `True` (proving the capability is intact), with the no-baseline
case pinned separately as `None`.

## R2 — target resolution. **1 FIX-NOW · 1 ACCEPT**

**FIX-NOW (B1): decoy shadowing produced an order-dependent verdict.** The check returned on the
*first* changed file defining the target, so a trivially-compliant `checkout_total` in `decoy.py`
shadowed the real, still-bloated one in `checkout.py` and produced a vouch — while the same two
inputs in the opposite order gave `False`. A verdict that depends on dict insertion order is not
evidence. Every candidate is judged now: an unmet ask **anywhere** downgrades; several
all-compliant definitions are *ambiguous* and abstain rather than vouch.

**ACCEPT (B3): the relocation/stub class.** A tiny top-level `f` delegating to a bloated
`class C: def f(self)` reads as met. This is the same relocation class ADR-0072's red-teams have
**already ACCEPTED twice**, with **Wave-3 predicate authoring** (operator-approved predicates
stating the full contract, ADR-0080 flow) as the named successor. Per the STOP rule — two rounds on
one defect class, stop and escalate — it is **not** third-rounded here. Fail-safe bound unchanged:
every evasion of this class degrades to the pre-claims baseline, because the structural verdict is
downgrade-only plus a vouch that requires *positive* proof; a missed catch is a missed park, never a
new ship channel.

## R3 — does the fix generate false parks? **CLEAN**

| Probe | Verdict | Reading |
|---|---|---|
| C1 correct refactor, baseline present | `True` | capability intact — the vouch path still works |
| C2 correct refactor + unrelated same-named helper elsewhere | `True` | no spurious trigger |
| C3 target defined in two changed files, both compliant | `None` | abstains; `None` has **no effect**, so not a park |
| C4 compliant new definition + a stale bloated one | `False` | honest downgrade — a bloated target still exists |

No capability was lost and no new park channel was created. The three verdicts now sit in the right
directions: `False` on a real unmet ask anywhere, `None` on anything unmeasured or ambiguous, `True`
only when the target is unambiguous **and** every requested predicate ran.

## Verdict

**`clean_deliver`.** Two FIX-NOW findings fixed and pinned; one ACCEPT on a known, twice-accepted
class with a named successor and the STOP rule respected; R3 clean. The module's docstring promise —
*"a `False` can only turn a would-be ship into a park, so it can never manufacture a false_ship"* —
is true again, and now in both directions: it cannot manufacture a vouch either.

**Residual, accepted:** the relocation/stub class (B3), unchanged from ADR-0072's disposition.
