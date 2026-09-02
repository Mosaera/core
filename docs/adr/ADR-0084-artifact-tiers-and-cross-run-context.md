# ADR-0084: Artifact tiers — what persists across runs, who owns it, and how it goes stale

- Status: proposed
- Implementation: partial — §3 shipped (`graph/_design_cache.py`, migration 0023, keyed on task+plan+corrections); follow-ups (a) charter reachability and (c) plan↔design consistency (§5) are open
- Date accepted:
- Owners: @rengi
- Related issue / MR: `#53` (operator session that surfaced it), successor to the `#26` shared run context
- Supersedes / Superseded by: —
- Related threat model: [TM-0001](../threat-models/TM-0001-mosaera-lite-repo-agent.md) (untrusted repo content reaching a prompt)
- Review trigger: a third artifact wants to persist across runs, or a cross-run digest is proposed as gate input

**Decision summary:** Every artifact a run touches belongs to exactly one of two tiers — the
**project tier** (operator-authored, durable, binding on every run) or the **run tier**
(agent-generated, per-run, advisory). A run-tier artifact may be *cached* across runs but never
becomes authority, and every cache carries an invalidation key derived from its real inputs. The
charter is project tier and must reach every stage that can act on it, including the coder. Cross-run
learning is admitted on the same terms that already govern the project map: derived from recorded
evidence, attributable to the run that produced it, visible to the operator, and **never reaching the
gate**.

## Context

Two failures observed while driving a greenfield project end-to-end through the UI on 2026-08-05
([friction log](../engineering-history/ledgercli-friction-log-2026-08-05.md)) turned out to be the
same defect seen from opposite ends. Both are tier confusions.

**The charter does not reach the coder.** `grep charter` across `graph/`, `prompts.py` and
`run_context.py` returns nothing. The charter is read in exactly two places — the decompose
synthesis and the PM chat — so its constraints survive only insofar as a *particular item's
acceptance text* happens to restate them. `design_node` hands the coder `Task + Plan + Design` and
nothing else. This explains an asymmetry that looked like model stubbornness at the time: a semantic
constraint ("use `decimal.Decimal`") propagated reliably because it landed in the item's acceptance
and rode `build_run_task` into the task string, the Proctor's tests, and the gate's claim oracle;
a structural constraint ("exactly one package, at `src/<pkg>/`") had no per-item acceptance to
attach to, so it reached plan and design as soft prose and reached the coder not at all. Encoding it
as an explicit charter constraint mid-session did not help, and could not have.

**A run-tier artifact outlived its run and became authority.** `design_node` persists the design onto
the backlog item and reuses it verbatim on a later run whenever `feedback` is empty. The motive is
sound and deterministic-first — a stored design means one fewer model call. The defect is the
**invalidation key**: "no feedback" is the only test, so a design is served from cache after the
charter changed, after the item's acceptance changed, and after the plan changed. In the observed
session the operator amended the charter between runs and the second run was handed a design that
predated the amendment. It is a cache with no key.

Stated together, the two tiers are currently **inverted**: the artifact the operator owns and that
should bind everywhere reaches the least far, while an artifact an agent invented in one run
persists and governs later ones.

Separately, the project wants runs to stop being siloed — an agent should learn what earlier items
delivered cleanly, what parked, and what thrashed — and should not re-derive the whole repository
every run. Both are capability requests, and this project's position on capability is already
settled: [ADR-0063](ADR-0063-capability-through-auditability.md) holds that safety is containment
plus traceability plus verification, **not** process-restriction. The question is therefore not
whether agents may carry context forward, but on what terms, and the tier rule is the prerequisite
for answering it — the persisted design is precisely what unprincipled cross-run reuse looks like.

## Decision

### 1. Two tiers, and every artifact declares one

| | Project tier | Run tier |
|---|---|---|
| Examples | charter (goal, constraints, prohibitions, posture), brief, standing decisions (clauses), project doctrine, the recon map | plan, design, foresight, the diff, the transcript |
| Author | the operator (directly, or via a proposal the operator ratified) | an agent, during a run |
| Lifetime | durable; changes only by a deliberate human edit | the run that produced it |
| Authority | **binding** — a run may not contradict it | **advisory** — evidence and grounding, never a rule |
| May a run write it? | **No** | Yes, it is the run's own output |

