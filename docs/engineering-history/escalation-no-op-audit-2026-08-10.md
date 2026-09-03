# 45 of 61 stored escalations never happened (2026-08-10)

**Status: FIXED** (ADR-0016 Amendment 1). This record exists so the affected cards stay
identifiable and so the audit is reproducible rather than re-derived.

## What was wrong

An escalation to an unreachable cloud tier fails every model call, contributes nothing, and — before
the fix — was returned as the run's outcome, **overwriting the tier-0 result that had really
happened**. `error` stayed `None`; `escalation_path` still named the model. A failed escalation was
therefore indistinguishable from *"a stronger model tried and could not."*

Found because the owner said the account has no Anthropic credits, so the Sonnet-5 escalations the
cards reported could not have returned anything. Nothing in the stored record would have revealed
it.

## The audit, reproducibly

Run from the repo root, over `<MOSAERA_HOME>/benchmarks/MCB-*/*.json`:

```python
AGENT = {"coder": "Coder", "tester": "Tester", "reviewer": "Reviewer",
         "critic": "Critic", "pm": "PM"}
path = card["meta"]["escalation_path"]          # e.g. ["coder: ollama/x -> anthropic/y"]
role  = path[-1].split(":")[0].strip()
rows  = {r["agent"]: r["calls"] for r in card["cost"]["by_agent"]}
no_op = rows.get(AGENT[role], 0) == 0
```

| cards with an escalation | 61 |
|---|---|
| escalated role made calls (real) | 16 — all on-box `ollama` targets |
| escalated role made **zero** calls (no-op) | **45 — every one targeting `anthropic/claude-sonnet-5`** |

**Do not audit this via `by_model`.** The card's `cost` copies only
`total_tokens / usd / calls / by_agent` — `by_model` is never written, so a `by_model`-based check
returns "no row for the escalated model" for *every* card and reports a vacuous 61/61. That mistake
was made first here; it is recorded so it is not repeated.

## Consequences for existing numbers

- The 45 cards are **not deleted** — they are the evidence. Any aggregate spanning them mixes real
  outcomes with runs whose producer never spoke.
- The 2026-08-09 52-run integration sweep contains **3** such cards (MCB-17, MCB-22, MCB-28). The
  other 49 stand.
- One of those three was cited as evidence that verb-arc slice 3's inadmissibility rule failed to
  suppress an escalation (MCB-22). That escalation was a no-op, so the finding is weaker than it was
  first reported — slice 3's `final`-vs-`terminal_state` defect is real and separately pinned by
  test, but MCB-22 is not the proof of it.
- Six MCB-27/28 runs from 2026-08-10 were void; re-run at tier 0, both cases pass the hidden grader.

## The generalisable point

This is the session's recurring shape, in the instrument rather than the product: **a path that
fails silently is indistinguishable from a path that ran and produced that answer.** The guard built
for exactly this hazard (`cloud_tier_allowed`) checked that the model was *priced*, because pricing
is what bounds the USD cap. Nothing checked that it was *reachable* — and reachability cannot be
established before the call, so the only honest check is post-hoc: did the producer actually speak?
