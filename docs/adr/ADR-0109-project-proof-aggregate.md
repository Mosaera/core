# ADR-0109 — A summary of receipts must be reconcilable against them

- **Status:** Accepted (owner-requested, 2026-08-23)
- **Related:** ADR-0063 (capability through auditability), ADR-0006 (honest parking),
  ADR-0079 (acceptance claims), [ADR-0105](ADR-0105-chat-as-a-control-surface.md) (derived, never
  stored)

## Context

The project Overview answers *"how well proven is the work that shipped?"* for a whole project.
Three of its axes — independence, checks, integrity — are answerable from fields already on the run
list. The other three exist only inside each run's **sealed receipt**: whether an independent
reviewer approved it, whether the security scan ran on the delivered tree, and whether the suite was
deep enough to catch a planted fault.

A page cannot fetch thirteen receipts to draw one panel, so the aggregate is computed server-side.
That introduces a genuinely new artifact: **a summary of sealed records**. Its failure mode is quiet
and severe — a number that looks authoritative while disagreeing with the receipts it claims to
summarize. The console already had one instance of this class: the web-side draft counted the
*absence* of a gate objection as evidence, which would have painted a perfect score over work
nothing verified. The receipts were right; the summary was not.

ADR-0063 requires that safety come from containment, traceability, and **verification at the door**.
A summary nobody can reconcile against its sources is the opposite: it launders unverified state
into a confident figure.

## Decision

`GET /projects/{id}/proof` returns the aggregate, and **five rules** govern it. They are enforced in
`apps/api/mosaera_api/proof.py` and pinned in `apps/api/tests/test_project_proof.py`; three are
additionally mutation-verified (reverting each rule fails the suite).

1. **One origin.** Every number derives from the receipt rows themselves — the same rows the run
   page renders and the web's `parseReceipt` reads — never a parallel table, a cached rollup, or a
   second derivation of the same facts. `project_receipts()` returns receipts **verbatim**; parsing
   and judgement live in exactly one place, because two interpreters is how a summary starts
   disagreeing with its own sources.
2. **No synthesis.** An axis reports only a verdict the receipt **literally carries**. A missing
   field is `unknown` — never inferred from a sibling field, from the run's status, or from the
   absence of an objection.
3. **Unreadable is unknown, never proven.** A receipt that is missing, truncated, or unparseable
   counts as `unknown` on every axis, and the delivery **stays in the population**. Dropping it
   would shrink the denominator and read as 100% proven over work whose evidence nobody could find.
   Every error path — including a store that raises — fails toward "we do not know".
4. **The source set is disclosed.** The response carries `sources.receipts_read` and
   `sources.receipts_unreadable`. Any reader can reconcile the summary against the receipts by
   hand, and every delivery appears in exactly one of the two lists.
5. **The denominator is what was measured.** Each axis reports `proven` / `failed` / `unknown` with
   `measured = proven + failed`. An instrument that was not yet wired when a run happened must not
   read as that run failing: `oracle_vouched_by` was empty on every run before 2026-08-13, and
   counting those blanks as failures would blame the engine for its own missing wiring.

**Derived, never stored.** Recomputed per request, like ADR-0105's decisions. There is no
materialized rollup that could drift from the receipts, and therefore no migration and no second
source of truth.

**One delivery per unit.** An item is represented by its newest APPROVED run; an ad-hoc APPROVED run
is its own unit. An item that parked eight times before shipping counts once, as the delivery it
became — remediated failures cannot colour the panel (owner decision, 2026-08-22).

## Consequences

- The Overview can state six axes with visible denominators instead of three, and the three new ones
  are the ones a stakeholder actually asks about: *was it reviewed, was it scanned, was the suite
  real?*
- The endpoint reads every delivering run's receipt on each call. It is a plain indexed read with no
  network hop — unlike `/decisions`, which makes a GitLab REST call — so it is safe to poll at the
  page's existing cadence.
- **`unknown` will dominate on existing projects, and that is the correct output.** Receipts written
  before a field existed cannot answer for it. The panel says "not recorded" rather than guessing,
  which is the same discipline `honest_park` applies to runs.
- A future materialized rollup (if the read ever becomes hot) would reopen rule 1 and needs its own
  decision — the reconciliation guarantee is what makes this artifact safe, not the endpoint shape.

## Alternatives rejected

- **Fetch receipts client-side.** Thirteen requests per page load, and it puts the interpretation of
  a receipt in two codebases — the exact condition rule 1 exists to prevent.
- **Store a rollup at delivery time.** Fast, and it drifts: a receipt corrected or re-sealed later
  leaves the rollup stating the old verdict with no way to notice. Rejected on rule 1.
- **Infer the missing axes from run-list fields.** The console already tried this and it produced
  absence-as-proof. Rejected on rule 2.

## Amendment — the record is the run row AND its receipt; security is a recorded exception (2026-08-23)

Live validation on the first deploy showed the aggregate reporting **"not recorded"** for integrity
and security on all thirteen deliveries of a project whose runs plainly record both. The rules held
— rule 2 refused to guess and rule 3 kept the deliveries in the population — but the axes were
asking the wrong row. Two corrections, both of which sharpen rule 1 rather than loosen it.

**1. A delivery's record is the run row plus its receipt.** `persist.receipt_json` carries the
GATE's verdict — action, reasons, reviewer verdict, tests_passed, validation strength, vouch,
mutation. Tampering (`tests_modified`), the seal (`receipt_id`) and scanner availability
(`security_unavailable_cause`) are recorded on the **run**. These are not two origins: they are one
run's durable record, written by one delivery, and the run page reads exactly the same two. What
rule 1 forbids is a second *interpretation*, and the reader now mirrors `lib/radar.ts`'s per-run
axes deliberately so the project summary and the run page cannot disagree.

The lesson generalizes: the first cut's tests passed because their fixture invented receipt fields
that `receipt_json` never writes. A fixture modelling a schema that does not exist is a test that
cannot fail on the defect it was written for — the same class this repo has now hit four times.

**2. Security is the one place absence counts, and it is recorded rather than assumed.** ADR-0107
split `security_not_attempted` from `security_unverified`, and ADR-0108 added `security_stale`,
precisely so that the security reason set became **total** over security states: a gate that
examined security and had nothing to say emits no token, and a gate that could not examine it now
says so explicitly. Under a total reason set, absence *is* the recorded verdict, and rule 2 is
satisfied in substance.

The alternative was worse than the exception. Holding the letter of rule 2 would have the run page
call a delivery *"security scan clean for this code"* while the project summary called the same
delivery *"not recorded"* — a summary disagreeing with its own sources, which is the artifact this
ADR exists to prevent.

**Residual, recorded not closed.** Receipts written before ADR-0107/0108 cannot emit those tokens,
so a pre-ADR delivery that was merely *silent* about security reads as clean. The reason set is
total only going forward. Closing it needs a positive scan record in the receipt itself — a receipt
schema change, and therefore its own decision. Until then this is the one axis whose green can come
from an old silence, and it is the first place to look if a security number ever seems too good.
