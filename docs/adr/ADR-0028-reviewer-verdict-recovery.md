# ADR-0028: Recover a dropped reviewer verdict instead of false-parking correct work

- Status: accepted
- Date: 2026-07-13
- Owners: Alejandro Rengifo
- Related: [ADR-0027](ADR-0027-benchmark-diversity-trustworthy-python.md) (the trustworthy-Python arc that measured this), [ADR-0006](ADR-0006-durable-transcript-and-honest-outcomes.md) (honest `incomplete`/park outcomes this makes fewer of), [ADR-0012](ADR-0012-cohesive-team-supervision.md) (the park path a false-UNKNOWN wrongly triggers)
- Corrected by: [ADR-0034](ADR-0034-only-executed-evidence-may-ship.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.

## Context

The MCB-21 baseline (the ADR-0027 arc's first case) exposed a third trust gap, distinct from coder capability and
the correctness oracle: **the reviewer's verdict reliability.** Across the three baseline runs the delivered code
was correct every time (Implementation 100 + Validation 100), yet **one run in three false-parked** — Review 67 /
Autonomy 77 / Governance 83 — because the local reviewer (`gpt-oss:20b`, a reasoning model) concluded its review
*without* a parseable `VERDICT:` line. Same signature as MCB-11 in the Phase-2 measurement.

`parse_reviewer_verdict` is deliberately strict — it anchors on the literal `VERDICT:` token and never guesses
APPROVE, so an unparseable review is `UNKNOWN`, which routes to the human park (correctly, *if* the review were
truly unusable). But a reasoning model that reviews well and simply drops or reformats the verdict line is not an
unusable review — it's a formatting flake, and parking correct, passing work on it is a false negative that
directly undercuts "Python you don't have to babysit." A ~1/3 rate makes it the highest-frequency trust gap of
the three.

## Decision

Add a bounded **verdict-recovery** step, `reviewer.clarify_verdict(model, review, config)`: when — and only when
— a **non-empty** review parses to `UNKNOWN`, make **one direct model call** (the raw `reviewer_model`, not the
tool agent — cheap, no re-review) that hands the model its own review back and asks it to commit to exactly one
verdict line. The reply is read with a lenient keyword scan (safe because the reply is a single constrained line,
unlike free review prose), and a canonical `VERDICT: <X>` line is appended to the review so every downstream
strict parse (`route_after_review`, the gate) sees it. Wired in `graph.review_node` right after `review_change`.

Deliberate boundaries that keep it honest:
- **Only fires on `UNKNOWN`** — never overrides a review that already parsed.
- **Never guesses APPROVE** — a blank/ambiguous/conflicting reply, or any model error, returns `""` → the verdict
  stays `UNKNOWN` → the run still parks (fail-closed to today's behaviour).
- **Recovers judgment, doesn't manufacture it** — the model decides from its own review; a critical review yields
  REQUEST CHANGES / BLOCK, not APPROVE.
- **Does not widen what can ship** — `tests_passed` (validation + the tester oracle) is an independent gate, so a
  recovered APPROVE still cannot deliver failing code. `parse_reviewer_verdict` and `packages/policies` are
  untouched.

## Consequences

- The ~1/3 false-park of correct work becomes a recovered verdict — fewer honest-but-wrong parks, higher
  effective autonomy, without loosening the ship criteria.
- One extra model call, but only on the flake path (`UNKNOWN` ~1 run in 3), and a single cheap direct call rather
  than a full re-review.
- The strict authoritative parser is unchanged; recovery is additive and localized to `reviewer.py` +
  `review_node`.
- Honest residual: recovery depends on the same model that dropped the line; a model that both reviews poorly
  *and* can't commit to a verdict still parks (correctly). This addresses verdict *formatting* flakiness, not
  reviewer *judgment* quality — a stronger/structured-output reviewer remains a separate future option.

## Alternatives considered
- **Loosen `parse_reviewer_verdict` to keyword-scan the whole review.** Rejected — verdict words appear in review
  *prose* ("you should not BLOCK a change like this"), so scanning free text would misread verdicts. The strict
  anchor must stay; the re-ask reply is the only text safe to scan leniently.
- **Default `UNKNOWN` to APPROVE (or to REQUEST_CHANGES).** Rejected — defaulting to APPROVE ships unreviewed
  work; defaulting to REQUEST_CHANGES just trades a false park for a false fix loop. Recovering the model's actual
  verdict is the only option that doesn't fabricate a decision.
- **Structured-output / tool-call verdict.** A stronger fix, but a larger change to the reviewer contract and
  local-model tool-call reliability; deferred. `clarify_verdict` is the cheap, safe first cut.

## Update (2026-07-13): corrected mechanism — the verdict was in the reasoning channel

The first cut above (a `clarify_verdict` re-ask) shipped, and the arc's discipline is to *re-measure*. An 8-run
MCB-21 re-measure with the fix came back **worse, not better** (Review 67→28, Autonomy 77→48) — and, crucially,
revealed the 3-run baseline had been small-sample luck: the true false-park rate on this correct, delivered case
is **~75%**, with Implementation 100 every run. So the diagnosis above was incomplete and the re-ask was solving
the wrong problem.

Digging into the actual reviewer output (a diagnostic invoking the real reviewer, and a faithful repro with its
read tools on a real parked workspace) found the real mechanism: **`gpt-oss:20b` routes its whole review — the
`VERDICT:` line included — into the reasoning channel (`additional_kwargs.reasoning_content`) and leaves
`content` empty.** `message_text` reads only `content`, so `review_change` returned `""` → `UNKNOWN` → park — and
`clarify_verdict` re-read only `content` on its re-ask too, which is exactly why the band-aid didn't move the
needle. This is a direct consequence of `models.py` setting `reasoning: True` for gpt-oss to keep CoT out of
`content` (ADR-0002 seam) — the review is *there*, just not where we were reading.

**Corrected fix (deterministic, no extra model reliance):** `review_change` and `clarify_verdict` now read
**both channels** via `reasoning_of` (reasoning + narration), preferring the last message that carries a parseable
verdict. The verdict the reviewer already produced is simply read from the right channel. Faithful repro on the
real parked workspace: **4/4 runs recovered a verdict** (3 directly, 1 via the re-ask) versus **0/4** before. The
strict `parse_reviewer_verdict` and `packages/policies` remain untouched; this is a pure extraction fix. The
deterministic oracle-approve backstop (approve when the executed oracle passes but the reviewer truly emits
nothing) is held in reserve — the channel fix appears to remove the need, pending the full re-measure.
