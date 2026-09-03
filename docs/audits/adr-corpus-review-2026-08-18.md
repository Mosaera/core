# ADR corpus review — staleness, buried work, and what is worth doing now

- Date: 2026-08-18
- Scope: all 101 ADRs in `docs/adr/`, read end to end, cross-checked against the code, the
  README Records table, and `docs/roadmap.md`
- Method: ten read-only passes over consecutive batches, plus four corpus-wide mechanical checks.
  Every finding cites the two facts that disagree. Findings marked **[verified]** were re-checked
  by hand against the named file.
- Nothing in this review changed any file except `ADR-0084`'s `Implementation:` line and this
  document.

## What "stale" means here

Two facts already in the repo disagree — the standard `scripts/check_doc_claims.py` already uses,
so findings here can feed it. This review deliberately does **not** propose `last-reviewed` dates,
mandatory header backfill, or any new metadata: `docs/research/documentation-retrievability-and-staleness-2026-08-06.md`
rejected those with reasons, and its principle stands — *a status a human types is structurally
unfixable; a status that is DERIVED cannot go stale.*

| Class | Meaning |
|---|---|
| S1 | Header or body contradicts the code |
| S2 | ADR contradicts its README Records row |
| S3 | Supersession/amendment is one-directional |
| S4 | Dangling reference (cited ADR, file, issue, or roadmap item that does not exist) |
| S5 | Follow-up described as pending that has actually shipped |
| S6 | Decision quietly overtaken by a later ADR, neither saying so |
| S7 | Rationale no longer holds (judgement, marked as opinion) |

## Headline numbers

| Measure | Result |
|---|---|
| ADRs reviewed | **101** (0030, 0037, 0096 are tombstones/unmerged) |
| Stale | **56** |
| Clean | **45** |
| One-directional supersede/amend links | **29 — every single one in the corpus** |
| Dangling `ADR-NNNN` references | **0** |
| README Records rows missing or orphaned | **0** |
| Archive candidates | **1** (ADR-0086) |

## Corpus-wide findings (mechanical, whole-corpus, not visible per-ADR)

**1. Supersession is 100% one-directional. [verified]** 29 supersede/amend links exist; **zero**
are acknowledged by their target. ADR-0079 has five successors (0089, 0090, 0092, 0095, 0097) and
mentions none of them. ADR-0075 has three. Anyone opening a superseded ADR reads it as current.
The `docs/research/…staleness…` doc names bidirectional supersession as a high-yield lint that
*"almost nobody implements"* — it is the single highest-value mechanical fix available, and it is
derivable: the forward links already exist, so the back-link can be generated rather than typed.

