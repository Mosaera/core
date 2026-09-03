# The over-strict bar is visible BEFORE it lands (2026-09-02)

Tracked as #130, slice 5 of the
#129 over-park arc.

First live run on `0.6.3`, `app.mosaera.dev`, project LedgerCLI (brownfield, real standing suite),
`autonomous: true`, guided approval mode. Run `20260902-125337-1443d3`, cancelled at the first
write gate. Cost to learn this: **19 model calls, 143k tokens, and no code written**.

## What happened

The brief:

> Add a `--count` flag to the `list` command. When passed, list should also report how many entries
> it printed. Do not change the existing list output when the flag is absent, and keep every
> current test passing.

It does not say what the report should look like. That is not a defect in the brief — it is what a
real brief looks like.

The run paused at a guided write gate with the Proctor proposing `tests/test_cli_list_count.py`:
**10,347 characters, 13 test functions, 55 assertions**, for one boolean flag. Among them:

```python
assertTrue(last_line.startswith("count: "))
assertIn("count: 3", last_line)
assertTrue(r.stdout.startswith("amount,category,note,date\n"))
```

`count: ` appears nowhere in the task. An implementation printing `3 entries`, `Total: 3` or
`Found 3` satisfies the brief and fails this bar. This is the measured over-park driver — 47.3% of
over-parks are the authored bar refusing code the hidden grader passed — reproduced on the first
live run, on real work.

## The finding: the information is available two stages earlier than we act on it

Everything this arc built acts at the **delivery gate**, after the coder has run:

- the two-bars ask (`oracle_dispute.py`) fires when an authored assertion refuses a tree the
  standing suite vouches for — **8 of 150 sweep runs**, and only after the work is done;
- `case_impossible` and the faithfulness detector feed a repair pass that measured null.

**But the bar was fully readable at authoring time.** It sat in a human-facing interrupt payload,
before the coder wrote a line, before validation, before the gate. At that moment the whole waste is
still avoidable: no implementation, no fix loop, no iteration budget.

A guided-mode operator is already shown this payload — and is shown **nothing** about whether the
bar is meetable. They are asked to approve 10kB of assertions on the merits of a summary line.

## Why this is cheaper than everything the arc shipped

| | acts at | cost when it fires |
|---|---|---|
| two-bars ask | delivery gate | the full run is already spent |
| repair pass | after authoring | measured null (p = 0.51) |
| **authoring-time check** | **write gate** | **19 calls, nothing implemented** |

**And the obvious cheap version does not work.** "The detectors already run on this file, just show
their output at the write gate" was the first shape of this idea. Measured, on this exact payload,
with the real entry point:

```
assertions in the bar: 55
DETECTOR FINDINGS: 0
```

Zero. `check_exception_message_pin` needs the haystack to be exception text; `check_type_name_string`
needs `str(type(...))`; `case_impossible` needs a case fold. None of them describes "a literal the
task never used, required as a prefix of stdout". Surfacing what exists would have surfaced nothing,
and the 4.2% figure from the sweep should have made that the expected answer rather than a surprise.

So this is TWO findings, and conflating them would waste the cheaper one:

1. **Timing** — the bar is readable two stages before anything acts on it. True regardless of what
   any detector can see, and cheap.
2. **Detection** — nothing currently recognises this shape. That is a new check, and it needs the
   measurement discipline that produced the 4.2% correction, not confidence.

## Not a proposal to auto-reject

ADR-0062's boundary holds: the engine may not mechanically widen or rewrite the acceptance class,
and a detector that refuses a bar is a detector deciding what "correct" means. The honest shape is
the one the two-bars ask already uses — **speak, never act**. Annotate the write gate with what the
deterministic checks found and let the operator decide, exactly as they already decide the write.

The autonomous case is harder and is deliberately left open: there is no human at the write gate,
and *Unsuppressible Ask* says a control may refuse to act but never to speak — which is an argument
for recording the findings on the run even when nobody is there to read them yet.

The proposed bar is preserved verbatim beside this note as
[`artifacts-authored-bar-2026-09-02.txt`](artifacts-authored-bar-2026-09-02.txt), so any future
check can be measured against the real thing rather than a paraphrase of it.

## What is NOT established

- **One run.** A 55-assertion bar for a boolean flag is striking, not a rate.
- **What check would catch it.** The shape is "a string literal absent from the trusted task,
  required as a substring or prefix of program OUTPUT" — the same shape as MCB-01's
  `captured.out == expected_output`. It is a general faithfulness rule, not a case-specific detector,
  so ADR-0085 permits it. But a naive version over-fires: a task saying "sum the amounts" legitimately
  produces a test asserting `"6"`, and `6` is not in the spec either. The existing checks are narrow
  precisely because that boundary is hard, and the new one must be measured against the labelled
  corpus BEFORE it ships.
- Whether an operator shown the annotation would act on it differently.
