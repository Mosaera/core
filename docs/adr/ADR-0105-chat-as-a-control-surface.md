# ADR-0105 — The chat is a control *surface*, never a control

- **Status:** accepted (owner-approved 2026-08-19, in-session)
- **Scope:** api + agents + web · **trust boundary** (an approval surface and a credential surface
  reachable from a model-facing conversation) · threat model TM-0002 updated · red-team required
- **Builds on:** [ADR-0104](ADR-0104-gitlab-oauth-connect.md) (the one GitLab dialog this reuses
  rather than reimplements) · [ADR-0004](ADR-0004-auth-and-session-model.md) (role boundary) ·
  [ADR-0082](ADR-0082-gate-decisions-and-standards.md) (the gate offers only the answers the engine
  made available) · [ADR-0102](ADR-0102-delivery-spine-truth-up.md) (the authenticated call *is*
  the human control for delivery actions) · [ADR-0080](ADR-0080-intake-clarification.md) (the
  precedent: the model proposes, the server re-derives, the operator accepts)
- **Advances:** ADR-0045 / issue #31 "Quincy as the single interface" — which remains DIRECTION.
  This is one slice of it, not the arc.

## Context — the operator wants to work from the conversation

The owner asked for the PM chat to become where work happens, with the other tabs demoted to
drill-downs: Quincy showing controls to approve git operations, and a card that sets up the GitLab
integration without leaving the conversation.

Today's chat cards cannot carry that. They are **model output**: Quincy emits a fenced block, the
server regex-parses it, and the client holds the result in component state — so a card **dies on a
reload** (an acknowledged TODO in `PmChangesetCard.tsx`). `ProjectMessage` has no structured payload
column. And the chat path has **no actor**: `post_message` never sees the caller, so nothing there
can attribute an approval to a person.

That last fact decides the design. **An approval surface that cannot identify the approver is not an
approval surface.**

There is also a threat the existing cards do not face. Quincy's context carries untrusted
repository content (the repo overview, attachments, and — since the ADR-0047 amendment — a
member-authored charter, which needed its own fence for exactly this reason). A model that can
*summon* UI can be talked into summoning a credential prompt. That is phishing inside the product,
triggered by a file in someone's repo.

## Decision

**The chat becomes a new surface over controls that already exist. It never becomes a new control.**

### 1. Decisions are DERIVED, never stored

`GET /api/projects/{id}/decisions` recomputes the pending set on every call from live state — a
parked run's durable status, whether the project can reach GitLab, an item MR whose recorded target
is gone. No table, no migration, no second source of truth to drift, and nothing to forget to clear:
when the underlying control resolves, the decision stops being returned.

Listing **must not have side effects**. In particular it peeks at live sessions and never calls
`get_session`, which *rehydrates* — resuming runs as a side effect of rendering a chat panel would
turn a read into a write.

### 2. The model may REFERENCE a decision; it may never mint one

Quincy is told it can write `[[decision:<id>]]`, and only for an id the context actually listed.
After the reply, the server intersects every referenced id with the set derived for that turn and
drops the rest, then strips the markers **before the message is persisted** — the stored transcript
is what a reload renders, so stripping only the returned copy would put the raw markers back on
screen at the next refresh and replay them into the model's history. **An id the model invents
renders nothing.**
This is the ADR-0080 discipline applied to a new surface: the model proposes, the server re-derives
rather than believes.

The chat system prompt also states plainly that credentials are never to be requested as chat
messages.

### 3. Actions hand off; they do not authorize

A decision carries `actions[]` of `{label, kind}` — **a named UI control, never a url, method, or
body**. Answering a gate opens the run's own gate, which offers only the answers the engine made
available (ADR-0082) and remains the single deterministic authority. Repointing a stuck MR goes to
the Delivery page. Nothing is approved in the chat, so no second path to green-light anything is
created, and Deterministic Final Authority is untouched.

`requires_admin` is a **presentation hint** so the surface stops offering what the server would
refuse — it grants nothing, and every action's own endpoint keeps its own gate.

### 4. A credential never traverses the chat

The setup action opens **the same `GitLabDialog`** the settings pane opens (ADR-0104 Amendment 2's
"one control"), whose save posts to the existing admin-gated `POST /api/gitlab/config` — which
verifies the pair against the instance before storing and encrypts the secret at rest (ADR-0039).
The value never enters `ProjectMessage.content`, the transcript, or the model context. Reusing the
dialog rather than extracting a second copy of the instructions is deliberate: two copies drift, and
the drifting one would be the one asking for a secret.

