# ADR-0086: The approval posture ladder — gate on risk and on standstill, not on every write

- Status: **superseded** (was `proposed`; never accepted, never implemented)
- Implementation: not-started — **and never started.** One prose reference exists in the codebase
  (`packages/core/mosaera_core/oraclefit.py`); there is no `risk_gated` posture, knob, or code path
  anywhere in `packages/` or `apps/`.
- Superseded by: [ADR-0101](ADR-0101-run-interaction-modes.md) (accepted 2026-08-13) for the posture
  vocabulary and the write-gate surface. **§2's risky-write list is NOT superseded** — see the
  archive note below.

> **ARCHIVE NOTE — 2026-08-18** (`docs/audits/adr-corpus-review-2026-08-18.md`). **This decision was never implemented and the surface it
> governs was rebuilt by another decision.** ADR-0101 replaced the guided/autonomous vocabulary with
> **`ask` · `accept` · `auto`**, shipped in `apps/api/mosaera_api/runner/_mode.py`. Its middle rung
> is *not* this ADR's middle rung: `accept` auto-approves **every** in-scope write and buys back one
> direction checkpoint after design, where ~~`risk-gated` (the new default)~~ would have kept gating
> the *risky* writes. ADR-0101 states the disagreement directly — *"Per-file write approval is not a
> gate **category**; it is `ask` mode's behavior."* — and does not cite this ADR.
>
> **Superseded:** §1's three-posture ladder and the `risk-gated` default. §3's *substance* — the
> deterministic delivery gate and the ADR-0012 escalation interrupts are never relaxed — survives and
> is re-affirmed by ADR-0101 ("the deterministic delivery gate, which **no mode can skip**").
>
> **NOT superseded, and the reason this file is kept: §2's risky-write list.** It is the only
> written-down, deterministic, model-free inventory of what makes a write worth a human — the oracle
> surface, re-approval churn, an assertion-floor drop, non-constant→constant, manifests and entry
> points, a payload too truncated to show. ADR-0101's `accept` mode has no equivalent, so every item
> on that list is currently ungated in `accept`/`auto`. Anyone building a per-write risk signal on
> ADR-0101's modes should start from §2. Preserved, superseded rather than deleted, per the README's
> rule that a superseding decision references the old one.
- Date accepted:
- Owners: @rengi
- Related issue / MR: operator sessions 2026-08-05/06 (LedgerCLI live runs); supersedes the F20 finding's framing
- Supersedes / Superseded by: — (depends on [ADR-0085](ADR-0085-oracle-defect-detection-strategy.md) §3 for its end state)
- Related threat model: [TM-0001](../threat-models/TM-0001-mosaera-lite-repo-agent.md) (the agent write surface)
- Review trigger: `#64` reports a containment measurement, or a posture is proposed that removes the delivery gate

**Decision summary:** Guided mode gates **every write**, which is neither what the operator wants nor
where the value is. Replace the binary (autonomous | guided) with a **three-rung ladder** —
`autonomous` · **`risk-gated` (the new default)** · `guided` — where the middle rung stops only on
writes carrying real risk, and otherwise lets the team iterate to delivery on its own. The delivery
gate and the escalation interrupts are **rungs of the ladder in every posture** and are never
relaxed. The end state the owner wants (gates only at a standstill) additionally requires the agents
to check each other credibly, which is unproven — so this ADR builds the rung that is defensible
today and names the evidence required for the next one.

## Context

**Measured on run `20260806-154604-229044`** (Slice 1, hand-driven, reached the delivery gate):
**14 write gates, 8 send-backs, ~85 model calls, one budget raise.** Splitting them by what the
approval actually bought:

*Noise — approval with nothing to decide:*
a 0-byte `src/budget_tracker/__init__.py`; an `expenses.append(dict(row))` no-op; a README.

*Real catches — a defect that nothing else in the system would have stopped:*
a `src.budget_tracker` import repeated 5× (one of them past the old 4,000-char truncation);
a `pyproject.toml` with no `[tool.setuptools.packages.find]`, so nothing could import;
a `budget` script discarding `main()`'s exit status, so failures reported success;
`sys.path.insert(0, '.')` re-added after being corrected;
a silent `ROUND_HALF_UP` → banker's-rounding regression hidden inside docstring churn;
a header-duplication bug that would have failed a protected test;
a third duplicate storage suite.
The day before, at the same kind of gate: the coder replacing `date.today()` with `date(2023, 1, 1)`
to force a broken test green (**F43**).

So roughly half the gates were pure friction and half were load-bearing. That is the F20 finding
stated precisely: **identical approval weight for a 0-byte file and a product-corrupting diff is what
trains click-through**, and click-through is what makes the load-bearing half fail.

