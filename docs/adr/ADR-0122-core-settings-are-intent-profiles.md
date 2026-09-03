# ADR-0122: Core settings state INTENT; a profile derives the mechanics — as a default layer, never a ceiling

- Status: accepted
- Implementation: shipped — resolver, a Behavior section, per-knob provenance, and the visibility classification that takes the settings surface from 84 knobs to 12 (§6). Hiding only: nothing is locked (§6a)
- Date accepted: 2026-08-28
- Owners: Alejandro Rengifo
- Related issue / MR: none yet — filed as a `[prereq]` proposal in [docs/roadmap.md](../roadmap.md); this ADR is the design record that a tracked issue should cite
- Supersedes / Superseded by: — (**extends** [ADR-0005](ADR-0005-config-in-ui-settings.md): the settings precedence gains one layer)
- Related: [ADR-0046](ADR-0046-posture-and-autonomy-governance.md) (the restriction lattice this is deliberately NOT — see §4), [ADR-0057](ADR-0057-autonomous-oracle-posture.md) (`apply_oracle_posture`, which outranks `verification_profile` on autonomous runs), [ADR-0081](ADR-0081-control-liveness-ladder.md) (why a control that cannot fire is worse than no control), [ADR-0020](ADR-0020-autonomous-correctness-gate.md) (`autonomous_verified`, which stays a direct knob)
- Related threat model: none — no trust boundary moves. The delivery gate, the tool allowlist, and every knob governing what may ship are untouched, and §2's precedence rule is what makes that claim checkable rather than asserted.
- Review trigger: a profile is given ceiling semantics, `verification_profile` becomes the input to `apply_oracle_posture`, or a knob is added to a profile table that also appears in `NEVER_DERIVED`

**Decision summary:** `GENERAL_KNOBS` had grown to 80 entries, ~62 of them reachable in the Settings
page, and an operator is asked to decide things like how many identical failures constitute a stall.
Three **intent profiles** — `effort_profile`, `quality_profile`, `verification_profile` — now
derive those mechanics from a stated intent. The profiles are a new
layer in the ADR-0005 precedence chain, sitting **below** stored config: they can only supply a
value the operator never set. That single ordering choice is what keeps this change outside the
trust boundary, and it is the difference between this ADR and ADR-0046.

## Context

The settings surface has leaked the engine's internal architecture into its UX. This is not a
cosmetic complaint: ADR-0046 already recorded the underlying defect — *"our autonomy surface is a
scatter of independent opt-ins that compose in ways nobody reasoned about"* — and ADR-0034 recorded
what that scatter cost, a composition (`deliver_unverified` + reviewer silence) that shipped a
change with no validator and no reviewer.

ADR-0046's answer is a **posture**: one named, versioned statement of what a deployment permits,
which individual knobs may not exceed. It is accepted and remains DIRECTION under epic `#31`. It is
not what this ADR builds, and the distinction matters enough to state twice.

What is missing *below* that is more mundane. Even with a posture in place, an operator who wants
"try harder before giving up" must today set six knobs (`max_escalations`,
`reason_on_stall_enabled`, `max_reason_attempts`, `model_escalation_enabled`,
`max_model_escalations`, `coder_test_repeat_limit`) and know how they interact. There is no artifact
expressing the intent — only its decomposition.

## Decision

### 1. Three intent profiles, each owning a disjoint set of knobs

`effort_profile` (how hard a run tries) · `quality_profile` (the bar and the revision budget) ·
`verification_profile` (which independent checks run). Tables live in `config/_profiles.py`.

**Three, not four.** The first cut split `autonomy` from `recovery`, and no operator could tell
them apart — both answered *"how hard does it try?"*. The source proposal contradicted **itself**
about which one owned the recovery knobs, which was the evidence that the distinction was not real
rather than merely badly explained. A test enforced the split's consistency; consistency is not
meaning.

**The partition is enforced, not merely intended.** Two profiles writing one knob would make the
resolved value depend on dict iteration order; `test_profile_tables_are_disjoint` fails if that
ever becomes true.

### 1a. `effort_profile` DRIVES `reliability_sensitivity` instead of racing it