**Naming:** "card" already means *benchmark scorecard* throughout this repo. Server-side vocabulary
is **decision**; "card" stays a UI word.

## Consequences

- Cards are query-backed and therefore **survive a reload**, unlike the changeset and charter cards.
  A pending decision that vanished on refresh would be worse than none.
- The conversation can now tell an operator what is blocking them and take them to the control,
  without acquiring the ability to act.
- New attack surface: a model-referenced UI element. Mitigated structurally (server-derived +
  id validation + no endpoint in the payload) rather than by prompt instruction alone.
- Deriving `mr_stuck` costs one REST read (20s timeout) when the project has an api token; when we
  cannot ask, we claim nothing rather than guess. The **interactive chat turn derives with
  `allow_network=False`** so that call never sits in front of a conversation — the `/decisions`
  endpoint derives the full set asynchronously instead.
- The transcript is stored verbatim and replayed into the model context each turn, so credential-
  shaped strings are redacted on write (`redact_chat.py`). Narrow and prefix-anchored: a mitigation
  for the paste that happens anyway, not a general secret detector, because a heuristic broad enough
  to catch an arbitrary secret is broad enough to corrupt legitimate messages.

## Alternatives rejected

- **Let Quincy request a card by id from a fixed catalogue.** More conversational, but it makes the
  model the trigger for showing a credential prompt, and its context carries untrusted repo content.
  Rejected: the precondition must be re-derived, not requested.
- **Store decisions in a table.** A second source of truth that can outlive the thing it describes —
  the exact recompute-vs-record failure mode, inverted. Derivation has no stale state.
- **Give the PM chat agent tools.** It has none today and its policy scope is read-only
  (`packages/policies`). Granting side-effectful capability to the surface that reads untrusted
  content is the opposite of this decision.
- **A generic card/plugin registry.** CLAUDE.md's Not-Yet list forbids a generalized artifact
  platform before the first use case is proven. This slice *is* the first use case.

## Amendment — slice 2 (2026-08-19): Quincy can see delivery, and the network ban becomes a budget

Asked on a live project to "look over our git and make sure everything is clean", Quincy answered
four times that he had no access to the repository's branches or merge requests, and offered shell
commands. He was right. A direct API read then found, in seconds, **six items on one project and one
on another delivered with committed work and nothing proposing it anywhere**, plus two stale
branches. The product knew all of it; the PM did not.

1. **A `## Delivery` section in the PM context.** Item and project facts come from
   `project_detail` — the rows already carried `branch`/`mr_url`/`mr_state`/`mr_target` and the
   renderers discarded them. Branch facts come from the bounded read below. The block states what it
   does NOT know: item MR state is last-polled, and when the branch read did not land it says
   **NOT CHECKED** rather than letting a model infer a clean repo from silence. That sentence is the
   control, and a test asserts it.
2. **The slice-1 network BAN becomes a DEADLINE.** `allow_network=False` skipped the REST-backed
   decision kind on the chat path, justified by a 20-second worst case that was **never observed** —
   measured against this self-hosted instance the whole derivation takes ~140ms. Its real cost was
   that Quincy could not see a decision the panel was showing him, which is the Round 2 question the
   slice-1 red team left open. The chat turn now asks with a ~3s deadline; `/decisions` keeps the
   default. Exceeding it is just another "cannot ask" and lands on the existing claim-nothing path.
   The read is additionally wrapped so no failure of an *enrichment* can cost an operator their
   conversation.
3. **`delivered_no_mr`** — one AGGREGATE decision, never one per item (six cards in a conversation
   is noise). Free to derive, so it holds on both paths. Member-available: opening a merge request
   is the authenticated call itself (ADR-0102).
4. **Remote-derived strings reaching the model go through `quote_repo_text`.** Slice 1 interpolated
   a GitLab branch name raw into `_stuck_mrs`. Branch names are remote content: flattened,
   non-printables stripped, length-bounded, so a crafted name cannot start a line and forge a `##`
   section. `_fence_operator_text` is NOT the right tool here — it keeps newlines, because it
   protects trusted operator prose.

## Amendment — the reference channel is on probation (2026-08-19)

