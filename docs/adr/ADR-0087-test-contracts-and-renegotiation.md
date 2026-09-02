# ADR-0087: Delivered tests are amendable contracts — the engine must be able to change its mind

- Status: proposed
- Implementation: **§5 BUILT 2026-08-06 (write-gate half) and 2026-08-07 (escalation-gate half,
  with §6, MEASURED LIVE); §1–§4 registry BUILT 2026-08-07; §3's impossibility proof not-started**
  - **What landed.** A write a HUMAN approves at the write gate now records the resulting content's
    integrity hash into `operator_edits`, and `tampered_integrity` reads it as a **second sanctioned
    source** beside `proctor_edits` — same hash space, same content-pinned rule. The operator's
    authorization stops being prose and becomes a fact the deterministic guard sees. Issue
    #65 (F63).
  - **Why this slice first.** It required no new artifact: `proctor_edits` (ADR-0058) already was
    *"the ONE sanctioned way a BASELINED path may change"*, red-teamed and content-pinned. The
    approval decision already existed at a point where the content was known. The gap was only that
    the two never met.
  - **The load-bearing constraint** is `decision.actor == "human"`. An autonomous auto-approve that
    could sanction its own writes would retire ADR-0036 in silence. Pinned by a test that asserts
    an `autonomous` actor sanctions **nothing**.
  - **NOT built as of that slice:** the contract/ownership model (§1–§4), Proctor-owned
    amendments, the anti-laundering evidence test, and the escalation-gate case where an operator
    authorizes an edit the producer has not yet written (no content exists to pin). *The
    escalation-gate case and the weakening measure landed 2026-08-07 — see below.*
  - **RED TEAM DONE — 3 rounds, 2 FIX-NOW (both fixed pre-merge), no repeated defect class.**
    - *Round 1, authority:* `autonomous`, `unknown`, empty, `HUMAN` (case) and `human-ish`
      (prefix) all refused; only an exact `human` actor sanctions. No finding.
    - *Round 2, content:* **FIX-NOW ×2.** (a) A human could sanction a **collection-control**
      file — a `collect_ignore` or `addopts=--ignore` drops requirements wholesale exactly as
      emptying a test does, and is *worse* to review because the effect is invisible in any test
      file. Operator sanctions are now excluded for conftest/pytest-config paths by
      `_is_collection_control`. (b) The **tester's** toolset held the sanction sink, so a
      human-approved tester overwrite of a baselined test reopened the manufacture-a-green-suite
      move. The sink is now the coder's alone; the Proctor's sanctioned route stays
      `proctor_edits`, which is coder-blind and gated on the assertion floor + a proven mutation
      catch.
    - *Round 3, scope/persistence:* a later silent write at a sanctioned path still trips
      (content-pinned); a human-approved **delete** sanctions nothing and still trips; a sanction
      on one path does not excuse another; `edit_file` records correctly. No finding.
  - **Residual, stated deliberately:** a human can now authorize a *weakening*. That is their
    authority, and it is the point — but it makes
    #66 (assertion count must not
    decrease) *more* important, not less: the operator should be told what they are approving.
  - **2026-08-07 — the ESCALATION-GATE half, plus §6.** The write-gate slice below could only
    sanction content that already existed. The blocking case is the opposite: at the escalation the
    operator authorizes a change the producer has not written yet, so there is nothing to pin.
    Issue #65 (F63) /
    #66 (F59).
    - **The defect was smaller than it looked.** `supervise_node` ORs an oracle conflict straight
      into `give_up`, so the ESCALATE arm asked the operator and then concluded the run *whatever
      they answered*. The authorization was not merely unenforceable — it was unread.
    - **§2 is implemented as Proctor-under-human-authorization, not as either alone.** The
      operator authorizes a SCOPE; the **Proctor** produces the CONTENT; the result lands in
      `proctor_edits` and the EXISTING content-pinned rule excuses it. So `tampered_integrity`
      gained no parameter and `packages/policies` was not touched. Releasing the path to the coder
      instead would have been the producer rewriting the test that judges it — the mirror image of
      this ADR's own round-2 finding, with a weaker pin.
    - **§6 built (`assertion_profile` / `profile_regression`).** Weakening is measured per test
      function and one-sided. The assertion floor could not stand in: it is `any()` over a file, so
      dropping seven of eight tests clears it while one real assertion survives. Wired by
      AUTHORITY — the unattended paths (the Proctor's repair, the amendment) REFUSE the excuse on a
      loss; the write gate, where a human is reading the diff, ANNOUNCES it and honours the
      decision. That asymmetry is deliberate: refusing an approval a human just reviewed would
      rebuild the deadlock this ADR exists to dissolve.
    - **Coder-blindness is CONSTRUCTIONAL here, not temporal.** The implementation exists on disk
      by escalation time, so `_proctor_validate_repair`'s `iteration <= 1` trick is unavailable.
      The amend ask is assembled from task/plan/design/criterion + the operator's reason and never
      from `diff`, `coder_summary`, `test_output` or `escalate_reason` — asserted directly against
      the built string. **This is weaker than temporal blindness and is a named residual.**
    - **One-shot and self-consuming.** Path-scoped, content-unpinned authorization is the weakest
      excuse in the system, so it is consumed into `proctor_edits` and cleared in the same node
      return. No fix iteration, gate-deny re-plan or rehydrate replays it; a second amendment needs
      a second escalation and a second human.
    - Knob `amendment_gate`, **default OFF** (the `escalate_arm` precedent). `tester_enabled` off
      ⇒ no non-producer amender ⇒ fails closed.
    - **RED TEAM DONE — 3 rounds, 2 FIX-NOW (both fixed pre-merge), no repeated defect class.**
      - *R1, authority:* `HUMAN` (case), `human_park` (prefix), whitespace, `rescope`, absent,
        `stop`, `give_up`, and a non-list payload all authorize nothing. No finding.
      - *R2, scope:* **FIX-NOW.** The authorization is granted per node id but the tamper guard
        works per FILE, and the first implementation reduced node ids to paths on the way in —
        so ticking ONE failing test authorized weakening EVERY failing test in that file. Node ids
        are now preserved end-to-end, and only the functions the operator actually chose may lose
        assertions. A bare path falls back to the tests that were *failing* there, never to
        "anything in this file" (a passing test was never in the way).
      - *R3, persistence:* **FIX-NOW.** `Settings.from_env` re-reads per run, so a park that
        outlived a settings change could resume with the knob OFF and a live authorization in
        checkpointed state. The consumption point now re-checks the knob and CLEARS the licence
        rather than holding it. Otherwise clean: re-entry after consumption grants nothing, a
        rehydrate replays only the content pin, and a later different content at an amended path
        still trips.
    - **Residuals, stated deliberately:**
      - **Semantic weakening at constant assertion count** (`== Decimal("42")` → `== compute()`)
        is invisible to §6. Inherited from the assertion floor's accepted #67 residual, which
        ADR-0085 freezes. Backstop: a run with non-empty `proctor_edits` already vouches only on a
        **proven** mutation catch, never on an unmeasured one.
      - **§3's real teeth are NOT built.** The owner does not independently establish that *no
        correct implementation could satisfy this test*; the human's authorization stands in for
        that proof. This is the single largest gap and it deserves its own issue.
      - A **first-iteration hand-raise cannot reach the amendment gate**: `blocking_protected_tests`
        parses the previous iteration's `test_output`, so a run that has not validated yet has no
        blocking set (the #68 split-evaluation defect, from the other side).
        **CLOSED 2026-08-07 — see the entry below.** Stating it here was not enough: it was
        re-derived from scratch three weeks later, after it had already cost two live runs.
  - **2026-08-07 — §5 covers BOTH origins its own offer accepts (#76, F71).**
    Measured live on run `20260807-204815-c76f7b`, minutes after #75 made the offer fire: the
    operator authorized, the Proctor wrote the content, and the run ended `incomplete` on
    *"pre-existing/protected tests … were modified"* with `proctor_edits: {}` and
    `amended_tests: []`. **The offer and the consumption disagreed about what may be amended.**
    `blocking_protected_tests` deliberately offers a baselined path OR one the Proctor authored
    THIS run; every consumption mechanism handled only `integrity_baseline`. Two independent
    blockers: `baseline_test_sources` read one baseline, so `_weakens` returned its
    *"no pristine source"* sentinel and every same-run path was silently `continue`d; and
    `tampered_files(tests_baseline)` takes **no excuse parameter at all** and hashes in a different
    space (raw bytes) from `proctor_edits` (integrity hashes), so an excuse for one is invisible to
    the other.
    - **§5 was therefore non-functional for one of its two origins, and #87's success does not
      generalise** — it happened to amend a test delivered by an EARLIER item, which lands in
      `integrity_baseline`. All 15 existing tests snapshot the file into that baseline first, so
      100% of coverage was the inherited origin. Same lesson as F70 one layer along: the untested
      case was not an edge, it was half the feature.
    - **Fix.** One pre-amendment source covering both origins (the text is on disk either way, so
      §6's assertion-profile guarantee is preserved in full, not relaxed); the unchanged-check
      selects the baseline by origin; the result is recorded in **both** hash spaces, so each guard
      sees the sanctioned change through the channel it already reads. A path pinned in both is
      recorded in both — never in whichever is convenient. `tampered_files` is deliberately NOT
      given an excuse parameter: #75's red team showed that widening a shared helper leaks into the
      arm that ships.
    - **Narrowing the offer was rejected**: the close-the-gap arm is the designed remedy for
      engine-authored trapping tests and explicitly excludes coder hand-raises (pinned by
      `test_the_two_arms_do_not_both_claim_the_same_run`), so this case has no other mechanism.
    - **No refusal is silent any more.** Every rejection returns its reason
      (`amendment_refusals`, declared state) and it reaches the gate payload and the panel. This is
      the fourth instance of one class — F61's button, F65's vanished offer, F69's placeholder,
      F71's refusal — **a control that offers or declines invisibly**. The generalized rule this
      repo should now hold: *a deny-by-default branch must record why it denied; silence is
      indistinguishable from absence.*
    - **RED TEAM — 3 rounds complete. 2 FIX-NOW, both fixed pre-merge, and both were caused by
      the widening itself rather than by the original mechanism.**
      - **R2, FIX-NOW — the registry would have recorded the amendment as a lie.** A path the
        Proctor both AUTHORED and AMENDED this run is new to the project: version 1, a delivery.
        `_write_contracts` keyed `is_amendment` on membership in `amended_tests` alone, so it would
        have written provenance `amended` — claiming a prior version that was never delivered — and
        with an **EMPTY content hash**, because `proctor_edits` only ever holds baselined paths.
        Item 88 produces exactly this shape, so this would have corrupted the registry's first real
        rows on the very next delivery. Now: an amendment must also be baselined, and the content
        hash comes from whichever space pinned it.
      - **R3, FIX-NOW — the widening had quietly weakened the oracle.** The delivery gate tightens
        its vouch for a run whose tests were edited (proven mutation catch, never unmeasured) —
        the rule THIS ADR names as the backstop for its accepted semantic-weakening residual. It
        keyed on `proctor_edits`, which a same-run amendment does not write, so exactly the runs
        whose acceptance bar had just been renegotiated fell back to the looser rule. The predicate
        is now `sanctioned_test_edit(state)`, covering every sanctioned route, and the gate consumes
        it rather than re-deriving it.
      - The lesson across both: extending a control to a second origin does not inherit that
        control's downstream guarantees. Everything keyed on the FIRST origin's storage — the
        registry's provenance, the oracle's tightening — silently excluded the new one.
      **ACCEPT (R1):** with a BARE-PATH authorization, `amended_functions` falls back to the failing
      tests at that path, and since #75 that set can come from the coder's own (tree-hash-pinned)
      run — so a producer that makes additional tests at the path fail widens what may be weakened.
      This is #75's R3 residual reached by a new route (a producer breaking the product to fail a
      protected test), not a new capability; the UI emits node ids, which bypass the fallback
      entirely. **Pinned:** a path in both baselines is excused in both; a path in neither sanctions
      nothing and says so; the collateral, assertion-floor, unchanged and one-shot rules all bite
      identically on the new origin.
  - **2026-08-07 — the offer gets evidence on the branch it actually fires on (#75, F70).**
    The residual above stopped being theoretical: LedgerCLI item 88 hit it twice (runs
    `20260807-194739-644d8f`, `20260807-195038-936bdf`) with the coder stating in its own words
    that a Proctor-authored test it may not edit was blocking it, and the escalation carried **no
    `amendable` key at all**. The item cannot deliver; the control was, on that branch, absent.
    - **The cause is a branch, not a bug in the predicate.** A hand-raise routes
      `implement → capture → supervise` (`route_after_capture`) and never passes through `test`,
      the only writer of `test_output`. The *protected* half of the subset check was correct and
      populated the whole time; the *failing* half was empty, so deny-by-default withheld the
      offer — silently, and looking exactly like correct behaviour. That is why a 3-round red team
      missed it, and why every fixture in `test_amendment_gate.py`, `test_escalate_arm.py` and
      `test_graph_build.py` hardcoding `test_output` was the real defect: **nothing tested the
      absence.**
    - **The fix reuses evidence that already existed.** `run_tests` takes no arguments, resolves
      the plan through the engine's own `resolve_plan` and runs it in the sandbox, so the producer
      chooses only WHEN it runs — never what runs, never what comes back. Its output is recorded
      into a shared sink (the third, alongside `protected_tests` and `operator_sanctioned`),
      **pinned to `workspace.evidence_hash()`** (was `tree_hash()` until ADR-0108's successor,
      `f0666bfa`), and persisted by `capture_node` into the declared
      `coder_test_output` channel. A tree that moved after the run ⇒ `""` ⇒ no fallback ⇒ no
      offer. The pin is the whole warrant: without it a coder could run the suite, then write, then
      raise its hand, and hand the gate a description of a tree that no longer exists.
    - **One reader, not two.** `effective_test_output(state)` is consumed by both
      `_failing_test_files` and `blocking_test_ids`; a second copy of *"which output counts?"* is
      the drift that puts a control and its operator surface out of step. `test_output` always
      wins — the fallback covers an absence and never overrides a real validation. Pinned on the
      conflicting case, not the agreeing one.
    - **Why NOT `capture → test → supervise`,** the obvious alternative: it creates the first path
      on which a give-up reaches the gate with `tests_passed=True`, where `_resolve` can reduce the
      reasons to `["reviewer_unknown"]` and **auto-approve delivery for a run whose producer said
      it was blocked**. Closing that needs a `packages/policies` edit, plus a full sandbox
      validation per hand-raise and convergence-bookkeeping pollution. Strictly worse.
    - **A fifth deny-by-default rule joins §5's four:** the offer is withheld outright when
      `tests_modified` is set. `blocking_protected_tests` never checked it (only
      `is_oracle_conflict_escalation` did), so a run that weakened a protected test could be handed
      authorization to amend one — the gate laundering the thing it exists to prevent. Reachable
      before this change via `hygiene_fix → implement → capture → supervise` carrying a stale flag.
      The suppression is now **stated in the payload** (`amendable_withheld`) rather than showing
      the operator nothing, which is F65's actual complaint.
    - **Unchanged:** `packages/policies`, the gate contract, and all graph routing. The operator
      still authorizes a scope, the Proctor still writes the content, the coder never gets the path.
    - **RED TEAM, 1 verification pass** (scoped: a bounded successor to §5's 3 rounds). Question
      asked: *can a producer manufacture or stale-replay a `coder_test_output` that authorizes
      amending a test that is not actually blocking it?*
      - **R1, FIX-NOW, fixed pre-merge — the SHIPPING arm inherited the fallback.**
        `trapping_engine_tests` (the close-the-gap arm, which retracts tests and **delivers**)
        shares `_failing_test_files` with the escalate arm, so routing the fallback through that
        helper silently handed producer-timed evidence to the one arm whose output is a commit.
        The fallback was argued for the arm that STOPS and asks a human. `_failing_test_files` now
        takes its source as an explicit argument defaulting to the narrow one, and only the
        escalate arm names the wider source. Pinned both ways.
      - **R2, ACCEPT (documented, inherited).** `tree_hash` is stat-only (`path,size,mtime_ns`)
        and capped at 300 listed files, so in principle a same-size, mtime-restored, or
        beyond-the-cap write could leave the pin satisfied. The coder's write tools cannot set
        mtime and arbitrary exec is knob-gated (`coder_repl_enabled`); more to the point this is
        the engine's existing memo key for the validation plan, mutation check and coverage runs,
        so the amendment gate inherits an established trust assumption rather than inventing one.
        Strengthening `tree_hash` would improve all of them together.
      - **R3, PRE-EXISTING, not introduced.** A producer can break the product so a protected test
        fails, then hand-raise, and the offer is legitimately made. Identical on today's
        `test → supervise` path — the failing-set-⊆-protected rule never asked *why* a test fails.
        Mitigated where it always was: the human reads the criterion and the test, the Proctor
        writes the content, and the assertion floor refuses a weakening.
    - **Not fixed:** #68's split evaluation (the two points can still disagree once state evolves,
      and the gate-reasons half still passes trivially at supervise time), and §3's impossibility
      proof.
  - **2026-08-07 — §1–§4, the contract registry.** `test_contracts` (migration 0024): one
    append-only versioned row per `(project_id, path, version)`. Version 1 is a delivery, N+1 an
    amendment, and **the version history IS the amendment record** §4 asks for — a second table
    would duplicate the key and let the two drift.
    - **Why it was needed, precisely.** Project item runs share ONE long-lived clone, so a test
      delivered by item N lands in item N+1's `integrity_baseline` indistinguishable from a
      human's. `disposition.py` calls every baselined path *"a HUMAN/baselined test"* — a statement
      that is simply FALSE on a project's fourth item, and there was nowhere else to learn
      otherwise.
    - **The load-bearing rule is NEVER INVENT OWNERSHIP.** Rows exist only for paths a run
      demonstrably authored or amended. A baselined path with no row means *we do not know who
      wrote it* — the truth for every human-authored test in a brownfield repo — and the operator
      surface shows nothing rather than attributing the bar to whichever item last touched the
      file. Pinned by a test; there is deliberately no `pre_existing` provenance value, because a
      label invites a future writer to stamp it on a guess.
    - **Written** in `persist_run` on a REAL delivery only (`approved` + a commit + a project);
      **read once**, in `supervise_node`, to annotate the amendment offer with the owning item,
      the version, and whether the bar has been renegotiated before. The read degrades to absent
      on ANY failure: a run that cannot park because a lookup broke is worse than one that parks
      with less context.
    - An amendment **inherits the origin owner** when the caller supplies none — an amendment
      changes a bar's content, not whose bar it is, and losing that blanks the one fact
      (*"authored for item #42"*) the operator most needs at the moment they are asked to judge it.
    - Re-delivering identical content records **no** new version, or the history fills with noise
      and *"how often is this bar amended?"* — the question this ADR's Consequences section wants
      answered — becomes unanswerable.
    - **F66 fixed on the way past:** `amendment_offer` AND `amendment_instruction` both read
      `state["acceptance"]`, which is not a RunState key. The offer's criterion had been empty on
      its first live firing, and the Proctor's amend ask had been carrying an empty *"Acceptance
      criteria"* section — it was told to amend a test to match a requirement it was never shown.
      Both now read `claims`, which is where the acceptance actually lives. A pre-existing test had
      masked this by inventing the key in its fixture: it pinned a fiction and passed.
    - **NOT built:** §3's impossibility proof (the owner independently establishing that *no
      correct implementation could satisfy this test*). The human's authorization still stands in
      for it, as recorded above.
- Date accepted:
- Owners: @rengi
- Related issue / MR: #65 (F63, the blocking case) · #66 (F59/F35, weakening ships) · **#54 (a Quincy-owned test-steward — this ADR is the authority model that issue needs)** · operator session 2026-08-06
- Supersedes / Superseded by: — (extends [ADR-0036](ADR-0036-test-integrity-baseline.md); constrained by [ADR-0013](ADR-0013-adding-an-agent.md)/[ADR-0058](ADR-0058-proctor-validates-repairs-tests.md))
- Related threat model: [TM-0001](../threat-models/TM-0001-mosaera-lite-repo-agent.md) — **an amendment path is a new surface on the oracle-authoring boundary and needs its own entry**
- Review trigger: a second item deadlocks on a delivered test, or the plumbing work this depends on lands

**Decision summary:** A delivered test is currently a permanent, unamendable assertion, so **the engine
can only add — it can never change its mind.** Any work that alters behaviour deadlocks against the
tests that encode the old behaviour. Make delivered tests **versioned contracts with owners**, and
define a recorded **amendment protocol** by which the bar's owner may change it on evidence, with
human authority expressed as an artifact rather than as prose. **Proposed only — this authorizes no
build** (`DIRECTION is not authorization`).

## Context

### The add-only ceiling, observed

LedgerCLI hit it at **item four**. Item #87 is a five-line deletion in `cli.py`. It took three runs
and ~4M tokens and never shipped. Nothing malfunctioned:

- the producer made the correct fix and hand-raised that a pre-existing test now contradicted it;
- the tamper guard correctly blocked an edit to a protected test;
- the delivery gate correctly refused to ship failing tests;
- the escalation correctly reached the operator.

Every control was locally right, and the honest work could not complete. The item's *purpose* was to
change behaviour, which necessarily invalidates the test encoding the old behaviour — a trap no
single control can see.

This is not an edge case. It is refactoring, deprecation, correcting an earlier misunderstanding, and
responding to a changed requirement. A codebase that can only accrete has a lifespan.

### The rigidity is in permissions, not control flow

Worth stating because it is the natural misdiagnosis. The run graph re-routed constantly through the
2026-08-06 session — fix loops, review send-backs, hygiene, escalation re-scoping. **Not one failure
was "the topology could not get there."** What cannot move is *who may change what*: the Proctor owns
the bar, the coder may not touch it, and there is no path for the bar itself to change.

Rebuilding the engine as a freer loop while keeping this permission model would reproduce every
deadlock with less auditability.

### The guard protects a file, not a contract

- Run `20260806-215759-0ba3b2` **deleted** `assert len(lines) == 2` from a delivered test → **shipped**.
- Run `20260806-232524-3a6733` **restored** it under explicit operator authorization → **blocked**.

The tamper guard detects *edits to a baselined path*. It missed the dishonest change and caught the
honest one, because "was this a weakening?" is a different question from "was this touched?".

### Human authority has no artifact

At the escalation gate the operator wrote *"You are AUTHORIZED to update that test — this is a
requirement change I own."* It went nowhere: the authorization lived in a feedback string handed to
the producer, and the deterministic guard that blocks delivery never sees it.

The North Star holds that decisions and evidence are **versioned artifacts**. Operator authorization
is not one. As long as human authority is prose, any control strict enough to be useful is also
strict enough to deadlock honest work.

## Decision (proposed)

1. **A delivered test is a contract**, not a file: an owner, a version, and the criterion it binds.
   Locked at delivery — a later run cannot silently edit it out, which is the F59/#66 hole.

2. **The bar's owner amends the bar.** When the producer proves it cannot satisfy a test, the natural
   resolver is the **Proctor**, not the human. This is the authority model #54's
   test-steward needs.

3. **Anti-laundering is the load-bearing constraint.** The coder must never change the bar through a
   proxy. An amendment requires the owner to independently establish that **no correct implementation
   could satisfy the test** — a checkable property (run the bar against a reference or the empty
   tree), not "the coder says it's wrong". Separation of duties (ADR-0013/0058) survives intact.

4. **An amendment is a requirement change, recorded as such** — its own artifact, distinct from a
   test fix, carrying who authorized it and on what evidence.

5. **Operator authorization becomes that artifact**, per-item and file-scoped, which the tamper guard
   **reads**. An intended change proceeds; an unauthorized edit still fails closed. This is the F63
   fix, and it dissolves rather than patches the deadlock.

6. **Weakening is measured, not inferred from the path.** Assertion count per test function, before
   vs after, is the property the guard should test.

## Consequences

- ADR-0036's protection stays and gains a legitimate release valve. F59 is exactly why it must stay.
- The engine gains the ability to refactor and deprecate — a precondition for long-lived projects.
- Amendment records give trust somewhere to accumulate: how often an owner amends, how often an
  amendment later proves wrong. **Granting more autonomy becomes an argument from evidence rather
  than a guess** — the honest version of "checks and balances earn freedom".
- New abuse surface: an amendment path is a way to weaken a bar with paperwork. TM-0001 needs an
  entry, and this carries a **red-team pass** before any build.

## Sequencing — deliberately after the plumbing

The 2026-08-06 lessons are explicit that the substrate is not yet steady: deny means three different
things (#69), the per-run budget default cannot finish a real item (F56), the PM invents formats it
never read (#70). Debugging a novel authority model on top of that hides which layer is lying.

**Do the plumbing first.** This ADR exists so the direction is recorded and findable, not so it is
built next.

## What this does NOT decide

- Whether the Proctor, Quincy, or a distinct steward role owns the contract (see #54).
- The storage shape of a contract or an amendment.
- Whether amendments require human co-signature at every posture, or only below some rung
  (interacts with [ADR-0086](ADR-0086-approval-posture-ladder.md)).
- Anything about control-flow topology. The graph is not the problem.


## Amendment 2026-08-28 — the one-shot rule did not hold in guided mode (#127)

**Rule 2 of the design ("one-shot, self-consuming") was correct as written and never executed on the
operator-facing path.** Found by running the F63 task live rather than by a test.

`consume_amendment` sits above `author_tests_node`'s run-once guard and *instead* of it, and clears
`pending_amendment` in its own return. It calls the Proctor first, and in **guided mode the Proctor's
file writes gate** — the interrupt fires *inside* the node, so the node never returns, the clear
never commits, and LangGraph replays the node from the top with the authorization still standing.
This is **F35's mechanism** (documented in `_proctor_authoring.py`, sixty lines below the function it
broke), and it is guided-mode only: MCB has never had write gates (`bench/operator.py` passes
`approve_writes=False`), so the benchmark could not see it.

Measured live on LedgerCLI, run `20260828-202022-5a07ae`: the same paths re-amended round after
round, `iteration` frozen at 4, **1.29M → 1.82M tokens on a one-line change**, never delivered.

**Two consequences, the second worse than the first.**

1. *Unbounded re-asking.* Every operator approval bought one more full Proctor pass over the same
   authorized set.
2. *A laundering route.* `proctor_amend` re-read the pristine sources from **disk** at the top of its
   own pass (the baselines keep hashes, not text). On a replay that read already contained the
   previous amendment, so the collateral-damage rule — *"any test function REMOVED or SHRUNK that the
   operator did not name is refused"* — was measured against the previous amendment instead of the
   original. A removal the operator never authorized could therefore be sanctioned across rounds.
   **Demonstrated, not inferred:** with the fix reverted, the new tripwire test shows the
   unauthorized removal landing in `proctor_edits`.

**The fix, in the same shape F35 used — anchor to something that survives a replay.**

- `amendment_before_sources` (new `RunState` key) captures the authorized paths' pristine text at
  `amendment_delta`, which is a return that **commits**. `proctor_amend` reads it instead of disk.
  The disk read survives only as a fallback for a run authorized before the key existed.
- `proctor_amend` asks the Proctor only for paths that do **not** yet differ from their baseline. A
  path written by an earlier replay is dropped from the ask and still **validated**. Each replay
  therefore asks for strictly less, and the pass terminates: no writes left ⇒ no gate ⇒ the node
  returns ⇒ the one-shot clear finally commits.

**Nothing about the authority model changes.** The operator still authorizes a scope, the Proctor
still produces the content, the result is still content-pinned in `proctor_edits`, and
`packages/policies` is still untouched. The authorized set never widens — what was unbounded was the
number of attempts inside it.

**Testing note, recorded because it is the reusable lesson.**
`test_the_authorization_is_one_shot` asserted `out["pending_amendment"] == []` — the *return value*.
That assertion was true, is still true, and proved only that the clear is **written**, never that it
**commits**. A control whose failure mode is "the node never returns" cannot be pinned by a test that
calls the function and inspects what it returned. The two new tests drive the replay instead, and
both were confirmed to fail with the fix reverted.

**Residual.** Both fixes are keyed to the *authorization*, so a run parked before this change
rehydrates without `amendment_before_sources` and falls back to the disk read — the pre-fix
behaviour, for those runs only.


## Red-team round, 2026-08-28 — scoped to #127's own fix

Target: the fix in `18e0ebce` (the anchored pristine sources + the not-yet-written narrowing), not
the amendment feature at large. Durable load-bearing change in the trust-boundary domain, so three
rounds. **One FIX-NOW, applied.**

### R1 — FIX-NOW: the consumption honoured what the offer refuses

`amendment_offer` withholds when `tests_modified` (a run that already modified a protected test
outside the sanctioned channel). **`consume_amendment` never checked it.** That gap predates #127
and was *cushioned* by the very bug #127 fixed: every entry re-asked the Proctor, whose write
overwrote whatever was on disk. With the narrowing in place a path already differing from its
baseline is **not** re-asked and is validated *as it stands* — so a protected test modified outside
the sanctioned channel could be sanctioned into `proctor_edits` as though the Proctor had authored
it. That is the producer editing its own exam, the one thing ADR-0087 exists to prevent.

This is F70/F71's shape in the direction the codebase had not written down.
`escalation_amendment_fields` states the rule one way — *"the offer must not promise what the
consumption will refuse"* — and the converse was never enforced.

**Fixed:** `consume_amendment` now refuses and clears on `tests_modified`, with a per-path reason.
Deny-by-default, cleared rather than held, matching the `amendment_gate`-off branch beside it.

**Reachability:** low by the normal flow — only the Proctor runs between authorization and consume,
and the offer is withheld at authorization time. Fixed anyway: the whole point of the narrowing is
that disk content now stands unaltered, and a control that is safe only because of an ordering
assumption elsewhere is not safe.

### R2 — FALSE-POSITIVE: a missing anchored source does not skip the collateral check

Concern: `amendment_before_sources` could be partially populated (a path unreadable at authorization
time), leaving `before_sources.get(rel)` as `None` where the old disk read would have supplied text
— silently skipping the weakening measure. **It does not.** `_weakens(None, …)` returns
`["<no pristine source to compare against>"]`, which counts AS a loss, becomes collateral, and
refuses the path. Fails closed, by existing design.

### R3 — ACCEPT (documented): checkpoint growth

`amendment_before_sources` puts full test-file *source text* into `RunState`, so it rides every
checkpoint write for the rest of the run. Bounded by the authorized set (operator-named, and
intersected with the blocking set) — the live LedgerCLI amendment was 6 files, order 50–100KB. One
amendment per run. Accepted; noted here so it is not rediscovered as a mystery.

### STOP rule

Not triggered — R1 and R3 are different defect classes, and R2 resolved without a fix.

### Test-quality note, recorded because it nearly slipped

The first version of the R1 regression test wrote `assert True` as the tampered content and **passed
with the guard removed** — the assertion floor refused it first, so the test never exercised the
guard. Rewritten to use `_AMENDED` (the exact bytes the sanctioned path accepts elsewhere in the
file), it now fails with the guard removed and passes with it. Green for the wrong reason is the
same defect class as the one-shot test this whole issue started from.

### Consequence worth flagging

`_proctor_authoring.py` now sits at **exactly 500 lines**, the god-file ceiling, with zero headroom;
`unwritten_paths` moved to `_amendment.py` (436) to get there. The next change to that file must
split it.

### Verdict

**`clean_deliver`** for the fix and this round. Residual, unchanged from the fix itself: a run parked
before the change rehydrates without `amendment_before_sources` and falls back to the disk read.
Still owed and NOT done: live re-validation that a behaviour-change task now completes on a single
authorization.
