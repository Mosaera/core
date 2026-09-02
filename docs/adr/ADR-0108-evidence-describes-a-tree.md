# ADR-0108 — Evidence describes a tree, or it is not evidence

- **Status:** Accepted
- **Date:** 2026-08-22
- **Amends:** [ADR-0106](ADR-0106-the-tree-that-ships-is-the-tree-that-passed.md) (extends its rule past `tests_passed`), [ADR-0076](ADR-0076-independent-security-gate.md) (deny-by-default now covers stale, not only absent)
- **Related:** [ADR-0107](ADR-0107-decision-specific-admission.md), [ADR-0090](ADR-0090-gate-reason-classification.md)
- **red-team:** pending

## Context

Found by the whole-product liveness audit (2026-08-22, 11 agents), confirmed by execution:

```
evaluate_gate(tests_passed=True, reviewer_verdict="APPROVE", findings_count=0,
              security_status="clean", scan_attempted=True, oracle_verified=True, ...)
  -> reasons: []   action: deliver
```

`RunState` is last-write-wins, `scan_node` is the sole writer of `security_status`, and **nothing
clears it on a re-plan**. So on the give-up edge — `review → review_fix → implement → capture →
supervise → gate`, where the coder writes *after* scan and review ran — the gate reads an earlier
iteration's `"clean"` about a tree that no longer exists, and **ships**.

ADR-0106 solved exactly this for one channel: `tests_passed` is pinned to `verified_tree` and
`delivery_check` re-measures when the tree moved. Security and the reviewer had no pin at any layer.
ADR-0107's `scan_attempted` closed the *absent* case. **Absent suppressed a question; stale
delivered.**

The plan-unworkable edge is *not* the dangerous one — nothing writes to the tree after `test_node`
there, so its verdicts are stale-but-accurate. Recorded because the first analysis got this backwards.

## Decision

**1. The writer stamps the tree its verdict describes.** `scan_node` returns `security_tree`;
`review_node` returns `review_tree`. This is `_amendment.pinned_coder_validation`'s shape — the
producer records its own tree hash beside its own output — generalised.

**2. One comparison, at one seam.** `graph/_freshness.py` owns `is_fresh`, called from `gate_node`
only. **Fails closed**: a missing stamp, an empty stamp, or an unreadable workspace is NOT fresh.

**3. Two new gate reasons**, `security_stale` and `reviewer_stale`, defaulting to *fresh* so every
existing single-gate-visit assertion stays byte-identical. Only `APPROVE` is freshness-checked on the
reviewer leg — a stale non-approval already parks.

**4. Classified `not_run`, not `objection`.** "It ran on a different tree" means that for *this* tree
it did not run. This is load-bearing: an unclassified reason would silently re-suppress the ADR-0107
ask, which was refused 100% of the time until it was fixed. Both are `PROOF_BEARING`.

**5. `diff` is deliberately NOT freshness-gated at the commit predicate.** `nodes_deliver.py`'s
`state.get("diff")` decides whether to commit; gating it on freshness would silently drop delivered
work, which is worse than the bug.

## Honest limits — HISTORICAL (the first cut; superseded, see "Successor phase 1")

> Every bullet below describes `c2c1ed8e`, whose pin was `tree_hash(limit=None)`. The successor
> moved the pin to `evidence_hash` and made three of them false in the present tense — which a
> red-team lens then had to catch, because no guard detects an ADR contradicting itself. Kept as
> the record of what was believed when, not as a description of the code.

- **The pin is UNBOUNDED (`limit=None`), and the first cut was not.** `Workspace.tree_hash` defaults
  to 300 sorted paths; on this repo that is 300 of 1,315 tracked files. That was recorded here as an
  "honest limit, inherited not introduced" — a framing that was true and useless, because the blind
  regime is the *normal* one. A red-team agent built a 401-file tree, wrote a backdoor to a path
  sorting after the cut, and **reproduced the original bug straight through the fix**: the stamp
  never moved, `scan_fresh` stayed True, and it shipped. Every fixture in the new test file was a
  one-file repo — the only regime where the pin reliably fired. Now unbounded, and
  `test_the_pin_SEES_past_the_300_path_listing_cap` fails if anyone re-bounds it.
  ~~**ADR-0106's `verified_tree` is still capped at 300**~~ — TRUE THEN, FALSE NOW: the successor
  moved it onto `evidence_hash` too. And "unbounded" was never the property that mattered — lifting
  the cap was necessary and nowhere near sufficient, because the blindness that shipped code was
  `_SKIP_DIRS`, not the cap.