Decision 2 above gave the model a channel to point at a decision inline. The **guard** works and is
mutation-tested. The **channel has never been used**: across every live turn of slices 1 and 2, on
projects with pending decisions in context, the validated reference set came back empty every time.
The cards render anyway, because they are server-derived — which is the design working, and also the
reason the channel earns nothing.

Rather than delete it on one confounded observation, it gets one fair chance and a kill criterion:

- The mechanical convention **moved out of the system prompt** — where it sat in ~7,700 characters,
  thousands of characters from the ids it refers to — and now renders **inside the
  `## Pending decisions` block**, directly under those ids, and only when there are any.
- The **credential prohibition did not move.** It is a standing safety rule, it applies whether or
  not decisions exist, and the system prompt is the trusted channel; the assembled context also
  carries repo overview, charter and attachment text.
- **Measured:** a log line per turn that offered a decision (the denominator) and an audit event
  written only on a fire (the numerator, visible in the Activity tab).
- **Kill criterion, fixed in advance:** after 20 offering turns or one week of normal use,
  whichever comes first, if the referenced count is still zero, **remove the channel** — the clause,
  the `_DECISION_REF` regex, and the validation. The cards are unaffected. Recorded now so a second
  zero cannot be rationalised into a third placement attempt.

Note what survives either outcome: the *guarantee* that a model cannot mint a decision does not
depend on the channel existing. Removing the channel removes an injection surface; it removes no
safety property.

## Amendment — the context is de-duplicated (2026-08-19)

A research pass over everything Quincy receives found that **"what needs my attention?" was answered
four times in one prompt**, from four independent code paths, for the same item: a `## Backlog` row
carrying `[in_review]`, a dedicated `In review, awaiting the stakeholder's approval:` line, `##
Delivery` stranded rows, and the `## Pending decisions` count. The stranded predicate was written out
character-identically in **two modules** with no shared helper. That is why Quincy answered a
"what's waiting on me?" question from the delivery block and never referenced the decision: the block
he was asked to cite was the *poorest* of the four and the richest one came later.

- **Each block now owns one job.** Decisions own *what needs action* and carry the item ids (the
  summary is rendered, not just the title). Delivery owns *what is the state* — counts and branches —
  and points at the decision instead of re-enumerating it.
- **The duplicated predicate is gone.** The delivery block reads the count off the decision, so the
  two cannot drift. No new module: `build_pm_context` already had both in scope.
- **The dedicated in-review line is removed.** It restated `#id title` for a subset of rows that
  already carry `[in_review]`, with no new field. Its stated purpose — answer from project state,
  not conversation claims — is served by the rows themselves.
- **The delivery-agent capability block was injected twice per turn**, byte-identical, under the same
  heading, in two different trust tiers. The context copy is gone; the system-prompt copy stays
  because it is the one carrying the restrictive clause.

Measured effect on the assembled context for one stranded item: mentions of that item drop from four
to two, and two whole sections disappear.

**Why this is not cosmetic.** On 2026-08-07 the planner's context filled to **10 tokens of headroom**
and it fell back to generic plans until `num_ctx` was raised (`friction-log:538-560`). Space in this
prompt has a measured failure mode.

**The `[[decision:…]]` probation tally resets.** This restructures the context the experiment was
measuring — the 3 turns collected on 2026-08-19 measured a different prompt, and carrying them
across a changed baseline would be the kind of quiet comparison the kill criterion exists to prevent.


## Amendment — the surface reports what a run would have discovered (2026-08-19)

Asked to run one backlog item on a live project, the engine parked honestly: the acceptance test
demanded deleting imports that are actually used, because the *item* named them as unused. The
autonomous chain then ran four more items and ended `INCOMPLETE` on every one — already satisfied,
unbuildable, no independent oracle. **310 model round trips, nothing delivered**, on items that
deterministic checks in this repository could already flag in milliseconds.

None of those checks reached the operator in time. `checkability` runs and marks the backlog rows;
`reachability_findings` exists and, given the offending item's own text, returns the exact sentence
("needs running git … which the delivery agent cannot do"); `backlog_audit` computes the whole
report and is a CLI nothing in the app calls. The gap was never detection. It was that **the
launch gate reads a STORED clarification**, and nothing writes one for an item created after
decompose — by changeset, by chat, or by hand.

A new decision kind, `backlog_health`, reports what a run would have discovered:

