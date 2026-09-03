# Code evidence for the stages that author the bar (2026-08-20)

**Question:** the PM writes acceptance criteria it cannot check against the code (F60, issue #70).
Does giving `curate` and `decompose` the CONTENTS of the files an item names change what they
write?

The access map made the defect structural rather than behavioural:

| stage | repo access before this change |
|---|---|
| **curate** — enhances and adds items | **nothing at all** |
| **decompose** — creates the backlog | file listing + README |
| plan | listing + read-only tools |
| design | listing + up to 4 named files verbatim + tools |

The stages that AUTHOR the bar could not read the code; the stages that implement it could.

## What was built

`ground_named_files` (`packages/core/mosaera_core/grounding_text.py`) reuses design-grounding's
`plan_named_files` selection and deliberately does NOT reuse its rendering.

- **Selection reused.** It is deterministic and self-limiting: an item naming no file selects
  nothing, which is what makes this affordable on every curate.
- **Rendering hardened.** `build_grounding` wraps contents in a triple-backtick fence, and `mapview.py:8-11`
  already recorded why that is not enough — a fence has a delimiter untrusted text can close. Every
  line is prefixed `| ` instead. The per-line treatment is NOT `quote_repo_text`: it flattens with
  `" ".join(raw.split())`, which is right for a file listing and destroys Python. Caught by
  rendering a real function and reading the output, not by review.
- **Reader injected.** QMB has no clone; a `Workspace`-bound helper could not have been measured.
- **A total cap**, which `build_grounding` does not have.

## The instrument had to be extended first

QMB fixtures carried a file LISTING and no source, so the suite was structurally unable to detect
this change — the same trap the evidence slice hit before fixtures gained `verdicts`. Measuring
first and reporting "no effect" would have repeated it. Fixtures gained `contents`, and QMB-12 was
added as the counterpart to QMB-06: QMB-06 states its contract in the item description on purpose
(so a wrong answer means the PM ignored what it was handed); QMB-12 puts the contract ONLY in the
code, and a test asserts every `must_contain` string is absent from everything the PM is told.

## What the raw output shows (3 probe passes each, gpt-oss:20b)

Ungrounded, asked to sharpen "add a `--json` flag to the status command", it invented
`total_spent`, `remaining_cap`, `category_breakdown`, an `--human` flag, a `-q` flag, and "the
order defined in the configuration file". None of these exist.

Grounded, it wrote `cmd_status`, `store.caps()`, `store.entries()`, two-decimal formatting, sorted
by category, and the literal `OVER`/`ok` marker — every pass, with `remaining` gone entirely.

This is F60 reproduced and then removed on the same fixture, and it is why the case asserts `OVER`
rather than `spent`: `spent` alone is guessable and scored 3/5 with no code at all.

## A limitation the measurement exposed

The first QMB-12 draft described the behaviour without naming a file, and grounding produced **0
characters** — selection is filename-driven, so an item that names no file gets no code. The
recorded F60 item may well have been of exactly that shape. The fixture was made realistic (items
normally say where the code lives) rather than the selector made fuzzy: a heuristic that guesses
which file an item "means" would be a second origin for the same answer, and Deterministic-First
prefers a control that fires precisely to one that fires often. **What this change does not fix:
an item that names no file is still ungrounded.**

## The A/B

Same method as [the evidence-context A/B](pm-evidence-context-ab-2026-08-20.md): one model
(`gpt-oss:20b`), paired on `(case, dimension, pass)`, McNemar exact. The BEFORE arm removes
QMB-12's `[contents]` table, which makes `code_evidence` empty for every case and so reproduces the
pre-change prompt byte-for-byte. **Confirmed inert before running:** 0 grounding characters across
all 12 cases.

**Pre-registered before the run:** *grounded* and *honest* move to AFTER; *safe*, *consistent* and
*complete* are controls. *"If complete moves, the added block is displacing attention rather than
informing it, and that is a cost to report, not to explain away."*

### Whole suite, 5 passes — 177 paired trials

Pooled: 14 AFTER / 14 BEFORE, p=1.000. **That number is meaningless here and is recorded so nobody
recomputes it hopefully.** Only QMB-12's prompt differs between the arms; the other eleven cases
are byte-identical, so their 22 discordant trials are a null control running alongside — and it is
large. Restricted to the case that actually changed: grounded 3-0, honest 4-0, both one-sided, both
underpowered (exact p 0.25 and 0.125).

### QMB-12, 20 passes — 80 paired trials

| dimension | AFTER | BEFORE | p | rate AFTER → BEFORE | |
|---|---|---|---|---|---|
| **grounded** | **10** | 0 | **0.002** | 10/20 → 0/20 | predicted mover |
| **honest** | **16** | 0 | **<0.001** | 20/20 → 4/20 | predicted mover |
| safe | 0 | 0 | 1.000 | 20/20 → 20/20 | control — did not move |
| complete | 3 | 9 | 0.146 | 10/20 → 16/20 | control — MOVED, see below |

Grounded goes from **never** to half the passes, and honest from 4/20 to 20/20. Both predicted
movers moved, one-sided, with nothing to BEFORE.

### The control that moved

`complete` leaned 3-9 toward BEFORE. Not significant, and not dismissed on that basis — the
mechanism was chased down instead. On this case `complete` can only fail one way: an empty
changeset, i.e. model output `_extract_json_array` could not read. A follow-up probe with the
arm's exact prompt (capabilities included — a first probe omitted them and was discarded rather
than reported) measured empty changesets at **2/12 with evidence and 4/12 without**, the opposite
direction. Every non-empty proposal carried the expected `enhance` op in both arms.