- Stat-based `(path, size, mtime_ns)`; a same-size write inside one mtime tick is invisible. No
  agent tool can set mtimes, but target-repo code runs writably during install, so a hostile repo
  could. A content hash is the successor.
- **`live_tree` fails CLOSED — and the first cut did not, while its own docstring said it did.**
  `tree_hash` builds from `os.walk`, which swallows traversal errors, so a missing or empty root
  returns `sha256("")`, never `""`. The documented fail-closed branch was dead code, and with that
  same sentinel on both sides `is_fresh` returned **True**: it vouched for a tree it could not read.
  ~~An explicit `is_dir()`/non-empty probe now precedes the hash.~~ SUPERSEDED — that probe guarded
  the ROOT's existence, not whether the walk yielded anything, so the sentinel survived one
  predicate over and the next round found it again. `f0666bfa` DELETED the probe: `evidence_hash`
  ends the class instead, because git either answers or raises.
- **`security_status == "disabled"` is EXCLUDED from staleness.** The operator turned scanning off,
  so there is no verdict to be stale; parking it would be a false park explained by a false sentence
  ("the code changed after the security scan ran" — no scan ran). It also matters for the
  instrument: `bench/harness.py` disables scanning on **every** benchmark run, so the first cut
  would have minted a new park class across the whole corpus.
- **The rollout measures itself.** Measuring the park rate from stored runs was attempted first and
  is *not possible*: the stamp was never recorded historically, and `audit_events` node rows exist
  for only 6 of 131 runs — so even the upper bound had no sample. The stamp ships with the fix, and
  subsequent runs record what history could not. A first cut of that measurement reported "50% at
  risk" by flagging `scan → review → gate`, the normal path; the number was an artifact of the
  instrument and is recorded here as a caution about the next one.

## Consequences

- A gate reached after a post-scan write parks with an honest reason instead of shipping.
- The ADR-0107 ask still fires on a stale park (`not_run` is ASK-admissible) — pinned by test.
- The SHIP arm remains closed to both new reasons.
- `test_gate_monotonicity`'s cross-product gains `scan_fresh`, `review_fresh` **and the
  `scan_attempted` ADR-0107 missed**, plus `"disabled"` on the status axis — as its own docstring
  requires of any new gate parameter. *This bullet previously asserted the edit had been made when
  it had not; the red team caught the claim, and the edit now exists. Recorded rather than quietly
  corrected, because a false claim in an ADR is the G-class defect this arc is auditing.*
- **The wiring is pinned by execution, not by a quoted comment.** The first test file re-derived
  `gate_node`'s arguments beside a comment promising the two stay in step; mutating `gate_node` to
  stop asking survived **2,136 tests**. `test_gate_node_ITSELF_asks_the_freshness_question` captures
  the kwargs the node really builds, and kills that mutation.
- **The gate panel no longer shows a green "clean" for a scan the gate refused.** That line rendered
  from the scan text alone, so a run parked *because* its clean was stale still showed the person
  holding the override button an unqualified green tick. The stale verdict stopped vouching to the
  gate and carried on vouching to the human — the same defect one layer out.
- **Checkpoints written before this ADR rehydrate as stale** (a `security_status` with no
  `security_tree`) and park rather than ship. Fails safe; self-heals on the next scan.
- **KNOWN RESIDUAL, deferred:** `findings` / `findings_text` / `tests_modified` / `destroyed_paths`
  ride the same last-write-wins channels and are **not** pinned. A park carrying iteration-1
  findings emits `security_findings` (class `objection`) about a dead tree, which suppresses the
  ADR-0107 ask. It fails *safe* — over-suppression, and a producer cannot write past a findings
  verdict to clear it — but it is this ADR's own defect class, one channel over.