**2. The README Records index is healthy. [verified]** All 101 rows present, no orphans, 100/101
statuses agree (ADR-0070's `**SUPERSEDED / REVERTED**` vs `reverted` is cosmetic). The
hand-maintained index is *not* the problem — contrary to what the ADR-practice literature predicts
at this corpus size. Its one content defect is the ADR-0104 row (below).

**3. Three header generations coexist, and the template describes the least-used one. [verified]**
89 ADRs use `- Status:`; 9 (0084–0092) follow `ADR-0000-template.md` fully with `Implementation:` /
`Review trigger:`; the newest 12 (0093+) switched to bolded `- **Status:**` with invented fields
(`Scope`, `Amends`, `Invariants`, `Builds on`) and **dropped `Implementation:` entirely**. The
field whose wrongness prompted this review exists on 10 of 101 and current practice has abandoned
it.

**4. The doc-drift ledger has itself drifted. [verified]**
- `docs/roadmap.md:1274-1275` states the template's `Implementation:` / `Date accepted:` fields are
  ones *"**zero** ADRs use"* — **10 ADRs use them.**
- `scripts/check_doc_claims.py:28` states *"ADR-0077 uses none of the template's field names"* —
  ADR-0077 carries `- Status:`, `- Date:`, `- Owners:`, `- Related issue:`. The guard that exists
  to catch contradicted claims contains one, for the second time (its docstring records the
  earlier "wired into nothing" instance).

**5. Structural reference checks are clean, semantic ones are not. [verified]** Every `ADR-NNNN`
citation resolves to a file on disk. But ADR-0042 cites **ADR-0036** (test-integrity) as the
antecedent for a clone-token host-equality fix — a link that resolves and points at the wrong
record. No mechanical check can catch that class.

## The severe ones — read these first

### ADR-0047 — the header says nothing was built; a whole subsystem was [verified]
Line 8: *"no threat-surface change lands with this ADR; **nothing is built yet**"*. Line 208:
*"**Zero runtime change** — design only. No knob, no schema, no migration."*
Reality: migration `0017_onboarding_map_and_charter.py`, 14 modules under `mosaera_core/recon/`,
38 files referencing ADR-0047, and **9 rows in TM-0001** citing it. The same file at lines 472–549
says *"MR3 delivered"*, *"MR4 delivered"*, *"#42 (MR1–MR4) is complete."*
**Why it is the worst:** the false claim is *"no threat-surface change"*, on a subsystem TM-0001
describes as running eight categories of host tooling across an untrusted clone. Triage by header
skips the thing that most needs review, and the threat model already knows better.
**Fix:** prepend a dated amendment recording MR1–MR4 as shipped, or strike the two claim clauses.

### ADR-0072 — reads ACTIVATED for a control switched off the same day [verified]
ADR line 106: *"Amendment (2026-08-02) — posture **ACTIVATED** as a bounded, expiring accept"*,
with *"EXPIRY — review by 2026-11-02"*.
`config/_settings.py:361-364`: *"posture activation **WITHDRAWN** 2026-08-02 after a null n=25/arm
A/B (pooled Fisher p=1.0)"* → `oracle_structural_spec: bool = False`.
The ADR carries a future review date for an accept that no longer exists.
**Fix:** append "Amendment 3 — posture WITHDRAWN" with the n=25 null; correct the Status line.

### ADR-0104 — a client secret's location disagrees in three places [verified]
`docs/adr/README.md`: *"Client secret **ENV-only**"*. `routes/settings.py:138`:
`encrypt_secret(secret)` — stored. ADR-0104 line 133, in rejected-alternatives: *"Env-only matches
precedent"* — still rejecting what shipped, while an Amendment **higher in the same file** reverses
it. Only TM-0002 tracked the change.
**Fix:** correct the README row and `roadmap.md:53`; mark the rejected alternative REVERSED.

### ADR-0086 — silently overtaken; the one archive candidate [verified]
Proposes `risk-gated` as *"the new default"*. Shipped instead:
`MODES = ("ask", "accept", "auto")` (ADR-0101). `risk_gated` appears **once** in the codebase, as
prose. **ADR-0101 never mentions ADR-0086.** Unlike the other 29 gaps, here neither record points
at the other.
**Fix:** supersede-and-archive, re-homing §2's risky-write list (protected paths, assertion-floor
drops, truncated payloads), which is genuinely unbuilt and worth keeping.

### ADR-0081 — the ratchet that has never moved [verified]
`scripts/check_control_liveness.py` declares six grandfathered posture knobs and says the list
*"may only SHRINK"*. `git log -S'GRANDFATHERED'` returns **exactly one commit** — the one that
created it (bc33be8, 2026-08-04). Two weeks on, zero notches. Separately, Amendment 1 Decision 7
claims the check is now mechanical via `experiment_report()`; that function has **no production
caller** — only its definition and tests. ADR-0082:224 says so out loud: *"that silence is not
compliance."*
**Fix:** add a roadmap item owning the six C3/C4 sentinels; correct Decision 7 to say the check is
still a human procedure at the call site.

### ADR-0082 — contradicts itself 15 lines apart
Line 205: *"§1/§5 **BUILT** 2026-08-07"*. Line 220: *"**Deliberately NOT built, and still
DIRECTION:** §1/§5 …"*. Code sides with "built" (`schemas.py:106-112`, `_gate_outcomes.py`).

### ADR-0058 — a deleted mechanism still reads as current authority
§3 describes `react_on_bad_test` / `diagnose_test_review` as shipped. Neither symbol exists;
`_posture.py:46` records the removal by ADR-0060. ADR-0058 carries no amendment note.

### ADR-0061 — the definition of done disagrees with itself
The ADR retired *"`false_ship` ≈ 0 on held-out inputs"* as **exploitable** (names no suite, no n,
no configuration). `roadmap.md:886` — the "four measured gates (ADR-0061)" table — still carries
that exact retired wording, as does `:1009`. The roadmap knows about the amendment at `:584` and
`:1291`, so the table row is unreconciled, not unaware.

## Full table

Legend — **Deferred**: shipped / roadmap (still tracked) / **forgotten** (in neither) / none.