- **Derived, never stored**, like every sibling — it disappears when the backlog is repaired.
- **`standing`, never `blocking`**: nothing is broken and no run is parked. These items simply
  should not be started as written.
- **Advisory. It does not gate a launch.** `backlog_audit` is deliberately read-only and says why:
  three graders written during the 2026-08-05 governance sweeps over-fired and scored correct work
  as failures. An over-eager detector here would lock an operator's real backlog rather than merely
  produce a bad number. The owner chose advisory explicitly.
- **`intake_ask_unreachable` stays OFF.** The roadmap conditions enabling it on a measured
  precision number. A report is not an ask, so it needs no knob and changes no intake behaviour;
  the reachability rule gained `include_description` and `statuses` parameters, both defaulting to
  today's behaviour, so the ask path and the report path differ without a second copy of the rule.
- **Checkability is deliberately NOT repeated in the card.** Every backlog row already carries its
  marker and the launch gate already refuses an open ask. Repeating it would be a second origin for
  one fact — the defect removed from this same prompt earlier the same day — and it fires on most
  real backlogs, which would make the card permanent furniture.

### The duplicate rule had to be replaced, and the measurement is why

`spec_lint` already had a near-duplicate check: token-set Jaccard over `title + acceptance`. On the
corpus above, where seven duplicate pairs were confirmed by hand against the repository, **it fired
on none of them**. The cause is structural, not a mis-set threshold: these duplicates are
*re-creations*, so one side carries full acceptance criteria and the other carries none. The union
balloons while the intersection does not, and Jaccard divides by the union.

The obvious repair — the overlap coefficient — inverts the bias and scored **54% precision**,
reporting six false pairs driven entirely by short titles.

What separates the classes is *rarity*: shared words like "add", "create" or the package name carry
almost no evidence, while "egg-info", "pandas" or "F401" carry nearly all of it. IDF-weighted
cosine over **groups rather than pairs** reproduces all five real groups with none invented, and
grouping is also what an operator wants to read ("these three are one job").

**How the grouping is done turned out to matter more than the threshold, and the first version got
it wrong.** It shipped single linkage — a union-find over every edge above the threshold — and live
validation broke it within hours. Rewriting one item in the product had reused another item's
closing sentence ("The existing test suite still passes unchanged…"); on a 16-item corpus that
boilerplate reads as rare, the accidental pair scored 0.305 against a 0.3 threshold, and single
linkage welded the .gitignore group to the unused-imports group into one five-item blob. Chaining
on a single false edge is the textbook failure of single linkage, and the blast radius is a whole
group, not one pair.

Average linkage — a merge decided by the mean similarity across every cross-pair — outvotes the
accident with the members that genuinely disagree, while still carrying a group over one weak edge.
It reproduces all five groups at **both 0.25 and 0.3**, where single linkage was wrong at both, so
the fix also widened the stable band rather than balancing the rule on a fitted number.

**The threshold remains provisional.** 0.3 was chosen after seeing the labels on one small backlog,
and IDF over few documents is unstable by construction — the false edge existed precisely because a
boilerplate sentence looked rare in a 16-item corpus. That uncertainty is affordable only because
the card advises and never blocks: a wrong grouping costs a suggestion the operator declines. It is
the reason this is not wired into a gate.

## Amendment — a changeset may not delete delivered work (2026-08-19)

Run as a non-technical operator, with the PM as the expert, the curate path failed dangerously.
Asked to tidy a live backlog it proposed deleting **twelve** items, five of them `done` or
`in_review` with runs and branches behind them. Asked in the *same conversation* whether that was
safe, it said no and explained precisely what would be lost — "would erase the record", "discard
the pending work and its MR". Asked for one safe list, it proposed four locks and silently dropped
the duplicate cleanup that had been the entire request. It produced the correct changeset only
after the operator named the problem themselves.

The knowledge was there. The path that produced the ops did not use it. **A control that depends on
which code path the model happened to take is not a control** (ADR-0063), and the operator most
likely to click Apply is the one least able to audit what it does. What saved the session was the
reviewer asking "is this safe?" — and nothing in the product prompts a non-technical operator to.

`apply_backlog_changeset` now refuses any op that DESTROYS the row of delivered work — `delete`,
the parent of a `split`, and every source of a `merge`, matching the three doors the store's
`_refuse_if_mr_live` already had to cover. Delivered means `done`/`in_review`, **or** carrying a
branch or MR url: status is not the only evidence, and the row is what branch protection reads.

