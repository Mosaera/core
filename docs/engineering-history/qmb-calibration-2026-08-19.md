# QMB calibration — can the instrument be trusted to rank models? (2026-08-19)

Before QMB is used to choose a model for the PM seat, the test has to be shown to decline when there
is nothing to find. This records that check, its one alarming result, and why that result did **not**
condemn the design.

**Model:** `gpt-oss:20b`, PM temperature 0.2 (hardcoded per role, `team.py:58`; no sampling knob
exists). **Suite:** 6 cases for the first control, 9 for the repeats — a corpus discontinuity, so
the counts are not comparable across it, only the splits.

## The method

A **null control** runs one model as both arms. Any difference is noise by construction. Its job is
not to produce a threshold — an earlier version of this design made that mistake and is corrected in
`arms.py` — but to answer one question: *does the test name a winner when there is provably none?*

## The results

| run | passes | discordant | split | p | named a winner? |
|---|---|---|---|---|---|
| 1 | 5 | 12 of 70 | **10 / 2** | **0.039** | **yes** |
| 2 | 3 | 8 | 4 / 4 | 1.000 | no |
| 3 | 3 | 8 | 3 / 5 | 0.727 | no |
| 4 | 3 | 8 | 4 / 4 | 1.000 | no |

Run 1 named a winner between a model and itself, and the CLI declared the test MISCALIBRATED.

**That verdict was wrong, and it was the instrument overclaiming for the fourth time.** At α=0.05 a
correctly calibrated test produces p<0.05 in about 5% of null experiments *by construction* —
p=0.039 from a single run is exactly what that looks like. One null control can reassure; it cannot
condemn. The message now says so.

**The interpretation was pre-registered before the repeats ran:** arm A winning ≥2 of 3
directionally would mean a systematic order effect and would invalidate paired comparison until the
arms were interleaved; scattered directions would mean chance. Arm A won **0 of 3** — two ties and
one favouring B.

1 significant result in 4 null controls is consistent with α=0.05 (P(≥1 in 4) ≈ 18%). **No evidence
of miscalibration.** The suspicion that made run 1 worth chasing — arm A ran first and had 3 unusable
replies against arm B's 1 — did not survive contact with more data.

## What the floor actually is

Roughly **20% of paired trials disagree when one model is run against itself** (12/70, then 8 each
at fewer passes), and the disagreement is **symmetric**. That is the sampling noise any real
difference has to show through, and symmetric noise is exactly what McNemar is built for: it tests
the *split*, not the count.

## Standing rules this establishes

- **Run the null control before quoting any ranking**, and repeat it. One clean control is
  reassurance, not proof; one dirty control is suspicion, not a verdict.
- **Pre-register the interpretation** before the repeats, so a result cannot be read backwards into
  whichever story it fits.
- **Read raw output before believing a score.** Every instrument defect found so far — five now —
  came from reading proposals or splits, never from reading a rate.

## Instrument defects found so far, all by running it

1. The scorer could not see the curate path's output; nearly published "F60 reproduced 5/5".
2. An empty model reply scored as a wrong answer rather than an absent measurement.
3. The null control was wired as a count threshold that would have discarded a 13-to-1 split.
4. The model-availability guard consulted a list containing the very name under test, so it could
   never refuse.
5. `discordant_needed` raised `OverflowError` — the textbook binomial form cannot produce an answer
   at the sizes a power search reaches.

Plus four overclaiming reports: min–max spread labelled "variance", a single-case dimension labelled
the same, the null floor as a filter, and run 1 labelled MISCALIBRATED.

## First real comparison — and what it could not tell us

`qwen3.6:35b` vs `gpt-oss:20b`, 9 cases, 5 passes, paired on (case, dimension, pass).

| arm | wall clock | unusable |
|---|---|---|
| `qwen3.6:35b` | **2557s** (42.6 min) | 2 |
| `gpt-oss:20b` | **148s** (2.5 min) | 2 |

`discordant 12 · concordant 108 · p=0.146` → **NO WINNER, TOO_CLOSE_TO_CALL** (~17 discordant
trials would have been needed).

The models agreed on 108 of 120 paired trials. **17.2x the latency for no difference this suite can
resolve.** For a seat on the interactive path — the same PM turn that enforces a 3-second deadline
on its GitLab read — that settles the practical question without the quality one being answered.

Read the verdict precisely: `TOO_CLOSE_TO_CALL` means *this suite at this size cannot resolve a
difference*, NOT that the models are equivalent.

### Three reporting defects the run exposed, now fixed

1. **The split was not printed.** McNemar is symmetric, so 9/3 and 3/9 give the same p — the
   direction was unrecoverable, and the run could not say which model won the trials they disagreed
   on. That is the entire question a comparison exists to answer.
2. **The raw data was discarded.** `run_comparison` persisted nothing, unlike `run_sweep`. Forty-three
   minutes of GPU time produced six lines of text and no trials to re-examine — so the one
   verification step that has caught every defect in this suite was impossible.
3. **"no null control was run" was misleading.** Four had been run; the CLI simply never threaded
   the measured floor into a comparison, so the note was true of the invocation and false about
   what was known.

A comparison now records the split, every discordant trial with the model that passed it, and is
written to disk even when the verdict is "too close" — because the expensive arm was the one whose
evidence got thrown away.

## Re-read per dimension: the pooled verdict was hiding two real, opposing leans

The re-run persisted its disagreements, so the same data could be re-scored without paying for the
arm again. Per dimension:

| dimension | qwen3.6:35b | gpt-oss:20b | leans | p |
|---|---|---|---|---|
| complete | 2 | **7** | gpt-oss | 0.180 |
| **safe** (primary) | **6** | 1 | qwen | 0.125 |
| grounded | **4** | 0 | qwen | 0.125 |
| consistent | 0 | 1 | — | 1.000 |

**The pooled 12/9 is `(2+6+4)` against `(7+1+1)` — the DIFFERENCE of two real leanings.** It shrank
toward "no effect" exactly where the models diverge most: `gpt-oss:20b` swept all five passes of
QMB-05 completeness (the case that must propose a `delete` when asked to deduplicate), and
`qwen3.6:35b` swept all three of QMB-06 grounding (the F60 case).

This is the repo's canonical finding-shape, previously stated three times and never mechanized:
*"The finding is the heterogeneity, not the average… shipping it on the pooled number would have
been shipping a coin-flip."*

**Still no winner, and the leans are still not significant** (0.125–0.180 against α=0.05). The change
is not that a ranking appeared; it is that "no difference" was the wrong description of the data.

### The pre-registration

Four dimensions tested at α=0.05 name a spurious winner 18.5% of the time. `safe` is fixed as the
**primary** — the verdict comes from it alone, at full α — because its failures are the irreversible
ones: a wrong completeness call costs a re-run, a wrong safety call deletes the record of delivered
work, which is what a live PM proposed the same day. Secondary dimensions report split and p but
their winner is **stripped structurally**, so no caller can read a ranking out of one. The constant
lives in code with its reason, because a primary chosen after seeing data is not a primary.
