# MCB-28 delivers: the MODIFY chain works end to end (2026-08-11)

**A behaviour-change item completed autonomously for the first time.** One run, `clean_deliver`,
**zero gate reasons**, hidden grader passed. The remaining bottleneck is named and it is not a
mechanism — it is model compliance.

## The measurement

Same case, same 5-runs-per-tester-model design, before and after
[ADR-0100](../adr/ADR-0100-critic-may-not-veto-an-unbound-claim.md):

| | before the critic fix | after |
|---|---|---|
| Proctor complied | 2/10 | 1/10 |
| **delivered** | **0/10** | **1/10** |
| **delivered *given* compliance** | **0 of 2** | **1 of 1** |
| grader would have passed | 10/10 | 10/10 |

The headline rate barely moves because compliance dominates it. The conditional is the result:
**every compliant run used to be vetoed, and now ships.**

```
COMPLIED  clean_deliver  deliver=True  grader=True  gate_reasons=[]
```

## The chain, now verified link by link

1. **ADR-0097** mints `task-c5` (`consumer_impact`) and the oracle satisfies it.
2. **ADR-0098** names the pre-existing test — `modify_amendment_targets=['tests/test_pricing.py']`
   on **all 10 runs**, so the targeting is confirmed live rather than replayed by hand.
3. The Proctor restates it (when it complies) → `proctor_edits=['tests/test_pricing.py']`.
4. The deadlock clears: `tests_tampered`, `validation_failed`, `claim_behavioral_failed` all gone.
5. **ADR-0100** stops the critic vetoing the premise claims that used to be the last blocker.
6. `clean_deliver`.

Every step of that was a separate day's finding. This is the first run in which all of them held at
once.

## The new instrumentation resolved the open ambiguity on its first use

Yesterday `proctor_edits == []` meant either *"the model ignored the instruction"* or *"the model
edited and the assertion-profile check refused it as a weakening"* — opposite fixes, indistinguishable
from the record. On all nine non-compliant runs the card now reads:

```
targets  = ['tests/test_pricing.py']   <- it WAS told
refusals = {}                          <- nothing was refused
proctor_edits = []                     <- and it made no edit
```

**Unambiguous model non-compliance.** Not a rejected repair, not a targeting failure. That
distinction cost a hand-replay against the case seed the day before and is now free on every run.

## What is left

**Compliance is the bottleneck, and it is a model property, not a mechanism.** 0/5 on the default
tester (which is also the coder), 1/5 and 2/5 on a larger one across the two measurements — n=5
each, so the model difference remains *suggestive*, not measured. The instruction is deterministic,
unambiguous, and provably delivered; the model simply does not act on it most of the time.

That is the same ceiling the [tester-model probe](tester-model-probe-2026-08-11.md) hit from the
other side, and it is a question about model tier rather than about the engine.

**Not claimed:** that the 30% over-park rate has moved. This is one case, ten runs. The critic fix
should help the wider corpus — it prevented 9 of 9 measured vetoes — but that has not been measured,
and the corpus is now 26 cases, so the next sweep is not comparable to the 125-run baseline anyway.

Corpus archived: `~/mosaera-backups/corpus-mcb28-postfix-2026-08-11.tar.gz`.