This closes a real gap rather than duplicating the store guard. `_refuse_if_mr_live` fires only
while a merge request is OPEN; the state here is work committed with **no merge request at all** —
what the `delivered_no_mr` decision reports, and the majority state on a project that has been
running autonomously.

**The override is a parameter of the human's request, never a field on an op.** The threat is a
model-authored changeset an operator accepts, so a permission flag living inside the changeset
would be granted by the very text it guards. `allow_delivered` can only come from the authenticated
call — the same rule as every other decision here: authority flows from the request, never from
model output. A test asserts that an op setting `allow_delivered`/`confirmed`/`force` on itself
achieves nothing.

Rejection is whole-set, matching the surrounding validator: each op is its own transaction, so
applying the safe half of a rejected changeset would leave the backlog in a state nobody proposed.

## Amendment — the decision surface leaves the conversation (2026-08-22)

**What changed.** The `DecisionCard` list moved out of the PM transcript and onto the project
Overview as a **"Waiting on you" band**, mirrored on the (previously placeholder) header bell. The
component moved with it: `components/pm/DecisionCard.tsx` → `components/overview/DecisionCard.tsx`.

**Why.** The owner's objection was the shape, not the derivation: *"the PM shouldn't have just stale
decision objects… my original thought was more of a notification style that the PM would surface on
finding or the engine surfacing so the operator could act on it or have Quincy do for them."* The
cards were query-backed but had **no refetch interval** (only a chat-send invalidation), **no
dismissal, and no acknowledgment**, so they were permanent furniture pinned to the bottom of every
conversation. A condition resolved elsewhere — the operator answering the gate on the Runs page —
stayed on screen until the tab remounted.

**This does not reverse §1.** The condition is still **derived, never stored**: recomputed on every
read, so a resolved condition disappears rather than rotting. What is now persisted is only the
**human's response** — an acknowledgment — which is what distinguishes an inbox from wallpaper. It
lives client-side (`lib/decisionAck.ts`, `localStorage`), so there is still no server table and no
second source of truth for the condition itself.

**Two rules constrain the acknowledgment, and both are enforced in code and pinned by tests:**

1. **A blocking decision can never be acknowledged.** `gate:{run_id}` is ONE id for a run that may
   park at several different gates over its life, so an ack on the first question would silence the
   second invisibly and without record — an unrecorded suppression of an ask, which
   **ADR-0107 forbids**. Rather than detecting the collision, the surface removes the capability:
   only `standing` advisories are dismissible. A blocking condition is cleared by acting.
2. **The ack is keyed to the payload, not the id.** `backlog-health` and `delivered-no-mr` are
   constant ids whose contents grow; dismissing "12 delivered items have no MR" must not silence
   "13". The key digests the title and summary the operator actually read, so a changed finding
   re-raises itself. Every failure mode fails **open** — a card shows rather than hides.

**Placement was never binding.** §3's requirement is that actions *hand off* to the control that
already owns them, carrying `{label, kind}` and no url/method/body; §4's is that a credential never
traverses the chat. Both hold verbatim — the same `GitLabDialog`, the same links. The Consequences
prose above ("the conversation can now tell an operator what is blocking them") is superseded by
this amendment: the *console* tells them, and the conversation stays a conversation.

**The reference channel is retired.** The `[[decision:<id>]]` channel was placed on probation by the
2026-08-19 amendment with an explicit kill criterion. It never fired in live use, and it existed
solely to point at a card inside the transcript. With the cards gone the channel has no referent, so
it is removed rather than left to rot.

**What did NOT move.** `PmChatPanel` still invalidates `["decisions", project.id]` on a successful
send, although it now renders nothing from that query: a chat turn can resolve a condition (Quincy
raising a clarification, an operator applying a changeset), and the band reads the same key.
Deleting the invalidation with the cards would have left the band stale after exactly the turns most
likely to change it. Nothing in the suite guards that line; the comment on it is the guard.

**Cost note.** `project_decisions` makes a GitLab REST call per request via `_stuck_mrs`. The band
and the bell share **one** query key and a 60s interval, so the bell adds no requests, and the
interval is the ceiling on that round trip per open tab. The surface stays **per project** — there
is no cross-project decisions endpoint, and a client-side fan-out would multiply that call by the
project count.