**A run never edits the project tier.** This is upheld today and must stay that way: nothing in the
run path writes the charter or the brief, and the ratification path for a standing decision goes
through the operator. Solving a propagation gap by letting a run write a per-run or per-item
constraint override is explicitly rejected — it would dissolve the distinction the tier rule exists
to protect.

### 2. A project-tier artifact must reach every stage that can act on it

The charter's constraints and prohibitions become part of the coder's instruction, not only the
planner's overview. Reaching plan and design but not the coder is the failure mode above; a
constraint that the executing agent never sees is decoration.

Preferred mechanism: extend the existing carrier rather than inventing one. `task_spec.build_run_task`
is already documented as the single definition of the task a run is given, and standing decisions
already ride it into the acceptance criteria — that channel is the one with a **measured** effect
(0/6 → 5/6 grader-clean came from the number reaching the coder). Structural constraints have no
clause representation today, which is the gap to close.

### 3. A run-tier artifact may be cached, never promoted

Caching a design across runs stays permitted — deterministic-first is a real constraint and a model
call is not free. The rule is that the cache carries an **invalidation key over its actual inputs**:
at minimum the charter version, the item's acceptance text, and the plan. Any change invalidates.

This is not a new mechanism. The recon map already does exactly this, per dimension, with a
fingerprint and a deny-by-default posture (`NULL fingerprint = unknown freshness ⇒ stale`). The
design cache should be keyed the same way. "No feedback" is not a key; it is the absence of one.

### 4. Cross-run context is admitted on the map's terms

An agent may receive a digest of what earlier runs did **and how they ended**, subject to four
conditions — the same shape that already governs the untrusted map:

