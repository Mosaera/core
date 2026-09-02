# MCB-28 measured: ADR-0098's mechanism WORKS, and a new blocker is now visible

**Status: the owed MCB-28 result.** 10 runs (5 per tester model). The mechanism is proven to break
the deadlock it was built for. The case still delivers **0 of 10** — for two reasons that are now
named, one of which is a precise, previously invisible defect in the critic.

## The result

| | arm 1 — tester `qwen3-coder:30b` (default, = the coder) | arm 2 — tester `qwen3.6:35b` |
|---|---|---|
| Proctor restated the test | **0/5** | **2/5** |
| `tests_tampered` | 5/5 | 3/5 |
| delivered | 0/5 | 0/5 |
| grader would have passed | **5/5** | **5/5** |
| over-park | 5/5 | 5/5 |

All ten runs produced **correct code** and all ten were refused.

## ADR-0098 works — proven, twice

The open question was compliance: the targeting is deterministic and provably fires, but whether
the *model* acts on it had never reached a stored record. On the two runs where it did:

```
COMPLIED  honest_park  proctor_edits=['tests/test_pricing.py']
          gate_reasons=['critic_vetoed']     <- the ONLY reason left
          unsat_kinds={}                     <- every claim satisfied
```

`tests_tampered`, `validation_failed` and `claim_behavioral_failed` **all disappear**. The deadlock
ADR-0098 targets — *the item requires editing a protected test → editing it stalls the run →
`amendment_offer` correctly refuses a run that already tampered* — is fully broken when the Proctor
does what it is told. That is the mechanism working end to end, and it had never been observed.

**Compliance is the bottleneck.** 0/5 on the default model, 2/5 on the larger one. Pre-registered
reading: n=5 separates "complies most of the time" from "almost never", and nothing finer — so
0/5 vs 2/5 is *suggestive*, not a measured model effect. It is worth noting that the same larger
model was [refuted as a general over-strictness lever](tester-model-probe-2026-08-11.md) hours
earlier; helping here and hurting there is consistent with the heterogeneity that refutation found.

## The new blocker: the critic vetoes a run for succeeding

Both compliant runs were vetoed, and the reasons are the finding:

- *claim `task-c3`: "The checkout code in `pricing/checkout.py` calls it on every order, and the
  existing test suite asserts the current raw-float result" — unmet*
- *claim `task-c10`: "The existing test asserts the OLD unrounded result" — unmet*

**Both are narrative context describing the PRE-change state.** Both were minted with
`oracle_kind: none`, so the deterministic oracle correctly ignores them. `nodes_critic.py` does not:

```python
claims = [c for c in (state.get("claims") or []) if isinstance(c, dict)]   # every claim, unfiltered
```

For a MODIFY item this is self-defeating by construction. The brief must describe what the code
does *today* in order to say what to change, and a correct change **necessarily falsifies those
sentences**. The critic then reports them as unmet requirements and vetoes. The better the work, the
more certainly it is refused.

This is the same shape as the rest of this arc — a mechanism reading a field that was never meant
for it — and it explains the 5 sole-cause `critic_vetoed` over-parks
[already flagged](over-park-attribution-2026-08-11.md) as the next lead. That lead now has a cause.

**Not fixed here.** It is outside slice 4's scope, it touches the veto path, and the fix has a real
design question behind it: `oracle_kind: none` means "no deterministic oracle exists", which is not
the same as "not a requirement" — filtering on it alone would blind the critic to genuine criteria
the deterministic layer cannot check, which is precisely what the critic exists for.

## Measurement gap, owed

`proctor_edits == []` conflates **"the Proctor never edited"** with **"the Proctor edited and the
assertion-profile check refused it as a weakening"**. Both leave the field empty and both let the
tamper guard fire, and they need opposite fixes. The run computes `amendment_refusals` for exactly
this, and it does not reach the card. Record it before drawing conclusions from arm 1's 0/5.

## Disposition

- **ADR-0098's "Owed: the MCB-28 result" is answered:** the mechanism works; it is not sufficient
  alone.
- **Slice 4 is not the reason MCB-28 fails.** Its oracle mints and satisfies `task-c5`
  (`consumer_impact`), and its amendment targeting fires correctly.
- **Next:** the critic's claim filter, then re-measure. Compliance is worth a second look only
  after that, since the critic currently refuses the runs that comply.
- Corpus archived: `~/mosaera-backups/corpus-mcb28-2026-08-11.tar.gz` (10 cards, both arms).