| ADR | Stale | Classes | Contradiction (short) | Fix | Deferred | Useful now | Archive |
|---|---|---|---|---|---|---|---|
| [ADR-0001] | yes | S1,S5 | Alembic "head `0007`" vs `0028` on disk; Semgrep/dashboard/PostgresSaver listed as follow-up, all shipped **[verified]** | correct head; move shipped items to "Delivered since" | shipped; Trivy on roadmap | Trivy — only unshipped scanner, seam documented | no |
| [ADR-0002] | yes | S5 | "dynamic escalation remains future work" vs ADR-0016/0022 built it | point at ADR-0016/0022 | shipped; work-packet store forgotten | no | no |
| [ADR-0003] | yes | S4 | cites "roadmap `#23`"; roadmap has no `#23` **[verified]** | say "issue #23, not roadmap-tracked" | forgotten | no — cross-run reuse buys a staleness surface | no |
| [ADR-0004] | yes | S5 | TM-0002, per-user rate limiting, audit attribution all listed as follow-up; all exist | replace with "Delivered since" | shipped | n/a | no |
| [ADR-0005] | yes | S1 | "`GENERAL_KNOBS` (~30)" vs **76** **[verified]** | "~30 at writing; 76 today" | shipped | n/a | no |
| [ADR-0006] | yes | S5 | "Follow-up: land TM-0002" — TM-0002 exists, and its own header cites it | mark delivered; keep PII/retention open | **forgotten** (PII scrub, retention) | **yes** — ADR names secret leakage into `run_events` the load-bearing risk; `connectors/redact.py` is a ready helper | no |
| [ADR-0007] | yes | S1 | capability enum omits `modify`/`subtract` (MCB-27/28 declare them); no case uses the `trivial` tier | widen enum; drop "trivial floor" | forgotten (real-repo cases) | yes — `_CAPABILITY_ORDER` still lists 5, so new cases fall outside the rollup | no |
| [ADR-0008] | yes | S1 | `pm_step_limit` "default 12" vs **20** **[verified]** | note the change | roadmap (as debt to delete) | **yes** — `similar_doctrine` has zero call sites; repo pays embedding cost on every artifact write **[verified]** | no |
| [ADR-0009] | yes | S5 | "autonomous between-item curation. Deferred" vs `_escalation.py` re-curates in the sweep | point at ADR-0023 (narrower form) | shipped; live mutation-tools forgotten | no | no |
| [ADR-0010] | yes | S5 | same deferral listed; shipped via ADR-0023 | as above | mixed; semantic dedupe + manual split/merge UI forgotten | no | no |
| [ADR-0011] | yes | S5 | "Still deferred: autonomous between-item curation" — shipped | strike that item | roadmap (dead semantic recall) | yes — delete-or-wire `similar_artifacts` | no |
| [ADR-0012] | no | — | none | n/a | forgotten (per-hop routing) | no — cost argument still holds | no |
| [ADR-0013] | yes | S4 | SOP names `graph.py`; it is now the `graph/` package | repoint to `graph/build.py` | forgotten (4 items) | partly — persona migration is cheap; 2 of 5 roles migrated | no |
| [ADR-0014] | no | — | none | n/a | forgotten (persisting model list) | no | no |
| [ADR-0015] | no | — | none | n/a | shipped (default-on via posture) | n/a | no |
| [ADR-0016] | yes | S5 | "wire the loop into the live runner. Deferred" — ADR-0022 did it | add ADR-0022 pointer | shipped; live no-op detector forgotten | **yes** — detector already written, one thread-through away; 45/61 escalations made zero calls | no |
| [ADR-0017] | no | — | none | n/a | forgotten (per-kind budget) | no — conditioned on measurement | no |
| [ADR-0018] | yes | S5 | "Cloud reason tiers are deferred" vs `nodes_reason.py:33` gating on `cloud_tier_allowed` | add "superseded in part by ADR-0024" | shipped | n/a | no |
| [ADR-0019] | yes | S3 | **rejects** per-item MRs; `mr_granularity` defaults to `"item"` **[verified]** | add "amended by ADR-0021/0102" | forgotten (per-project toggle) | no | no |
| [ADR-0020] | no | — | none (ADR-0057 declares the widening) | n/a | shipped via successors | n/a | no |
| [ADR-0021] | yes | S3,S5 | zero forward refs though ADR-0102/0103 amend it; branch-cleanup pass shipped | add "Amended by" line | shipped; DAG-parallel stacks forgotten | yes | no |
| [ADR-0022] | no | — | none | n/a | shipped (ADR-0024 gate) | yes | no |
| [ADR-0023] | no | — | none | n/a | forgotten (retry-with-enhance) | yes | no |
| [ADR-0024] | yes | S5 | Node sandbox follow-up listed pending; shipped via ADR-0032 | mark discharged | shipped; proxy debt on roadmap | yes | no |
| [ADR-0025] | yes | S1 | locates the floor in `validation.py`; it is in `languages/python.py` | add "relocated by ADR-0032" | shipped | yes | no |
| [ADR-0026] | yes | S1,S3,S6 | claims "**no plumbing**" — code says the key was undeclared so **the rule never fired**; rejected alternative (`tests_tampered`) was adopted | add "corrected by ADR-0036" | none | yes — rule now fires | no |
| [ADR-0027] | yes | S5 | cross-language cases "follow-on arc" — MCB-23/26 shipped | mark discharged; flag MR-C/MR-D | **forgotten** (MR-C, MR-D) | partly | no |
| [ADR-0028] | yes | S3 | still asserts "unparseable → UNKNOWN"; ADR-0034 split out `CONFLICT` | add correction pointer | forgotten (structured verdict) | yes | no |
| [ADR-0029] | no | — | none — **the only fully bidirectional chain in the corpus** (0029↔0031↔0034) | n/a | forgotten | history only | no |
| [ADR-0031] | no | — | none — discloses its own narrowing by ADR-0034 | n/a | roadmap (posture profiles) | yes | no |
| [ADR-0032] | no | — | none | n/a | **forgotten** (plugin contract + untrusted-pack threat model) | yes | no |
| [ADR-0033] | no | — | none — all four call sites verified | n/a | shipped | yes | no |
| [ADR-0034] | no | — | none | n/a | shipped via ADR-0036 | yes | no |
| [ADR-0035] | yes | S5 | two residuals ("`guard_bind` env-var gap", "secrets plaintext") closed by ADR-0042/0039, unnoted | add "Residuals closed by" | shipped | yes | no |
| [ADR-0036] | no | — | none | n/a | live via successors | yes | no |
| [ADR-0038] | no | — | none — charset regex matches verbatim; fuzz-pinned | n/a | none | yes | no |
| [ADR-0039] | yes | S1,S4 | "never a silently-wrong credential" vs `_from_env.py:36-39` deliberately degrading to "no token" (M-2); path cites `_settings.py`, code is `_from_env.py` | qualify to write/use paths | none | yes | no |
| [ADR-0040] | yes | S5 | "UI follow-up (deferred)" vs `AuthGate.tsx` rendering the field **[verified]** | mark shipped | shipped | yes | no |
| [ADR-0041] | no | — | none — `make lint` now runs six guards, three more than named | n/a | live (ratchet) | yes | no |
| [ADR-0042] | yes | S4 | cites ADR-0036 (test integrity) as antecedent for a clone-token fix — wrong record **[verified]** | drop the mis-link | shipped | yes | no |
| [ADR-0043] | no | — | none | n/a | **forgotten** (`max_escalations_ceiling`) | no — conditional | no |
| [ADR-0044] | yes | S5,S3 | "full line-level change coverage … future work" — ADR-0049 shipped it | add ADR-0049 pointer | shipped | yes | no |
| [ADR-0045] | yes | S4 | mis-cited in 4 places for PM sessions that **ADR-0048** owns; roadmap logs this at `:1269` and it was never acted on | repoint 4 citations | roadmap (DIRECTION) | yes — the "don't build from N=1" constraint | no |
| [ADR-0046] | no | — | none — every site states enforcement is unbuilt | n/a | roadmap (DIRECTION) | yes | no |
| [ADR-0047] | **yes** | **S1** | **"nothing is built yet" / "no migration" vs migration 0017, 14 recon modules, 9 TM-0001 rows [verified]** | **prepend dated amendment** | roadmap | yes | no |
| [ADR-0048] | no | — | none | n/a | roadmap | yes | no |
| [ADR-0049] | no | — | none — amendment matches the tree exactly | n/a | roadmap | yes | no |
| [ADR-0050] | yes | S5,S3 | "Follow-ups #2–#4 stand" — #2 shipped as ADR-0051 same day | mark #2 resolved | #3 roadmap; **#4 forgotten** | yes | no |
| [ADR-0051] | no | — | none | n/a | **forgotten** (`envconfig.py` extraction) | yes | no |
| [ADR-0052] | yes | S5,S3 | thrash-reducer follow-up "deferred" — shipped as ADR-0056 | add pointer | shipped | yes | no |
| [ADR-0053] | yes | S3,S5 | owns `classify_outcome`, which ADR-0069 **froze** — recorded only in code and ADR-0069 | add freeze amendment | shipped; **regression gate forgotten** | yes | no |
| [ADR-0054] | no | — | none | n/a | shipped | yes | no |
| [ADR-0055] | yes | S5,S1 | "a `bump_version.py` **can follow**" / "Not wired into CI yet" vs the script existing and CI job `version-record` | mark closed | shipped; 1.0 cut on roadmap | yes | no |
| [ADR-0056] | yes | S1 | "Settings page renders the dropdown automatically (no UI code)" — zero `sensitivity` hits in `apps/web`; `TESTER_FILE_CAP` absent from `.env.example` | correct both | **forgotten** (provider-aware default) | yes | no |
| [ADR-0057] | yes | S1,S4 | still lists `coverage_gap_fill`, deleted by ADR-0060; cites a line range that moved to `_oracle_legs.py`; "logged as roadmap follow-ups" — not on the roadmap | strike gap-fill; repoint | **forgotten** (mutation file-cap, `--approve-all` hook) | yes | no |
| [ADR-0058] | yes | S1,S3 | §3 describes `react_on_bad_test`/`diagnose_test_review` — **neither symbol exists**, deleted by ADR-0060 | annotate §3 DELETED | roadmap | §1/§2 yes; §3 history | no |
| [ADR-0059] | no | — | none (cosmetic `_EXEC_SESSION_LIMIT` underscore) | n/a | shipped | yes | no |
| [ADR-0060] | no | — | none — **bidirectional with ADR-0077** | n/a | (a) forgotten; (b) shipped | yes | no |
| [ADR-0061] | yes | S2,S7 | retired "`false_ship` ≈ 0" as exploitable; `roadmap.md:886` gate table still carries it verbatim | replace both cells | roadmap | yes — the release contract | no |
| [ADR-0062] | no | — | none | n/a | shipped (critic); confound on roadmap | yes | no |
| [ADR-0063] | no | — | none — explicitly direction-only | n/a | (1) shipped, (3) **partly forgotten** | yes | no |
| [ADR-0064] | no | — | none — every mechanism live | n/a | **forgotten** (scratch audit-log) | yes | no |
| [ADR-0065] | no | — | none | n/a | **forgotten** — claims "Logged on the roadmap"; no such entry | yes | no |
| [ADR-0066] | no | — | none — records its own withdrawal correctly | n/a | shipped + roadmap | yes | no |
| [ADR-0067] | no | — | none (file moved, behaviour same) | n/a | none | yes | no |
| [ADR-0068] | no | — | none | n/a | **forgotten** (ruff-style emit) | yes | no |
| [ADR-0069] | no | — | none (helper relocated to `_gate_outcomes.py`) | optional path refresh | **forgotten** (tamper-gaming catch) | yes | no |
| [ADR-0070] | yes | S2,S4 | header carries two statuses with no `Superseded by:`; body still present-tense though the code is fully removed **[verified via grep: zero hits outside docs]** | single status + successor line | roadmap | yes — the strongest negative result in the repo | no |
| [ADR-0071] | yes | S5,S1,S4 | "Measurement (DoD, **still to run**)" — ran 2026-08-02, null; header says red-team "to be run" while §Red-team says done; roadmap claims a bench lever that does not exist | record the null result | shipped (successor) | yes | no |
| [ADR-0072] | **yes** | **S1,S7** | **"posture ACTIVATED … EXPIRY review by 2026-11-02" vs WITHDRAWN the same day, n=25 null [verified]** | **add Amendment 3** | roadmap | yes | no |
| [ADR-0073] | no | — | none | n/a | **forgotten** (curate path unlinted) | yes | no |
| [ADR-0074] | yes | S3,S5 | amended by 0093/0094, no back-reference; conversion-rate hook "remains follow-up" — shipped as `mosaera-layer2-report` | add "Amended by" | shipped | yes | no |
| [ADR-0075] | yes | S1,S3 | states a literal reason allowlist; code derives it from `REASON_CLASS` (ADR-0090) after the literal went stale | annotate superseded | roadmap | yes | no |
| [ADR-0076] | no | — | none | n/a | roadmap (scan-completeness oracle) | yes — highest-priority security follow-up | no |
| [ADR-0077] | yes | S4 | `liveness.py:283` says "roadmap Open"; no such roadmap entry exists | add the item or repoint | **forgotten** | yes | no |
| [ADR-0078] | no | — | none | n/a | **forgotten** (residuals 1–3) | yes | no |
| [ADR-0079] | yes | S3,S5 | amended by 0090/0092/0095/0097, extended by 0089 — references none; under-specified case class shipped as govbench | add "Amended by" | shipped / roadmap | yes | no |
| [ADR-0080] | yes | S3,S5 | amended by ADR-0091 with no back-ref; "deterministic auto-ask … follow-up scope" shipped as `intake_ask.run_intake_pass` | add pointers | **forgotten** (`ApproveBody.answers`) | yes | no |
| [ADR-0081] | **yes** | **S1,S4** | **Decision 7 claims mechanization; `experiment_report` has zero production callers. GRANDFATHERED has never shrunk — one commit ever [verified]** | **correct D7; give the ratchet an owner** | **forgotten** (6 sentinels) | yes | no |
| [ADR-0082] | yes | S1,S5 | line 205 "§1/§5 BUILT" vs line 220 "Deliberately NOT built" — 15 lines apart | delete the stale clause | roadmap; DoD 2/3 forgotten | yes | no |
| [ADR-0083] | yes | S1 | asserts `available_cases() == 24`; the test asserts **26** | restate as a tripwire | roadmap | yes | no |
| [ADR-0084] | yes | S5 | header now accurate **[verified]**; `roadmap.md:1172-1176` still calls the design cache "a cache with no invalidation key" | mark (b) FIXED on the roadmap | roadmap | yes — (a) and (c) unbuilt | no |
| [ADR-0085] | yes | S5 | header "§2/§3 not-started" vs its own bullets + roadmap: §3's instrument shipped | restate the lead line | §2 forgotten-ish | yes — most-cited constraint in the codebase | no |
| [ADR-0086] | **yes** | **S6** | **proposes `risk-gated` as "the new default"; ADR-0101 shipped `ask/accept/auto` and never mentions it [verified]** | **supersede-and-archive; re-home §2** | **forgotten** | §2 risk list only | **yes** |
| [ADR-0087] | yes | S5 | header "§1–§4 registry BUILT"; `roadmap.md:683` says still open | correct the roadmap | roadmap (§3) | yes | no |
| [ADR-0088] | no | — | none — every clause verified | n/a | none | yes | no |
| [ADR-0089] | no | — | none | n/a | roadmap | yes | no |
| [ADR-0090] | no | — | none (review trigger has fired, unrevisited) | optional one-liner | roadmap + code | yes | no |
| [ADR-0091] | no | — | none | n/a | roadmap; cites "Alembic 0025", since taken | yes | no |
| [ADR-0092] | no | — | none | n/a | roadmap | yes | no |
| [ADR-0093] | no | — | none — verified by mechanism (file contains no ADR number) | n/a | roadmap | yes | no |
| [ADR-0094] | no | — | none | n/a | shipped | yes | no |
| [ADR-0095] | no | — | none | n/a | **forgotten** (git untracking) | yes | no |
| [ADR-0097] | yes | S5,S4,S3 | "Owed: MCB-28 executed" — ran and delivered 2026-08-11; ADR-number-collision note describes a resolved race as live | true up "Owed" | (a) shipped; (b) **forgotten** | yes | no |
| [ADR-0098] | no | — | none | n/a | none | yes | no |
| [ADR-0099] | no | — | none — unusually well-matched to code | n/a | accepted residual | yes | no |
| [ADR-0100] | yes | S5 | **reverse direction** — the ADR is right; `roadmap.md:155` still lists it as "the last blocker … current top priority" | mark DONE on the roadmap | accepted residual | yes | no |
| [ADR-0101] | no | — | none — DIRECTION items marked at the promised code site | n/a | roadmap | yes | no |
| [ADR-0102] | yes | S5 | ADR records red-team DONE; `roadmap.md:76` says "red-team: pending" | correct the roadmap | **forgotten** (3 DEFER-TO-SUCCESSOR items called "tracked") | yes | no |
| [ADR-0103] | yes | S5,S1 | §Deferred rests on "cherry-pick/rebase primitives that do not exist" — `tools/repo/cherry.py` exists | mark closed | shipped / roadmap | yes | no |
| [ADR-0104] | **yes** | **S2,S7** | **README "ENV-only" vs `encrypt_secret` in code vs the ADR's own reversed alternative [verified]** | **fix README, roadmap, and the alternative** | roadmap (live round-trip owed) | yes | no |