`reliability_sensitivity` (#51, ADR-0056) already scaled every self-stop budget, and
`apply_reliability_sensitivity` runs in `build_graph` — *after* this layer. A profile that set
`max_escalations` directly was therefore silently overwritten. Measured, not theorised:

```
recovery_profile=persistent                    -> max_escalations=2, max_iterations=8
  + reliability_sensitivity=cautious           -> max_escalations=0, max_iterations=2
```

The operator selected "persistent" and got **zero** escalations, with nothing to tell them. Two
dials on one axis, sharing the words *balanced* and *persistent* with different meanings. This is
the repository's recorded **second-origin** defect class, and it is the concrete reason the
profiles read as theatre: in that configuration one of them provably did nothing.

The fix is a division of ownership, not another override. `SENSITIVITY_OWNED` names the six knobs
that function overwrites, no profile may derive one, and `effort_profile` instead **sets
`reliability_sensitivity` itself** — so there is one dial, and the vocabularies match.
`test_profiles_never_touch_sensitivity_owned_knobs` is the regression guard, and
`test_the_profile_survives_graph_build` asserts the selection end-to-end through the seam the
defect lived in.

### 2. Precedence becomes `env > stored > profile > default` — the profile layer is BELOW stored

This is the load-bearing decision. A profile may only fill a knob the operator never set, so
selecting one can neither override nor weaken an explicit setting, and cannot change the behaviour
of a deployment that does not opt in.

Two consequences worth naming, because they are what make the change safe to land without a
red-team pass:

- **Upgrade is a no-op.** Profiles ship **unset**, not defaulted to `balanced`. Every profile row
  differs from at least one shipped `Knob.default`, so a default-on profile would silently re-tune
  every existing install. `test_no_profile_selected_changes_nothing` asserts the 80 pre-existing
  knobs resolve to their defaults with no profile selected; this was additionally verified against
  values captured from the pre-change tree, not only against the post-change defaults.
- **A profile is not a control.** It cannot deny anything, so nothing may come to depend on it for
  safety. That is why the clamp semantics stay with ADR-0046.

### 3. Safety knobs are structurally excluded

`NEVER_DERIVED` names the knobs no profile may set: `deliver_unverified`, `autonomous_verified`,
`scan_enabled`, `hygiene_gate_enabled`, `member_branch_delete`, `allow_cloud_egress`,
`backlog_spec_lint`, `stall_detection_enabled`. Each decides what the delivery gate permits or
whether a safety mechanism runs at all, and must stay a direct decision under an explicit control
path rather than a side effect of choosing "aggressive".

`test_profiles_never_derive_safety_knobs` asserts the set is disjoint from every table, so the
prohibition fails the suite instead of relying on a reviewer noticing. **Aggressive means more
attempts, never weaker evidence.**

### 4. What this is NOT: the ADR-0046 lattice

| | ADR-0046 posture | ADR-0122 profile |
|---|---|---|
| Direction | **Ceiling** — knobs may not exceed it | **Default** — fills only what is unset |
| Resolution | `min(configured, posture_ceiling)` | `configured or profile or default` |
| Can deny a ship? | Yes — a second veto | **No** — it is not a control |
| Seam | The evaluation seam (env, stored and direct construction all clamp) | The layering seam only |
| Status | accepted, DIRECTION | built |

A reader arriving at "profiles simplify the settings surface" could reasonably assume the tiering
work had begun. It has not, and building it here would have been the re-derivation failure this
repository has measured twice (F62, F58).

### 5. The UI shows what each option DOES, in sentences

A **Behavior** section leads the settings nav — intent first, then the mechanics that intent
derives. It holds the three profiles as dropdowns, and below them the thing that makes them
meaningful rather than decorative:

- **A side-by-side comparison of every option**, listing only the settings that actually DIFFER
  between them. A row identical in all three is noise that buries the decision the reader came to
  make. A three-way dial labelled only *cautious / balanced / persistent* asks someone to decode an
  adjective; showing the options against each other lets them predict the difference instead.
- **Sentences, not knob identifiers.** Each derived knob carries an `EFFECTS` line — *"How many
  times it may stop and reason about being stuck"*, never `max_reason_attempts: 3`. The first cut
  listed identifiers, which is a mechanism name presented as an intent control, and is precisely
  what made the feature read as theatre.
- **What no profile changes.** `NEVER_DERIVED` is served and rendered: effort changes how hard a
  run tries, never what evidence it must produce. That is the honest reassurance a profile chooser
  needs, and a test enforces it.
- **Which of a profile's settings you have overridden** — otherwise the comparison promises
  something the deployment is not doing.

All of it is **served from the derivation tables**, never copied into TypeScript: a client-side
copy would drift invisibly because both halves would still render.

Provenance also appears on the mechanics pages themselves, as per-knob badges — *from Effort* when
the profile supplied the value, *overrides Effort* when the profile owns the knob but an explicit
setting outranks it. The second is the load-bearing one: it is the case an operator hunts for when
a profile appears selected but "did nothing".

### 5a. What these descriptions deliberately do NOT claim

Every sentence describes **what the run will do**. None claims a profile delivers more often, and
the UI says so in as many words.

That is not modesty, it is the measurement position. On the ADR-0081 liveness ladder these profiles
sit at **C0/C1** — declared and read, never shown to change an outcome. Grounding an outcome claim
would need an A/B, and the arithmetic is unfavourable: detecting a 10pp delivery-rate difference
needs ~390 runs *per arm* at ~50% baseline, against a 26-case corpus whose case-vs-run independence
is undecided. Cost and wall-clock are far cheaper to establish — the effects are mechanically large
and the bench already records `usd`, `elapsed_s` and `iteration` per run.

So: **describe effort, promise nothing about success, and earn the numbers before printing them.**
The alternative is a label that sounds measured and is not, which is the failure this whole section
exists to avoid.

### 6. The settings surface is ELEVEN controls; the rest is hidden, not removed

`_visibility.py` classifies every knob as `core` / `developer` / `internal`, and the settings page
reads it: `core` renders, `developer` sits behind one *Show advanced configuration (N)* disclosure,
`internal` never renders. **88 knobs → 11 visible.** (41 developer, 36 internal.)

The classification lives in **two readable sets, not a field on each of the 85 `Knob` entries.**
That is the load-bearing choice: *"what does a new user actually see?"* has to be answerable by
reading one list. Spread across 85 constructor calls it is answerable only by a script, and a
surface nobody can read is a surface nobody can defend. It also means hiding a knob is a one-line
server change — and reversible by the same one line.

`visibility_of` defaults an unclassified knob to **`developer`, never `core`**. The failure mode of
the opposite default is a Core surface that grows by accident, one defensible knob at a time, which
is the condition this section exists to end. A test caps Core at 14.

Two judgment calls worth review:

- **The posture-forced oracle toggles become `internal`.** They were previously rendered with a
  "forced when autonomous" badge explaining that switching them off did nothing. Removing an inert
  control is better than explaining why it is inert.
- **`member_branch_delete` stays `developer`, not `internal`** — it is the only way an admin grants
  members branch deletion, and the Organization/Permissions surface that should own it does not
  exist. Hiding it would remove an administrative action rather than tidy one.

### 6a. Hidden is NOT locked, and the difference is not cosmetic

Every knob remains **fully settable by its environment variable**, whatever its visibility. This
slice changes presentation only: it crosses no trust boundary, needs no red-team pass, and can be
reverted by editing a set.

Making a knob genuinely unchangeable — the "config a client cannot alter" an enterprise product
ships — is a **different and larger change**. It must ignore env *and* stored config, which
contradicts the ADR-0005 precedence invariant, and for the safety knobs it touches the delivery
gate (CODEOWNERS + red-team). It is proposed in `docs/roadmap.md`, not built here.

**Do not describe a hidden knob as locked.** An operator with shell access can still set it, and
saying otherwise to a customer would be false. The proposal's "make the safety knobs always-on" and
"remove `deliver_unverified`" are therefore **not** satisfied — `deliver_unverified` is merely
unreachable from the UI at any depth.

### 7. `verification_profile` governs guided and ad-hoc runs only

`apply_oracle_posture` (ADR-0057) already force-enables the oracle stack on autonomous runs via
`POSTURE_FORCED_KNOBS`, and outranks this profile there. `general_settings_view` reports both facts
per knob — `derived_from` (which profile is in play) beside the existing `clamped_by` (what
overrides it at run time) — so the composition is visible rather than a surprise.

Making `verification_profile` the *input* to that posture is the coherent end state and is deferred:
it changes what the delivery gate permits.

## Consequences

**Good.** An intent is now a durable, inspectable artifact rather than a decomposition the operator
must reconstruct. The settings view reports provenance, so a value's origin is answerable. The
metadata makes the knob spec self-describing for the UI slice that follows.

**Costs and risks.**

- **A fourth precedence layer is a fourth thing to reason about.** Mitigated by keeping it strictly
  below stored — the rule "anything you set wins" needs no exceptions.
- **The profile tables are policy values, not measurements.** The quality thresholds in particular
  are initial guesses carried over from the proposal and should be tuned against run data. Nothing
  outside the table depends on the specific numbers.
- **A profile could accrete safety meaning by drift.** `NEVER_DERIVED` plus its test is the guard;
  the review trigger above is the second.
- **Two settings vocabularies now coexist** (profiles and raw knobs) until the UI slice lands. This
  is the cost of not colliding with in-flight work on the settings page, and it is temporary.