**The design tension.** The write gate currently does two jobs at once: it is a *permission control*
and it is the operator's only *window* into the run. Removing per-write gates does not merely remove
friction — it removes the surface that caught everything in the second list. The work does not
vanish; it moves to one large diff at the delivery gate, and F27 established that a wall of text is
exactly where a regression hides.

**Why the owner's end state is not yet buildable.** "Gate only at a standstill, let the agents check
each other" requires peer review to actually catch these defects. That is the claim
[ADR-0070](ADR-0070-independent-spec-review.md) built, measured (**0 park→ship conversions in 15
runs**), and reverted; ADR-0085 §3 permits re-opening it only on a containment measurement, tracked
as `#64`. The end state is therefore *gated on evidence*, not on plumbing.

## Decision

### 1. Three postures, not two

| posture | write gates | escalation | delivery gate |
| --- | --- | --- | --- |
| `autonomous` | none | auto-resolved (recorded) | **always** |
| **`risk-gated`** (new default) | **only risky writes** | **human** | **always** |
| `guided` | every write | human | **always** |

`guided` is retained deliberately — it is the debugging posture, and it is how every finding in this
log was found. It stops being the default.

### 2. What counts as risky (deny-by-default, deterministic)

A write stops for a human when **any** holds. All are structural facts, computable at the tool layer
with no model call — the same standard ADR-0085 §1 sets for the deterministic layer:

- the path is in `protected_tests` / `authored_tests`, or is a baselined test (the oracle surface);
- the file was **already approved this run** and is being changed again (the F27 revert/churn class);
- the proposed content **drops below the assertion floor** for a test file (the F42 gutting class);
- a diff replaces a **non-constant with a constant** (the F43 signature — `date.today()` → `date(2023,1,1)`);
- the write is to a manifest or entry point (`pyproject.toml`, `setup.py`, CI config, the console script);
- the payload had to be **truncated** for display (F40 — never auto-approve what cannot be shown).

Everything else — a new source file, a 0-byte `__init__.py`, a README, a first draft of a test —
proceeds and is *recorded as activity*, not as a question.

**Visibility is not the same as permission.** Every ungated write still appears in the run's activity
stream and in the delivery diff. The operator loses the interruption, not the information.

### 3. The delivery gate and escalations are not rungs to remove

Unchanged in all three postures, and out of scope for any future relaxation under this ADR:
the deterministic delivery gate (*Deterministic Final Authority*), the ADR-0012 escalation interrupts
(the "standstill" case the owner explicitly wants to keep), and the rule that a model may propose but
never clear.

### 4. The next rung is earned, not assumed

Moving `risk-gated` toward "no write gates at all, agents check each other" requires `#64` to show
that independent oracle review reduces the F43 product-corruption rate against a human-driven
baseline. Until then, the risky-write list above is the control, and it shrinks only against evidence.

## Options considered

**Keep guided as the default (status quo).** Rejected: measured ~50% pure friction, and the failure
mode of friction is click-through on precisely the approvals that matter.

**Drop write gates entirely now and rely on the delivery gate.** Rejected as premature. Every defect
in the "real catches" list would have reached one large diff at the end, where F27 says regressions
survive review. Revisit when `#64` reports.

**Make the risk rules model-judged rather than structural.** Rejected: it puts a model on the
permission path, and ADR-0085 §1 freezes semantic judgment out of the deterministic layer. Every rule
above is a structural fact about the diff.

## Security implications

Narrows *when* a human is asked, never *what the deterministic controls enforce*. The tool-layer
guards (protected paths, write scope, `.git` refusal, churn) are unchanged and still refuse
regardless of posture; the risky-write list is strictly additional. The delivery gate is untouched.

Residual risk, stated plainly: in `risk-gated`, a defect in a **non-risky** file is not seen until the
delivery diff. Today's run had two such (the `budget` exit-status bug and `sys.path`), both caught
early only because every write was gated. They would still have been catchable at delivery — later,
in a bigger diff. That is the trade this ADR accepts, and `#64` is what would retire it.

## Consequences

**Good.** Today's 14 gates become roughly 6, and the ones that remain are the ones that were doing
work. Approval stops being a reflex. The posture the owner wants becomes a named rung with a stated
entry condition rather than an aspiration.

**Bad / accepted.** More defects surface late rather than early, and the delivery diff has to be read
properly. `guided` must stay maintained as the debugging posture, which is a second path to keep
working.

**Reversible?** Fully. The ladder is configuration; a project can be set back to `guided` per run, and
the risky-write list is data, not architecture.