## Worth doing now — ranked

Already-decided work, unbuilt, that pays off at the current stage.

1. **PII/secret redaction on `run_events` (ADR-0006).** The ADR names secret leakage into the
   transcript as *"the load-bearing risk"*. The store is durable and exportable via
   `GET /api/runs/{id}/transcript`, and no redaction exists on that path.
   `packages/connectors/mosaera_connectors/redact.py` already scrubs credentials and can be reused
   at the `_emit` seam. Security-relevant, cheap, forgotten by both roadmap and ADR.
2. **Bidirectional supersession back-links (corpus-wide).** 29 links, all one-directional. The
   forward links already exist, so the back-links are **derivable** — a `check_doc_claims.py`
   contradiction check ("A says it supersedes B; B does not acknowledge A") rather than a field
   anyone maintains. Highest-leverage single fix in this review.
3. **Delete-or-wire the dead semantic recall (ADR-0008, ADR-0011).** `similar_doctrine()` and
   `similar_artifacts()` have zero call sites **[verified]**, and `persist.py` pays embedding cost
   on every artifact write for a retrieval path with no consumer. The roadmap proposes deleting the
   very seam ADR-0008 laid "wired later" — decide it explicitly.
4. **The six C3/C4 liveness sentinels (ADR-0081).** The ratchet has not moved since the day it
   landed. For a product whose thesis is that controls must be proven able to fire, six posture
   knobs sitting at C2 with no sentinel is the most on-brand debt in the repo.
