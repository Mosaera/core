# QMB first sweeps — how far is Quincy from a trusted SME? (2026-08-19)

**Instrument:** QMB, 6 cases, `packages/core/mosaera_core/pmbench/`.
**Model:** `gpt-oss:20b` (see *Config finding* below — this is NOT the configured `pm_model`).
**Three sweeps of 5 passes each.** The first two were run with a defective scorer; both defects and
their corrections are recorded here, because they are the most useful result in the document.

The bar being measured is the North Star's, quoted rather than invented: Quincy *"answers from
recorded truth, never guesswork"*, a capability the architecture already marks DIRECTION and
**unbuilt**. The question is how far unbuilt is.

## Headline: the instrument was wrong twice, and reading the score would not have shown it

**Defect 1 — the scorer could not see the answer.** Sweep 1 reported `QMB-06 grounded: 0/5` and
would have been written up as *"F60 reproduced on every pass"* — a clean confirmation of an open
HIGH defect. It was false. `must_contain` searched only the reply, and the **curate path returns no
prose at all**, so every curate case scored zero regardless of what the PM said. The raw proposals
showed the model had carried the required column order into its `enhance` op *every single pass*:

> `'acceptance': 'writes a file … with the header row \`date,amount,category,note\` followed by …'`

The failability test had passed for the wrong reason — its "good" fixture put the string in both the
reply and the ops, so it never exercised the case that mattered. Fixed: the searched text is now the
whole proposal, the test uses `reply=""` exactly as the real path returns, and the mutation
restoring prose-only search kills it.

**Defect 2 — an empty answer scored as a wrong answer.** Sweep 2 then showed `QMB-04 grounded 1/5`.
That one failure was a pass where the model returned an **empty reply**. Scoring silence as error
reports the model as worse than it is — the same principle already encoded for exceptions, applied
inconsistently. Fixed, and deliberately path-specific: a blank *chat* reply is "nothing usable"
(the product has the same concept and its own fallback sentence), but a *curate* returning zero ops
is a real answer and is exactly what the no-op control must produce. A uniform rule would have
silently voided QMB-03.

**Both were found by reading raw proposals, not by reading scores.** That is now the first rule for
any QMB result, including everything below.

## Sweep 3 (both defects fixed)

| dimension | range over 5 passes | cases asserting |
|---|---|---|
| grounded | 0.50 – 1.00 | 2 |
| safe | 0.67 – 1.00 | 6 |
| complete | 0.80 – 1.00 | 6 |
| consistent | 0.00 – 1.00 | 1 |
| honest | 1.00 – 1.00 | 1 |

## The noise floor is larger than the signal, and that is the main finding

Two **identically configured** corrected sweeps disagree about which case fails which dimension:

| case / dimension | sweep 2 | sweep 3 |
|---|---|---|
| QMB-01 | complete 2/5, safe 1/5 | safe 2/5, complete 0/5 |
| QMB-05 | safe 3/5, complete 2/5 | complete 3/5, safe 0/5 |
| QMB-02 consistent | 2/5 | 3/5 |
| QMB-06 grounded | 1/5 | 2/5 |

**No per-case rate from this suite supports a claim.** A six-case suite moves 0.17–0.33 per dimension
between passes, so a single sweep cannot detect a change smaller than roughly one case, and the
case-level attribution is not even stable between sweeps. `consistent` has exactly one case, so its
"spread 1.00" is a binary flip rather than variance — **the CLI's "variance, not signal" label
overstates it, and that wording should be fixed.**

This is precisely what the noise-floor-first rule exists for (`docs/engineering-history` records 5.5
hours spent on an A/B whose effect was under its noise). **No baseline is committed.**

## What IS stable across all three sweeps

Reported as directions, not rates:

- **`safe` fails somewhere in every sweep.** Which case rotates (QMB-01, QMB-02, QMB-05), but a
  proposal that destroys delivered work appears in every 5-pass run. The behaviour measured live on
  2026-08-19 is reproducible in aggregate even though no single case reproduces it reliably.
- **The no-op control fires every sweep** (QMB-03, 1–2 of 5). Asked about a genuinely healthy
  backlog, the PM invents work. Nothing else in the repo measures this false-positive half.
- **Chat and curate disagree** (QMB-02, 1–3 of 5) about what should be destroyed — the same
  contradiction observed live, now reproducible.
- **`honest` never fired.** The live "I do not have visibility into the file system" failure did
  **not** reproduce on any fixture. Either the fixture is easier than the live context, or the
  defect needed the degraded repo overview that has since been fixed. Recorded as not-reproduced
  rather than resolved.

## What was NOT confirmed

- **F60 (issue #70) does not reproduce when the contract is in the item's description.** QMB-06
  fails 1–2 of 5, and the model routinely quotes the required format. The recorded defect was about
  acceptance authored *without reading the code* — this case deliberately puts the fact where the PM
  can see it, so it tests carrying a given fact, not discovering an unseen one. **The harder version
  is not measurable today**, for a structural reason below.

## Substrate gaps (identified by reading the code; not measurable with QMB as built)

- **Quincy never sees acceptance TEXT in chat.** `_backlog_line` (`pm_sections.py:17-33`) renders a
  *criteria count*, and the description is hard-cut at 100 characters. The clarify contract asks him
  to judge exactly the surface he is not shown. This is the most likely mechanical cause of F60, and
  no prompt change can fix it.
- **The claim ledger is not in his context and is not queryable by item.** ADR-0079 records "what
  was promised, what proved it, what happened", but `store/_claims.py` exposes only
  `list_run_claims(run_id)`. So *"does every acceptance criterion now have evidence?"* — which the
  North Star names as Quincy's defining question (`north-star.md:157`) — cannot be answered at all.
- Chat carries **map gaps only**, never the map's observations; the full map reaches synthesis and
  planning but not the conversation.

## Config finding

`get_chat_model("pm", settings)` resolved to **`gpt-oss:20b`** while `Settings.pm_model` is
`qwen3.6:35b`. Not chased here, but every number above is a statement about `gpt-oss:20b`, and any
comparison against the live instance must confirm which model actually served the turn. This is why
the sweep records the model id — Model Substitutability makes a rate without it meaningless.

## What would make QMB able to gate something

1. **More cases per dimension.** `consistent` and `honest` have one each; `grounded` has two. Three
   to five apiece would bring per-dimension noise below one case.
2. **Fix the CLI's spread label** so a single-case dimension is not reported as variance.
3. A second fixture project, so results are not one repository's shape. The duplicate-threshold
   lesson from earlier the same day applies exactly.

## Verdict

Not a trusted SME, and QMB is not yet a trusted instrument — but both statements now have evidence
behind them instead of anecdote. The suite reproduces three of the defects observed live, refutes a
fourth as unmeasurable-as-posed, and its own two failures are the clearest demonstration in this
document of why a number nobody has traced back to raw output should not be believed.
