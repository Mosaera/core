# ADR-0046: Posture & autonomy governance — Free/Business/Regulated as policy-as-code, and the enablement ceremony

- Status: accepted
- Date: 2026-07-16
- Owners: Alejandro Rengifo
- Related issue: #31 (design ADRs for Waves B/C), #13 (enterprise policy pack), #19 (governed-execution business)
- Related: [ADR-0004](ADR-0004-auth-and-session-model.md) (admin = a role; the service token is not admin — the ceremony's threat model starts here), [ADR-0005](ADR-0005-config-in-ui-settings.md) (env>stored>default; the env-only knob precedent the grant joins), [ADR-0012](ADR-0012-cohesive-team-supervision.md) (the run modes posture clamps), [ADR-0024](ADR-0024-cloud-egress-and-price-gate.md) (a consent gate + one predicate at three seams — the shape this generalizes), [ADR-0034](ADR-0034-only-executed-evidence-may-ship.md) (the evidence gate posture composes with and must never loosen), [ADR-0035](ADR-0035-infrastructure-failure-is-loud.md) (`guard_bind`/`guard_memory` — refuse-to-boot precedent), [ADR-0036](ADR-0036-test-integrity-baseline.md) (the baseline/hash-chain spirit reused for the audit log), [ADR-0044](ADR-0044-oracle-make-real.md) (evidence is measured, not asserted), [ADR-0045](ADR-0045-the-firm-teams-as-modules.md) (posture is firm-wide/per-project, never per-team)
- **Related:** [ADR-0113](ADR-0113-the-oracle-plan-is-chosen-at-onboarding.md) — the per-project posture is now chosen during onboarding (§7's "set during the interview", built). The INITIAL choice only: no relaxation mechanism is introduced, the lattice is unmodified, and the flow names posture as a different axis from the ADR-0012 run mode it is routinely confused with.
- Related threat model: docs/threat-models/TM-0001, TM-0002 (the ceremony spans both the run trust boundary and the API/admin surface) — **no threat-surface change lands with this ADR; nothing is built yet**

## Context

The north star commits to autonomy as a **posture** keyed to the operator's compliance reality —
from a solo hobbyist running fully unattended, to a regulated/DoD deployment where nothing acts
without human judgment. Three profiles: **Free / Business / Regulated**, as *policy-as-code* in
`packages/policies`, each control **mapped to a named framework control**, with unattended autonomy
in the Regulated tier reachable only through a **dual-control enablement ceremony**.

**The problem this actually solves is not "enterprises want tiers." It is that our autonomy surface
is a scatter of independent opt-ins that compose in ways nobody reasoned about.** Today, whether a
run can ship unattended is decided by the interaction of at least: the per-run mode
(guided/autonomous/high-assurance, ADR-0012), `autonomous_verified` (ADR-0020), `reviewer_advisory`
(ADR-0029/0031), `deliver_unverified`, `resilient_sweep` + `resilient_recuration` (ADR-0023),
`auto_open_mr` + `mr_granularity` (ADR-0019/0021), `model_escalation_enabled` (ADR-0022),
`allow_cloud_egress` (ADR-0024), and `reason_on_stall_enabled` (ADR-0017). The roadmap separately
notes **~15 of these knobs aren't even reachable in the UI**.

This is not hypothetical drift. [ADR-0034](ADR-0034-only-executed-evidence-may-ship.md) found
exactly this failure: *"four mechanisms built under the old direction were never re-audited"* — and
one composition (`deliver_unverified` + reviewer silence) produced **a ship with no validator and
no reviewer**. Each knob was defensible alone. The composition was not, and no single artifact
described what the system as a whole would do.

A posture is that missing artifact: **one named, versioned, reviewable statement of what this
deployment permits**, which the individual knobs cannot exceed.

The second forcing function is **pivotability**. Regulation for autonomous AI is nascent and will
change. If posture rules are `if` statements scattered through the engine, every regulatory change
is an engine change — and the engine is the part under a trust boundary that we least want churning.

## Decision

### 1. Posture is a restriction lattice. It can only TIGHTEN, never loosen. *(the load-bearing invariant)*

A posture is **a second veto, never an override.** The final decision is a conjunction:

```
may_ship  =  evidence_gate_allows(state)   AND   posture_allows(state, profile)
```

Posture **cannot authorize a ship the evidence gate denies.** ADR-0034/0044 decide *what evidence
suffices*; posture decides *what is permitted on top of that*, and the only direction it can move is
more restrictive. `Free ⊇ Business ⊇ Regulated` in permissiveness.

This invariant is the whole ADR. Without it, "posture" is just another knob in the scatter — and the
first support ticket asking "can we get a posture that lets us ship without the oracle?" turns the
compliance feature into the gate bypass. **The tier that sounds strictest must never be reachable by
loosening; there is no posture that permits more than Free.** Free is the ceiling, not the wild west.

### 2. Posture clamps the knobs; the knobs cannot exceed the posture

Every autonomy knob above becomes **clamped** by the active profile, exactly as ADR-0035 clamped
`--network host` in `DockerSandbox.__init__` rather than trusting `Knob.choices`. That precedent is
load-bearing and its lesson is precise: *`choices` guards only the UI write path — a stored value,
an env var, or a direct constructor call all bypassed it.* Posture must therefore clamp **at the
evaluation seam, not at the settings-write seam**. A stored `settings.json`, a `MOSAERA_*` env var,
and a direct `Settings(...)` construction must all land in the same clamp.

A knob may always be *more* restrictive than the posture. It may never be less. Resolution:

```
effective(knob) = min(configured(knob), posture_ceiling(knob))     # min over the restriction lattice
```

This is deliberately the ADR-0024 shape: **one predicate, applied at every seam** (that ADR's
`models.cloud_tier_allowed` at three seams closed a previously-unguarded cloud path). Not a new
`if` per knob.

### 3. The three profiles, mapped to the human-supervision taxonomy

The **DoD 3000.09 in/on/out-of-the-loop taxonomy** gives the vocabulary:

| Profile | Supervision | Unattended delivery | Intent |
|---|---|---|---|
| **Free** | **out-of-the-loop** permitted | Yes, subject to the evidence gate | Solo operator / hobbyist. Autonomy is the default; the evidence gate is still absolute. |
| **Business** | **on-the-loop** | Yes, within bounds; human monitors and can veto at any time | Commercial default. Autonomy is granted by config, revocable instantly. |
| **Regulated** | **in-the-loop** | **No — by default nothing ships without a human decision** | Regulated/DoD. Unattended autonomy is reachable *only* via the §4 ceremony, time-boxed. |

> **Honest scoping note.** DoD Directive 3000.09 governs *autonomy in weapon systems*. We borrow its
> human-supervision **taxonomy** because it is the clearest published articulation of the in/on/out
> distinction — **not** because it applies to a software firm, and not as a claim of conformance to
> it. Saying so here so the citation is never read as a scope claim.

### 4. The enablement ceremony (Regulated → unattended)

Four independent conditions, **all** required. Each is independently sufficient to *deny*:

1. **Dual control** — two distinct `is_admin` sessions (ADR-0004) co-sign the grant. Two *different*
   principals; a single admin cannot co-sign with itself.
2. **Out-of-band activation** — a **server operator** activates it via an **env var + restart**.
3. **Time-box** — the grant carries an expiry. Org-configurable, **default ~90 days**. No auto-renew.
4. **Tamper-evident audit** — every step (propose, co-sign, activate, expire, revoke) is written to
   an append-only, hash-chained, exportable log.

**Why out-of-band is the crux, and not ceremony theatre.** Under ADR-0004 an `is_admin` session can
already write config and read secrets. If the autonomy grant were ordinary app config, then **one
compromised admin session = unattended autonomy** — the highest-consequence capability in the
product, reachable by the same credential that changes a model name. Requiring an env var + restart
forces the attacker to also hold **host/filesystem access**, a *categorically different trust
domain*. The ceremony's security value is precisely that **no single compromised credential in
either domain suffices**; it is dual control across *domains*, not merely across *people*. This is
also why the grant joins the ADR-0005 env-only list (bind/port/tokens/db/sandbox-backend) rather
than living in `settings.json` — same reasoning, established precedent.

The grant is therefore a **conjunction evaluated at run start**:

```
unattended_allowed = env_activated AND co_signed_record_valid AND NOT revoked AND NOT expired
```

### 5. The asymmetric off-switch — one click, one actor, no restart

**Turning autonomy on is a ceremony. Turning it off is one click.**

Revocation requires **one** actor, **no** co-sign, **no** out-of-band step, **no** restart, and takes
effect on the **next run start** — immediately, from the UI. It is a stored flag in the conjunction
above; flipping it denies regardless of the env var.

The asymmetry is deliberate and is a safety property, not an inconsistency: **the cost of a control
must be paid in the direction of danger.** Making revocation as hard as activation would mean that
during an incident — the moment you most need to stop the firm — you would need to find a second
admin and a server operator with shell access. That is a safety control that fails exactly when it
is needed. A restart-gated off-switch is not an off-switch.

Note the pleasing consequence of the conjunction: revocation is *fail-safe by construction*. The
env var alone was never sufficient, so revoking doesn't have to race it.

**Expiry is fail-closed.** A lapsed grant reverts to in-the-loop with no action and no alert-fatigue
renewal path. Renewal is a **fresh ceremony**, not a click — otherwise the time-box degrades into a
recurring rubber-stamp, which is the failure mode of every 90-day control ever shipped.

### 6. Pivotability — profiles are versioned, control-mapped DATA

A profile is data: a set of controls, each carrying a `control_id` mapping to a named framework
control, and a **profile version**. New or changed regulation ⇒ **a new profile version**, reviewed
through CODEOWNERS — **without touching the engine**.

Every run **records the profile version that governed it**. Auditability is retrospective: "this run
shipped on 2026-08-01 under posture `regulated@v2`, which mapped AC-6 to X." Without the recorded
version, a later profile edit silently rewrites the meaning of past runs — the audit-log equivalent
of a dangling pointer.

Indicative control mapping (the mapping is *traceability*, not conformance — see §Security):

| Control | Framework | Realized by |
|---|---|---|
| Separation of duties | NIST 800-53 **AC-5** | Dual-control co-sign + out-of-band activation by a different actor (§4) |
| Least privilege | NIST 800-53 **AC-6** | Deny-by-default tool allowlist (`scoped_tools`, `allowlist.py:59`); service token ≠ admin (ADR-0004) |
| Access enforcement | NIST 800-53 **AC-3** | The delivery evidence gate (`packages/policies`) |
| Audit review | NIST 800-53 **AU-6** / CMMC **AU** | Exportable audit log (SIEM) |
| Protection of audit information | NIST 800-53 **AU-9** | Hash-chained, append-only entries (§4.4) |
| Human supervision of autonomy | DoD **3000.09** taxonomy | in/on/out-of-the-loop → the three profiles (§3) |

### 7. Scope — posture is firm-wide and per-project, never per-team

Per [ADR-0045](ADR-0045-the-firm-teams-as-modules.md): a team cannot grant itself autonomy. Posture
resolves as **firm default → per-project override**, and a project may only be *more* restrictive
than the firm default (the same lattice as §2). The per-project posture is set during the onboarding
interview and recorded in the charter ([ADR-0047](ADR-0047-project-onboarding-and-the-durable-map.md)).

## Options considered

- **Posture as a preset that expands the knobs** ("apply Regulated" writes 15 settings). Rejected —
  a preset is a *starting point*, not a *constraint*: the next config write silently drifts out of
  the posture and nothing detects it. This is exactly how the current scatter arose. A posture must
  be **evaluated**, not **applied**.
- **Posture as the only autonomy control (delete the knobs).** Rejected — the knobs express genuine
  per-run/per-project intent below the ceiling, and a big-bang removal would be a breaking change
  across nine ADRs' worth of behavior. Clamping subsumes them without deleting them.
- **Ceremony entirely in-app (two admins co-sign, no env var).** Rejected — see §4. It reduces the
  highest-consequence capability to a single compromised trust domain. This was the tempting design
  and it is the one that matters most to have rejected in writing.
- **Ceremony entirely out-of-band (env var only, no co-sign).** Rejected — a single server operator
  could grant unattended autonomy with no application-level record and no second principal. Fails AC-5.
- **Symmetric off-switch** (revocation needs the same ceremony). Rejected — §5. A safety control that
  is slowest during an incident is not a safety control.
- **Auto-renewing time-box.** Rejected — degrades to a rubber stamp; the control becomes a calendar
  event rather than a decision.
- **Claim compliance / pursue certification now.** Rejected as out of scope and dishonest at this
  maturity — see below.

## Security implications

- **This ADR IS the trust boundary.** Posture lives in `packages/policies` — CODEOWNERS-protected,
  deny-by-default. Per `AGENTS.md` any change here requires explicit human approval, and per
  CLAUDE.md a merged trust-boundary change triggers an adversarial red-team pass **before** further
  building.
- **Control-mapped is NOT certified, accredited, or compliant.** We map controls so an auditor can
  *trace* our mechanism to a named control. We do **not** claim NIST 800-53 / CMMC conformance, an
  ATO, FedRAMP, or DoD 3000.09 applicability, and no artifact this ADR produces may be marketed as
  such. Overclaiming compliance is both a legal exposure and precisely the "assert, don't measure"
  dishonesty ADR-0044 removed from the oracle. **The audit log is evidence for an assessor; it is
  not an assessment.**
- **Tamper-evident is NOT tamper-proof.** A hash chain lets you *detect* that history was rewritten;
  it cannot *prevent* a root operator from rewriting the whole chain, since they hold the head.
  Detection is only real against an **externally anchored** copy — hence "exportable" is a security
  requirement (periodic SIEM/append-only export), not a convenience feature. Stated plainly so
  nobody reads the hash chain as stronger than it is (ADR-0035: the system must not stay quiet about
  what it cannot do).
- **Deny-by-default on the miss path.** An unknown/unparseable/absent profile must resolve to the
  **most restrictive** posture, never to Free. `strength`'s `"unknown"` default (ADR-0034) is the
  precedent: the miss path is the one attackers pick.
- **The clamp must sit at evaluation, not at the settings write.** ADR-0035's `--network host` bug in
  full: `Knob.choices` guarded the UI path while a stored value, an env var, and a direct constructor
  call all sailed past. A posture clamped only in `coerce_general_patch` would have the identical hole.
- **Revocation must not be admin-gated into unavailability.** If revocation requires an `is_admin`
  session and the admin is who you're revoking *because of*, the control fails. Revocation should be
  available to any authenticated principal — it can only ever *reduce* capability, so a hostile
  revoker is a denial-of-service at worst, and DoS on autonomy is the fail-safe direction.

## Operational implications

- **Zero runtime change lands with this ADR** — design only. No knob, no schema, no migration.
- When built: the audit log is durable state ⇒ an **Alembic migration** (`packages/memory`), never
  `create_all`. Export is a first-class endpoint, admin-gated (ADR-0004).
- The env-var grant means **activation requires a restart** — an operational cost accepted on the
  danger-facing side of the asymmetry (§5). Revocation must not inherit it.
- Runs must record `posture_profile` + `profile_version` for retrospective audit (§6).
- Expect the Regulated default (in-the-loop) to **reduce measured autonomy** on regulated
  deployments. That is the product working, and it should be reported honestly rather than tuned
  away — the ADR-0034 precedent (MCB Autonomy dropped on shallow cases, by design).
- **Docs-only domain** (`docs/`), disjoint from `#29`/`#30` — safe to land in parallel.

## Consequences

**Good.**
- Replaces a 15-knob scatter that composes unpredictably with **one named, versioned, reviewable
  statement** of what a deployment permits — the artifact whose absence ADR-0034 diagnosed.
- The tighten-only lattice makes the compliance feature structurally incapable of becoming a bypass.
- Dual control *across trust domains* means no single compromised credential grants unattended
  autonomy.
- Pivotability is real: profiles are versioned data, so a regulatory change is a reviewed data
  change, not an engine change.
- The asymmetric off-switch means the incident path is one click.

**Bad / accepted costs.**
- Activation genuinely requires host access + a restart. Some operators will find this
  user-hostile; that is the intent, and support pressure to soften it should be refused **here**,
  in writing, rather than negotiated later per-customer.
- Clamping touches every autonomy knob's evaluation seam — broad, and it crosses `packages/policies`
  (CODEOWNERS) plus `config/_knobs.py`/`_settings.py` (**declared hot files** — pre-place the
  scaffolding in the arc's foundation phase so later parallel phases don't both edit them).
- Three profiles is a guess at the shape of demand. Free/Business/Regulated is the north star's
  framing, not a researched taxonomy; the versioned-data design is what makes the guess cheap to
  correct.

**Follow-up work (none scheduled by this ADR).**
1. The profile data model + the tighten-only resolver (`packages/policies`), deny-by-default on miss.
2. The clamp predicate, applied at every autonomy-knob evaluation seam (the ADR-0024 one-predicate-
   many-seams shape).
3. The ceremony: co-sign records, the env-only activation, expiry, and the one-click revoke.
4. The hash-chained audit log (Alembic) + the export endpoint + external anchoring guidance.
5. Record `posture_profile`/`profile_version` on every run.
6. Surface it in the UI — this is where the ~15 unreachable autonomy knobs get a coherent home
   (the UI-refresh backlog), and dropdowns-not-free-text applies (ADR-0005).
7. **Red-team the ceremony before it ships** — CLAUDE.md mandates an adversarial pass on any merged
   trust-boundary change. Target the composition first (posture × the nine existing knobs), because
   composition is where the last one broke.

**Honest residual.** Posture governs **what the firm is permitted to do**, not **whether the firm is
right**. A Regulated deployment with a rubber-stamping human in the loop is compliant and unsafe;
posture cannot detect that, and this ADR does not pretend to. Correctness remains the evidence
gate's job (ADR-0034/0044) — posture only ever narrows what a green gate is allowed to do next.