5. **Live-path escalation no-op detector (ADR-0016 Amendment 1).** The detector is written; it
   needs the escalated role threaded into the run session. The bench measured 45 of 61 escalations
   making zero model calls — on the live path that silently corrupts run history.
6. **Realign the bench capability taxonomy (ADR-0007, ADR-0083).** `_CAPABILITY_ORDER` lists five
   capabilities; MCB-27/28 declare `subtract`/`modify`, so they fall outside the rollup matrix and
   the case-count assertion reads 24 against 26 actual.
7. **Reconcile the v1.0 gate-2 wording (ADR-0061).** The roadmap's gate table quotes the threshold
   the ADR retired **as exploitable**. The project's definition of done should have one authority.

## Archive candidates

**ADR-0086** only. Supersede-and-archive into `docs/archive/`, re-homing §2's risky-write list.
Immutability is respected: the record is superseded, not deleted.

Corpus size (101 vs the ~50 the research calls a liability) is real, but this review found no other
ADR safe to retire — 45 are clean and current, and the stale 56 are overwhelmingly *live decisions
with lagging records*, not dead ones. **The corpus is not bloated with dead decisions; it is
accurate code with trailing documentation.** Deletion is not the lever here.

## Candidate `check_doc_claims.py` contradiction checks

Each compares two facts already in the repo — no new metadata, nothing a reviewer can rubber-stamp.

