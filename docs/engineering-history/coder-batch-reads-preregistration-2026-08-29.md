# Pre-registration: does letting the coder batch its reads cut round trips? (2026-08-29)

**Status: STAGE 0 MEASURED NULL 2026-08-29 — the permission does not land; Stage 1 was NOT run.
See the RESULT section at the foot.**

Everything from here to the RESULT was written **before** any data existed, deliberately, so the
outcome could not be re-narrated afterwards. It is left unedited — including the predictions that
failed and the instrument that turned out not to exist. The knob (`coder_batch_reads`) ships
**default OFF**; this file is what it had to beat, and did not.

## Why we think there is anything here

Per-run cost is **round trips × a flat context re-send tax** — the coder's profile is ~97% input
tokens, so turn *count* is the lever, not thinking.

Two facts, both measured 2026-08-28/29:

1. **The capability is live.** `qwen3-coder:30b`, probed directly with one bound read-only tool and
   a task needing three files, returned **three `read_file` calls in a single assistant message**.
2. **Production never uses it.** Run `20260828-202022-5a07ae` made 116 tool calls; the median gap
   between consecutive calls is **2.9s** — a model round trip every time. The only sub-100ms pairs
   were `running_validation` → `environment_facts`, which is engine bookkeeping, not model batching.

Tool mix in that run: `file_read` 35, `file_written` 30, `search` 12, `running_validation` 10,
`environment_facts` 10, `sandbox_exec` 9, `validation` 6, `list_files` 4. **Reads are 51 of 116
(44%)** — the batchable share, because they do not gate.

Likely cause: the prompt frames every interaction as a sequence ("search first, then `read_file`")
and never says several may go at once. The change is a **permission**, not an instruction —
`CODER_SYSTEM` already prohibits spawning throwaway files and run `20260828-195437-b87e0c` wrote
three anyway, so a prohibition is weak evidence a directive will land. A licence to do the cheaper
thing is a different ask, but that reasoning is a belief and this sweep is what tests it.

## Metric

**Primary: coder model calls per run.** It is what the change acts on directly (a batched turn is
one round trip instead of N) and is far less noisy than tokens.

Secondary, reported not gated: total tokens, wall clock, tool-call counts by kind.

**Guardrails — any breach fails the arm regardless of the primary:** `false_ship` stays 0;
over-park does not increase; delivered-count does not fall.

## Noise floor, computed BEFORE the sweep

Over every surviving scorecard carrying a Coder `calls` figure:

| tier | runs | cases | mean | sd | cv | naive n/arm −20% | −30% |
|---|---|---|---|---|---|---|---|
| trivial | 25 | 2 | 44.3 | 25.0 | 0.57 | 126 | 56 |
| moderate | 118 | 16 | 18.8 | 15.4 | 0.82 | 263 | 117 |
| hard | 55 | 7 | 30.0 | 31.8 | 1.06 | 441 | 196 |

**The naive numbers are the wrong ones, and this is the finding that shapes the design.**
Decomposing moderate:

- **between-case sd of case means: 14.7**
- **median within-case sd: 8.6**

Most of the pooled variance is *between cases* — MCB-23 averages 62.2 coder calls, MCB-16 averages
6.8. That component does **not** shrink by adding runs, so a pooled unpaired comparison is mostly
measuring which cases got sampled.

## Design that follows from it

**Blocked by case: both arms run the SAME cases, compared within-case.** That cancels the 14.7
between-case term and leaves the 8.6 within-case noise.

With 16 moderate cases × 5 runs per arm: a case's mean difference has sd ≈ 8.6·√(2/5) ≈ 5.4, so the
SE of the averaged difference is ≈ 5.4/√16 ≈ 1.36. Detecting a 20% cut (Δ ≈ 3.8 calls) needs
Δ > 2.8·SE ≈ 3.8 — **just powered**.

- **Moderate tier: 16 cases × 5 runs × 2 arms = 160 runs.** At the measured ~20 runs/h, **~8 hours**
  — one overnight.
- **Trivial tier: 2 cases only.** Reported as descriptive, never as the result. Two cases cannot
  distinguish "trivial tasks batch better" from "MCB-01 and MCB-02 do".
- **Hard tier: excluded.** cv 1.06; nothing affordable can resolve it.

## Recorded predictions

Stated now so they can fail:

1. **Coder calls on the moderate tier fall by ≥20%** in the ON arm (paired by case).
2. **`false_ship` stays 0** and over-park does not increase.
3. **Batching actually appears**: sub-100ms tool-to-tool gaps rise from ~0 (excluding the
   `running_validation`→`environment_facts` pair) to a clearly non-zero share. *If prediction 3
   fails, 1 is uninterpretable* — the model ignored the permission, and the result says nothing
   about whether batching helps.

## The honest ceiling

Reads are 44% of tool calls. Even perfect 3:1 batching of every read leaves the other 56%
untouched, so the ceiling on this lever is roughly a **30% cut in coder round trips**, not more.
Anything above that in the result is a signal something else moved and should be investigated, not
celebrated.

## Scope

All 26 MCB cases are Python **by design** — Python is the foundation the other languages will be
built on, so a bound measured here describes Python work, which is the product today. That is a
scoping decision, not a gap; it does mean this result must not be quoted as a general claim.

## Prior art

`coder_diagnose_loop` is the closest precedent (a coder-prompt knob the bench A/Bs). The over-park
work is the cautionary one: several prompt-level changes measured null after the fact, which is why
the noise floor is above the fold here rather than in the write-up.