1. **Derived from recorded evidence, not from a model's recollection.** The source is what runs
   already persisted. `run_diagnosis` ([#75](../roadmap.md)) now records outcome bucket, park cause,
   gate reasons and vouch diagnosis for live runs, in the same vocabulary the bench uses — that is
   the failure-side source, and it exists.
2. **Attributable.** Every claim in the digest names the run it came from, so an operator can ask
   "why did it think that?" and get an answer that is not a summary of a summary.
3. **Bounded and deterministic.** Pure read-back and string assembly, computed once at run start,
   hard-capped. `run_context.build_run_context` is already exactly this and is the extension point.
4. **It never reaches the gate.** The digest informs authoring, planning and scoping. It is not
   evidence, it cannot satisfy an acceptance criterion, and it can never contribute to a delivery
   decision. This is the map's rule verbatim ("the map informs scoping, **never** the gate") and it
   is what keeps *Evidence-Gated Advancement* intact while agents get smarter.

**The immediate gap this names:** `project_history` filters `Run.status == "APPROVED"`, so the shared
context carries **successes only**. Every cancelled, parked and thrashed run is invisible to later
runs — the lesson most worth carrying is the one systematically excluded. Widening that channel to
carry outcomes (not just deliveries) is the smallest change that makes runs stop repeating each
other's mistakes, and it needs no new storage.

**Explicitly NOT authorized by this ADR:** the digest's construction, its budget, and what it may
say about a failed run are a design cycle of their own, and a "what to avoid" digest is exactly the
kind of surface where a bad prior run teaches a wrong lesson. This ADR fixes the tier and the terms;
the widening lands under its own issue with its own measurement, per scope discipline.

### 5. Plan and design must not contradict each other

Both are run tier and both reach the coder, which is currently told to "follow the plan and the
design" with no tie-break. When they disagree the coder oscillates — observed for a whole run, five
identical operator corrections, then reverted by the coder itself. Two changes:

- **A stated precedence.** Where the two conflict, the design governs; it is the later, more grounded
  artifact and the reviewer already checks the diff against it.
- **A deterministic consistency check**, following the established
  [ADR-0073](ADR-0073-backlog-spec-lint.md) shape: pure detector → curator-ready findings → one
  bounded disposition pass → deterministic apply, knob-gated, best-effort, one shot and no loop.
  Precision over recall, and it must never block a run on its own uncertainty.

## Options considered

**Let a run write per-item constraints.** Rejected. It closes the propagation gap by erasing the
tier boundary, and a constraint an agent authored for itself is not a constraint.

**Always regenerate the design; delete the cache.** Rejected. It pays a model call every run to fix a
staleness bug, which trades a correctness problem for a cost problem and contradicts
deterministic-first. The key is the fix.

**Put the charter in the coder's system prompt.** Rejected as the primary mechanism. It would apply
to ad-hoc runs with no project, duplicates a carrier that already exists and is measured, and puts
project text on a path where nothing checks that it arrived.

**Silo runs completely — no cross-run context.** Rejected, and this is the option the ADR most wants
to name. It is the "shackle harness" posture: safe by making the team permanently ignorant, so every
run re-derives the repository and re-learns the same lesson. It also contradicts ADR-0063 directly.
Auditability, not amnesia, is the control.

**An LLM-summarised "lessons learned" memo carried between runs.** Rejected. It is a model summary of
model output with no attribution, it degrades across generations, and it is precisely the
unauditable, silently-accumulating influence this project exists to avoid. Evidence, attributable,
or nothing.

## Security implications

The cross-run digest is assembled from repository-derived and agent-derived text, which is
**untrusted input** under `AGENTS.md`. It is data, never instruction, and inherits the map's
boundary treatment ([`mapview`](../../packages/core/mosaera_core/mapview.py)) rather than a new one.

The gate exclusion in §4.4 is the load-bearing security property: a digest that could reach the gate
would let one run's output become another run's evidence, which is exactly the closed loop
*Independent Approval* forbids. The existing structural guard —
`scripts/check_layer_imports.py` already forbids `policies` from importing the map's modules,
making "the map never reaches the gate" un-writable rather than merely agreed — is the pattern to
extend to any new digest module.

Widening `project_history` to carry failures means park causes and gate reasons enter a prompt.
These are engine-authored strings, not repo content, so the injection surface does not widen; but a
failed run's *task text* is repo-derived and must stay clipped and treated as data.

## Operational implications

No migration. `run_diagnosis` already persists the failure-side data (`#75`, migration 0022); the
map already carries per-dimension fingerprints; `build_run_context` already exists, is budgeted, and
is deterministic. The work is a filter widening, a cache key, and a carrier extension — not new
storage.

Each behavioural change lands knob-gated and default-OFF, so the digest widening and the consistency
check can be measured against the existing instruments rather than asserted. The design cache key is
the exception: a stale-cache fix is a bug fix and ships on.

The charter reaching the coder increases the coder's prompt size on every run. Given the measured
97.4%-input token profile, that cost is real and should be measured, not assumed negligible.

## Consequences

**Good.** The two tiers stop being inverted. A charter constraint becomes binding rather than
aspirational. A stale design becomes impossible rather than unlikely. Runs stop repeating each
other's failures, and the repository stops being re-derived from scratch every run — the map's
fingerprints turn a deep dive into a verification pass. Agents get more context, and every piece of
it is attributable and out of the gate's reach.

**Bad.** More text reaches the coder, on a token profile that is already input-dominated. A
cross-run digest is a new place for a wrong lesson to persist, which is why it is gated, bounded,
attributable, and measured before it is trusted. The consistency check adds a detector that can be
wrong; precision over recall, and best-effort, keep a lint bug from breaking a run.

**Follow-up.** Three tracked pieces, each with its own issue: (a) charter constraints into the
carrier the coder reads; (b) the design cache invalidation key; (c) the plan↔design consistency
check. The cross-run digest widening (§4) is DIRECTION under this ADR, not authorization, and needs
its own issue, measurement, and — because a "what to avoid" surface can teach the wrong lesson — its
own red-team pass before it is trusted by default.