1. **Bidirectional supersession** — if A's header claims supersede/amend of B, B must mention A.
   Would fire 29 times today.
2. **Alembic head references** — a doc citing "head `NNNN`" must match the highest migration on
   disk. Would have caught ADR-0001.
3. **Named symbol existence** — an ADR asserting a knob/function by name (`react_on_bad_test`,
   `coverage_gap_fill`, `risk_gated`) must find it in code, or carry a deletion note. Would have
   caught ADR-0057, ADR-0058, ADR-0086.
4. **`GRANDFATHERED`/ratchet drift** — any list documented as "may only shrink" that has not
   shrunk in N days is reported (report-only, not a failure).
5. **Self-contradiction within one ADR** — "BUILT" and "NOT built" about the same section.
   Would have caught ADR-0082 and ADR-0047.

## Method limits

- Ten agents read the ADRs; every S1 quoted here was re-checked by hand against the named file
  before inclusion, and the ones marked **[verified]** were confirmed by me directly.
- `useful_now` and `archive_candidate` are judgement, not measurement.
- Two batch-reported claims were corrected during synthesis: `check_doc_claims.py`'s assertion
  about ADR-0077, and this review's own framing of ADR-0084's `proposed`+shipped state — which
  `ADR-0000-template.md:12-14` explicitly permits by separating decision state from build state.
  That is an unratified-decision governance question, not staleness.