## Staged gate — added 2026-08-29, before any run

The 160-run sweep above is booked only if the mechanism works. Splitting it, and writing the stop
condition down now rather than after seeing the data:

### Stage 0 — mechanism check (~10 runs, ON arm only, trivial tier)

**Question: does the model take the permission at all?** Not "how much does it help" — that is
Stage 1. This is close to binary and needs almost no runs: either sub-100ms tool-to-tool gaps
appear in the transcripts or they do not.

No OFF arm is run. The baseline is already established: run `20260828-202022-5a07ae` made 116 tool
calls with a **median gap of 2.9s and zero model batching**, the only sub-100ms pairs being the
`running_validation` → `environment_facts` engine pair. That is what OFF looks like, measured.

Trivial is the right tier for this despite its 2 cases, because it has the highest read volume — if
batching shows anywhere it shows here. **The Stage-0 result is a mechanism verdict only and must
never be quoted as an effect size**; 2 cases cannot distinguish "trivial tasks batch" from "MCB-01
and MCB-02 batch".

**Stop condition, recorded in advance:** if sub-100ms non-engine tool gaps stay at ~0, Stage 1 is
NOT run. The permission did not land, and the finding is about the model ignoring a prompt licence
— not about whether batching would have helped. The successor is then the deterministic option:
a `read_files(paths: [...])` tool that takes several paths in one call, removing the model's
discretion rather than asking it to choose well (Deterministic-First).

### Stage 1 — the powered sweep (160 runs, moderate tier, blocked by case)

Exactly as designed above. Run only if Stage 0 passes.

### Why this ordering

Stage 0 costs ~30 minutes and can save 8 hours. It also protects the interpretation: without it, a
null Stage-1 result is ambiguous between "batching does not help" and "the model never batched",
and those have opposite successors. Prediction 3 existed to catch that; the gate makes it cheap
enough to actually check first.


## RESULT — Stage 0 measured 2026-08-29: the permission does not land. Stage 1 NOT run.

**Prediction 3 failed, and the pre-registered stop condition fires.** Recorded here against the
predictions above, which were written before any data existed.

### Correction to the method, made before the result was known

Stage 0 as designed read tool-gap timing out of run transcripts. **That instrument does not exist
for bench runs** — the event stream with per-tool timestamps comes from the live API
(`/api/runs/{id}/transcript`), and `mosaera-bench` writes a scorecard, a report and a patch, no
event log. The planned measurement could not have been taken as specified.

Substituted a more direct instrument for the same mechanism: build the **real** coder system prompt
both ways via `coder_system(..., batch_reads=)`, bind tools under their real names
(`read_file`, `search`, `list_files`, `edit_file`), give one realistic multi-file ask, and count
tool calls per assistant message. It isolates exactly the link under test — clause → emission — and
runs in seconds rather than minutes. It does **not** measure whether batching would help; that was
always Stage 1.

### The numbers

`qwen3-coder:30b`, temperature 0.7, 30 turns per arm:

| arm | turns batching (>1 tool call) | mean calls per message |
|---|---|---|
| clause OFF | **0 / 30 (0%)** | 1.00 |
| clause ON | **1 / 30 (3%)** | 1.03 |

An earlier n=10 pass read 0% / 10%; the larger sample moved ON *down* to 3%. The effect is
indistinguishable from nothing.

### What this means, stated narrowly

The model **is** capable — probed in isolation with a bare prompt and one bound tool it returns
three `read_file` calls in a single message. Under the **real** system prompt it does not, with or
without the clause. The likely reason is that the surrounding prompt dominates: ~2,000 words that
frame every interaction as a sequence ("read it first, then `edit_file`"; "search for the symbol
first, then `read_file`") swamp one added paragraph of permission.

That is the same shape already on record: `CODER_SYSTEM` prohibits spawning throwaway files and run
`20260828-195437-b87e0c` wrote three anyway. **This engine's prompt-level levers on this model are
weak in both directions** — a prohibition it ignores, and now a permission it declines. That
generalises beyond this experiment and is the more useful finding.

A single live confirmation, not powered but consistent: the smoke run
(`20260829-131644-488393`, MCB-01, clause ON) used **75 coder calls** against a historical mean of
56.0 (sd 21.1, n=15) — no improvement, well inside noise.

### Disposition

- **Stage 1 (160 runs, ~8h) is NOT booked.** Per the stop condition. Running it would measure the
  effect of a clause the model does not act on, and a null there would have been misread as
  "batching does not help".
- **Successor: the deterministic option**, as named in advance — a `read_files(paths: [...])` tool
  taking several paths in one call. It removes the model's discretion instead of asking it to
  choose well, which is what Deterministic-First says to do when a model-judgement path measures
  unreliable. The round-trip arithmetic is unchanged: reads are 44% of tool calls, so the ceiling
  is still ~30% of coder round trips — but a tool call the engine defines is not subject to a 3%
  compliance rate.
- **The knob stays, default OFF, now recorded as MEASURED NULL** rather than unmeasured — matching
  the `oracle_structural_spec` precedent, so the arm stays re-runnable against a future model
  without rebuilding it. It should be **removed** if and when `read_files` lands, since the two
  solve the same problem and the prompt clause would then be inert surface.

### Cost

Stage 0 cost about 25 minutes including the two false starts, and saved the 8-hour sweep. The
staged gate was worth more than the sweep would have been.