- **Two freshness rules, two polarities.** `_freshness.is_fresh` and `_amendment` fail closed;
  `_baseline.delivery_check` fails **open** (an unreadable tree means "no question arises" and the
  commit proceeds). One primitive, three call sites, one disagreeing on direction. Successor work.

## Red-team outcome — THE FIRST CUT DID NOT ACHIEVE ITS GOAL (2026-08-22)

Two rounds, six lenses. **Round 2 reproduced this ADR's own CRITICAL straight through this ADR**,
using nothing but the coder's ordinary `write_file`:

```
stamp before : 3dfe3e62f4bdddbd     # after: write src/.mosaera/backdoor.py
live  after  : 3dfe3e62f4bdddbd
is_fresh     : True                 # the pin is blind
git would commit: A  src/.mosaera/backdoor.py
```

`live_tree` asks `file_listing`, which prunes `_SKIP_DIRS` **by directory name at any depth**. The
delivery path's exclusions are **root-anchored on purpose** — `/.mosaera/`, so a legitimate nested
`src/.mosaera/` deliverable is not silently dropped (#59 red team). So there are two origins for
"what is in the tree" and they disagree, and the gap is exactly a ship path: `reasons == []`,
`action == "deliver"`, file in the commit. ADR-0106's `verified_tree` inherits the identical hole.

**The STOP rule fired on five classes**, each recurring in consecutive rounds:

| class | round 1 | round 2 |
| --- | --- | --- |
| pin blind to part of the tree | past 300 sorted paths | skip-dir names at any depth |
| fails open where it says fail-closed | unreadable root → `sha256("")` | empty listing → `sha256("")` |
| stale evidence vouches to the human | the green "clean" line | the unqualified findings list |
| operator sentence asserts a false cause | `disabled` | unstamped / unreadable |
| control unpinned by tests | wiring survived 2,136 tests | reviewer leg: both mutations survive |

Every one of them is downstream of a single architectural error: **the evidence pin derives "what is
the tree" from a PRESENTATION helper.** `file_listing` was built for humans and models — the PM
overview, the coder's `list_files`, a memo key — and it is *right* for it to hide caches and cap at
300. It is wrong as a security primitive, and every round has found another consequence of that one
mistake one origin over. Patching instances at the reader is not converging; that is precisely what
the STOP rule exists to interrupt.

## Successor phase 1 — LANDED (2026-08-22, owner-approved scope)

`Workspace.evidence_hash` / `committable_paths` replace the SOURCE rather than patching a sixth
instance. `committable_paths` mirrors `_stage_all` exactly — `git ls-files -c -o --exclude-standard`
(the same `.gitignore` + `.git/info/exclude` rules `git add -A` honours) minus the same root-anchored
`.mosaera/` reset — so the evidence listing and the committer are **one origin by construction**, not
two that must be kept in step. Four evidence call sites switched together:

| site | pin |
| --- | --- |
| `_freshness.live_tree` | ADR-0108 security + reviewer |
| `_baseline._stat_key` + `nodes_impl` `verified_tree` | ADR-0106 `tests_passed` |
| `_amendment.pinned_coder_validation` + `factory` stamp | the coder's own validation (F70/#75) |

The ~16 remaining `tree_hash`/`file_listing` callers are memo keys and presentation listings and
**stay on the walk** — hiding caches and capping at 300 is right for a repo overview and wrong only
as a security primitive. That distinction is now stated in both docstrings.

**Proof.** The end-to-end CRITICAL, through the real gate:

```
is_fresh : False              # was True
reasons  : ['security_stale'] # was []
action   : require_human      # was deliver
```

Reverting `live_tree` to the `c2c1ed8e` implementation reds two tests — the skip-dir CRITICAL and
the empty-listing sentinel. Both are regressions, not new assertions.

**Closed by this phase:** the skip-dir ship path · the 300-cap blindness (by construction, not by a
flag) · the `sha256("")` sentinel — git either answers or raises, and an empty committable set is
`""`, so unreadable and empty are both "no fingerprint" and neither can equal a stamp · the
ADR-0106/0108 contradiction, since both pins now ask the same question · the double-walk cost.
**Also closed incidentally:** ignored build artifacts (`.coverage`, `dist/`, stray logs) no longer
move the pin, because git honours `.gitignore` — the pin now moves exactly when the *committable*
set moves, which removes a false-park class the walk had.

**Faster, not slower** — in a clean checkout, **7.3 ms** vs **73.7 ms** (unbounded walk) and
**22.2 ms** (capped). 1,315 committable paths; the walk sees 1,316.

*The first version of this bullet said "254 ms … 39 ms … a 4,925-entry walk", and those numbers do
not reproduce.* They were measured in MY working checkout, where `.claude/worktrees/` held several
thousand files belonging to nested git worktrees — including the red-team agents' own. The walk
counted them; `committable_paths` does not, because git does not. So the figures described my dev
environment and were published as a property of the repo. The direction of the claim survives at
every size and shape independently measured (20k tracked: 75 ms vs 671 ms; 2k tracked + 20k
untracked-not-ignored: 84 ms vs 741 ms; same but gitignored: 7.2 ms vs 733 ms) — the magnitudes did
not. Recorded rather than quietly swapped: this repo has already paid once for trusting a number
without auditing the instrument.

**Not closed — phase 2, needs `gate.py` headroom (it is at exactly 500/500):** splitting the reason
token so `security_stale` stops asserting a cause it cannot know (*moved* vs *never stamped* vs
*unreadable* — currently one false sentence for two of the three), and single-origining the
GatePanel security block so a stale FINDINGS list stops vouching the way the stale clean line did.
Also open: the stat-only residual (hostile-repo-only; no role's allowlist carries a shell or
`utime`, and the give-up edge offers no execution window), `delivery_check`'s fail-open polarity,
and `bench.diagnose_bottleneck` having no branch for either staleness reason.

**What is nonetheless true of the shipped state:** the pin is strictly better than no pin — it
catches an ordinary post-scan edit to an ordinary path, and no round found a way to make the gate
*less* conservative than before ADR-0108. The ship path found here was open before this ADR too; the
defect is that the ADR claimed to close it. Nothing here is a regression against `98ebfb1a`.

## Round 3 verdict — `honest_park`. Phase 1 is NOT done, and the class is wider than this ADR.

Three lenses, isolated worktrees. The mechanism holds: `evidence_hash` genuinely closes the
skip-dir ship path, the cap and the `sha256("")` sentinel; the end-to-end gate flip reproduces;
`committable_paths` matched `_stage_all` on 14 of 14 exotic path-selection fixtures; all eleven
gates are genuinely green. What failed is the FRAMING, three separate ways, each a named recurrence.

**1. "One origin by construction" was established for the PATH LIST and assumed for the
FINGERPRINT.** `committable_paths` asks git; `evidence_hash` then asks the filesystem
(`(root/rel).stat()`). `git add -A` refreshes index entries from the worktree, so any committable
entry with no worktree content is invisible to a worktree stat. Gitlinks are that class today —
reproduced on Mosaera's real clone shape (plain `Repo.clone_from`, so a submodule dir is empty):

```
git status  : M  vendor
is_fresh    : True      <- BLIND
would ship  : vendor
```

The dropped symlink guard is the SAME cause, not a separate bug: git tracks a link's target as
content while `Path.stat()` follows it, so a tracked symlink off-clone makes the pin
nondeterministic (permanent park + a false operator sentence). **Class (a), sixth instance, third
consecutive round. The cause-level fix — an INDEX-sourced fingerprint (`ls-files -s` object ids, or
`status --porcelain=v2`) — closes gitlinks, symlinks, the deleted-file sentinel and the stat-only
mtime residual in one change.** Not attempted here; the STOP rule has fired on this class three
rounds running and a fourth patch from the same author is precisely what it forbids.

**2. THE LOAD-BEARING SENTENCE WAS WRONG, AND IT WAVED THROUGH TWO LIVE CRITICALS.** This ADR said
the remaining callers "are memo keys and presentation listings" and that the cap is "wrong only as a
security primitive". At least four are security primitives, and two are separation-of-duties
controls that are **blind on any real repo** (both PRE-EXISTING, neither introduced here):

- *(HISTORICAL — every finding in this bullet list was subsequently closed: the source moved to
  `security_listing` in `1f710222` and the predicate to the target's own pytest naming in
  `21718bf8`; a reader flagged the present tense here as reading like current state, hence this
  note. The text below is the round-3 record, kept verbatim.)*
- `testintegrity.integrity_paths` (ADR-0036/0058 tamper baseline) — `file_listing()` at the default
  300 cap. On Mosaera itself it baselines **28 of 215** test files. On a 401-file repo, verified:
  `integrity_paths() == []`, the acceptance test is unprotected, and rewriting it produces
  `tampered_paths == []`. **The guard the coder "cannot edit around" is silent while the producer
  rewrites its own exam.**
- the Proctor / disposition protected-test set (`nodes_plan.py:184,212`, `_proctor_authoring.py:226`,
  `disposition.py:206,215`, `_escalation.py:87`, `bench/layer2.py:158`) — same helper, same cap,
  same empty set past the cut.

Also on the walk: `nodes_critic.py:48` memoizes the held-out VETO under a key blind to exactly the
write this ADR exists to catch, and `nodes_impl.py:62` writes the durable suite verdict under a key
namespace its only reader can never match. **Class (a) spans at least eight sites; this ADR moved
four. ESCALATE as one scoped successor — move the tamper/oracle/protected-set consumers onto
`committable_paths` — do not patch site by site.**

**3. THREE OF THE FOUR SWITCHED SITES ARE PINNED BY NOTHING.** Reverting `verified_tree`,
`_stat_key`, `pinned_coder_validation` and the factory stamp all back to `tree_hash()` — restoring
the entire defect this phase exists to close — leaves the FULL suite green: `2914 passed, 0 failed`.
Only `live_tree` is defended. And the "fixture repair" this ADR presents as a win stubs
`evidence_hash` and `tree_hash` to the same canned value, making the control's source untestable by
construction. **Class (e), committed in the act of claiming to fix it.**

**Regressions this phase introduced, over and above the above:**
- **`verified_tree` slid from a PRE-validation to a POST-validation stamp.** It was `key[1]`
  (computed before `run_plan`); it is now `evidence_hash()` after it. `tests_passed` no longer means
  "the suite measured this tree" but "this is the tree just after the suite finished" — including
  anything written DURING validation, the one writable, network-enabled phase running target-repo
  code. The comment explained walk-vs-git and never mentioned timing, because the author did not
  notice. FIX-NOW: take the stamp before `run_plan`.
- **The fail-open aperture at `delivery_check` got wider.** `tree_hash` returned `""` only on
  exception; `evidence_hash` returns it on any git error OR an empty committable set, and
  `if not current: return {}` treats that as "nothing moved". On any instance with scanning disabled
  — **every bench run** — `security_stale` is structurally unreachable, leaving this fail-open path
  as the only remaining pin on `tests_passed`. Class (b).
- **Every in-flight parked run re-parks on resume** with "the code changed after the security scan
  ran". Nothing changed; the hash function did. Guaranteed for `verified_tree` on any repo above 300
  walked paths. A stamped artifact's format changed with no migration note. Class (d).

**Verdict: `honest_park`.** Blocking before this leaves staging: the three unpinned sites, the
`verified_tree` timing regression, and the two separation-of-duties CRITICALs (which are older and
larger than this ADR). The mechanism is worth keeping — reverting would restore the skip-dir ship
path — but the phase is not done and this ADR must stop claiming it is.

## Review trigger

A sixth `ReasonClass`, or a fourth evidence channel needing a pin.