- The review did not open every file every ADR names; unverifiable claims were recorded as
  "unverified" by the readers rather than asserted.

---

# Remediation — applied 2026-08-18

All findings above were fixed the same day. This section records what changed, so the table reads as
history rather than as an open list.

## What was applied

| Fix | Result |
|---|---|
| Supersession back-links | **29 → 0** one-directional links. 32 back-links written across 20 ADRs |
| Severe self-contradictions | ADR-0047, 0072, 0104, 0082, 0058, 0026 corrected in place |
| Archive | ADR-0086 superseded by ADR-0101, §2's risky-write list preserved |
| Shipped-but-listed-as-deferred (S5) | ~25 ADRs trued up with the evidence path |
| Wrong facts (S1) | Alembic head, knob counts, `pm_step_limit`, case counts, file paths |
| Wrong references (S4) | ADR-0042's ADR-0036 mis-citation, ADR-0003's phantom roadmap `#23` |
| Roadmap / README | 6 roadmap corrections, 2 README corrections |

## The editing rule used throughout

**No claim was silently deleted.** Every false statement is struck through with `~~…~~`, kept
readable, and followed by a dated correction citing this audit and the evidence path. The record
shows what it used to say and why it moved — which is the property that makes an ADR worth keeping
after the decision has aged.