So the lean is most consistent with parse-empty noise, which runs at roughly 15–35% either way on
this case and swamps a 12-trial probe. It is **not ruled out**: a real displacement cost would need
a larger n to separate from that noise. Recorded as open rather than explained away.

## Verdict

F60's PM half is addressed for `curate` and `decompose`, measured rather than asserted. The
remaining halves: an item that names no file is still ungrounded (above), `build_grounding`'s
escapable fence on the DESIGN path is untouched and recorded separately, and F53 — the Proctor
weakening its own bar — is the other half of #70.

## Live validation, 2026-08-20 — and what it could not establish

Deployed to `app.mosaera.dev` and exercised on the LedgerCLI project. **Grounding was not
demonstrated live**, and the attempt turned up two things worth more than the demonstration.

**1. The backlog could not discriminate.** Curate produced one well-formed proposal (28s, one
`enhance`) whose criteria named `OK` / `OVERSPENT` / `NO CAP`, two-decimal formatting and the
capped-category shape. Every one of those strings is ALREADY in the item text the PM is handed —
checked by membership, not by eye. So the proposal is consistent with grounding and evidence of
nothing, the same trap QMB-06 is built around. Worse, it asserted "categories without caps are
omitted", which the real `cli.py` contradicts: `all_cats = sorted(set(totals) | set(caps))` lists
them with `cap_str = "NO CAP"`. Where the backlog text disagrees with the code, the text still won.

**2. The control fails open SILENTLY, so "inert" and "nothing to ground" are indistinguishable.**
Nine of twelve live curate calls returned an empty changeset. The local control explains why that
matters: on a live-sized backlog, curate WITH the block returned 0/5 empty (8-12 ops a pass, on
both `gpt-oss:20b` and `qwen3.6:35b`), and WITHOUT it returned **5/5 empty** with the model
literally emitting `[]`. Empty is what ungrounded curate does — so the live pattern is consistent
with the block never reaching the prompt at all.

It could not be resolved from outside the instance, because `ground_project_files` returned `""`
for a wrong `projects_dir`, a missing clone, a permissions error and "the item named no file"
alike. That is the invisible-control shape this repo has already paid for, introduced here by the
author of the guard against it. Fixed by making both outcomes speak: a `code-evidence: N chars`
line on success and `code-evidence: UNAVAILABLE (<error>)` on failure. The fallback stays — curate
also runs unattended from spec-lint and escalation, and losing grounding must not lose the
curation — but the silence does not.

### Resolved the same day — the change is LIVE

Redeployed with the diagnostic; twelve curate calls, twelve log lines:

    code-evidence: 7054 chars for proj-ledgercli-511c67

**The hypothesis was wrong.** The block reaches the live prompt on every call; the empty
changesets were model variance, not an inert control. The diagnostic earned its place by
DISPROVING the theory that motivated it, which is the only reason to prefer an observable over an
argument. Curate returning ops went from 3-of-12 before the redeploy to 5-of-8 after, consistent
with variance rather than with a step change.

7054 > the 6000 total cap because the cap bounds SOURCE characters, not the rendered block: 5907
chars of content renders to 6844 with the `| ` prefixes, `### path` headers and the instruction
line (~940 overhead, measured). The identical 7054 on every call also says the cap is BINDING on
this project — four files selected, content truncated at 6000 — so a named file's later content is
being cut. Known limit, not a defect, but it bounds how much any one item can be grounded by.

**Still owed:** a live case that DEMONSTRATES grounding rather than confirming its presence.
LedgerCLI cannot: its backlog already states the contract, so the proposals quote `NO CAP` and
`OVERSPENT` and no code-only token (`all_cats`, `quantize`, `Decimal`) ever appeared. That needs a
project whose contract exists only in the repository — which is exactly what QMB-12 does offline.