Two things were deliberately *not* rewritten:
- **ADR-0072's Amendment 1** (the n=3 activation) stands as written. Amendment 3 refutes its
  efficacy tables but not its soundness argument. Deleting it would erase the more useful lesson: an
  activation on n=3 that failed to replicate at n=25.
- **ADR-0086's decision body** is byte-identical. It is superseded, not deleted, per the README rule.

## Corrections to this audit, found while remediating

1. **The back-links were not as derivable as §"Corpus-wide findings" claimed.** The `Amends:` field
   is prose mixing relationship verbs — `Amends: [A] (…); references [B] / [C] (deliberately
   preserved), [D]` — so a naive parser produces false links. The applied pass parses clause by
   clause, demoting after `references` / `relates` / `depends on` / `constrains`, and scopes to
   header fields only (body prose produced seven false positives). A `check_doc_claims.py` rule must
   use the same discipline; the "just derive it" framing above was too optimistic.
2. **ADR-0077 does use template fields.** `scripts/check_doc_claims.py` asserts it "uses none of the
   template's field names"; it carries `Status`, `Date`, `Owners`, `Related issue`. That guard
   docstring now contains its second self-contradicted claim (the first, "wired into nothing", is
   recorded in the docstring itself). Not fixed here — it is a code change.
3. **ADR-0084 `proposed` + shipped code is not staleness.** `ADR-0000-template.md` separates decision
   state from build state explicitly. It is an unratified-decision governance question — shipped code
   and a migration governed by a decision never formally accepted — and it is the owner's call.

## Code-side remainder — CLOSED 2026-08-20 (branch `fix/adr-code-remainder`)

All nine deferred code items below were fixed on 2026-08-20 in an isolated worktree. Same
discipline: correct in place, cite the evidence, say what the comment used to claim where that
history is load-bearing.

| Item | Was | Now |
|---|---|---|
| `app.py` `guard_bind` docstring | "a host passed only via `uvicorn --host` … is invisible to the app" | states the caller passes `_cli_bind_host() or MOSAERA_API_HOST`; keeps the real residual (gunicorn config-FILE `bind`) |
| `graph/build.py` | "the default (ceiling 12) is exactly the previous 150" | **160** — verified by executing `recursion_limit_for(Settings())` |
| `oraclefit.py` ×2 | cited ADR-0086's posture as live | scoped to §2's risky-write list, noting the posture is superseded by ADR-0101 and §2 is not |
| `models_chat.py`, `store/_sessions.py`, `0013_pm_sessions.py` | credited ADR-0045 | credit **ADR-0048**; ADR-0045 remains only as corrected history |
| `bench/liveness.py` | cited "roadmap Open" — no such entry | points at ADR-0077's last Definition-of-done checkbox |
| `check_doc_claims.py` | "ADR-0077 uses none of the template's field names" | describes the real split (89 `- Status:` / 12 `- **Status:**`) |
| `bench/suite.py` | `_CAPABILITY_ORDER` had 5 of 7 capabilities | adds `modify`/`subtract` |
| `.env.example` | `MOSAERA_TESTER_FILE_CAP` undocumented | documented at its real default, `10` |

**Correction to this audit.** The `_CAPABILITY_ORDER` entry above previously said MCB-27/28 "fall
outside the matrix columns". They did not. `_ordered()` returns `known + sorted(present - set(order))`
— unknown capabilities are **appended, not dropped**, so they appeared in the rollup but sorted last.
Canonical ordering, not data loss.

Two things caught during the fix, worth recording because both are the failure mode this audit is
about: `.env.example`'s new line was first written with default `8` when the knob's real default is
`10` (caught by cross-checking every documented value against `GENERAL_KNOBS`), and the `build.py`
figure was confirmed by *running* `recursion_limit_for` rather than by reading the formula.

## Still open — beyond this review's scope

- **Code comments** carrying stale claims: `apps/api/mosaera_api/app.py` (`guard_bind` docstring),
  `graph/build.py` (recursion-limit comment), `oraclefit.py` (cites superseded ADR-0086),
  `bench/liveness.py` ("roadmap Open" pointing at a nonexistent item), `bench/suite.py`
  (`_CAPABILITY_ORDER` missing `modify`/`subtract`), and `check_doc_claims.py`'s ADR-0077 claim.
  These are code changes needing their own review, not a docs pass.
- **Four ADR-0045 mis-citations in code** (`0013_pm_sessions.py`, `models_chat.py`,
  `store/_sessions.py`) — PM sessions are ADR-0048's decision. The roadmap half is fixed.
- **`.env.example`** is missing `MOSAERA_TESTER_FILE_CAP`.
- **The seven ranked "worth doing now" items** above are unbuilt work, not documentation defects.
