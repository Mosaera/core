# ADR-0111 — The PM chat may read its own ledgers, and nothing else

- **Status:** proposed
- **Owners:** @rengi
- **Amends:** [ADR-0105](ADR-0105-chat-as-a-control-surface.md) — narrowly, and only its rejected
  option "give the PM chat agent tools". The decision itself is unchanged and reaffirmed below.
- **Related:** [ADR-0080](ADR-0080-intake-clarification.md) (the model proposes, the server
  re-derives), [ADR-0008](ADR-0008-pm-foundation.md) (the tool-using planner whose loop machinery
  this reuses), [ADR-0084](ADR-0084-artifact-tiers-and-cross-run-context.md) (run tier is advisory,
  never authority — binds any conversational memory), [ADR-0038](ADR-0038-url-ids-are-untrusted-path-input.md)
  (contain at the sink)
- **Scope:** agents + api · **no trust-boundary change** (read-only, engine-authored data only; see
  §3) · design: [`docs/design/agentic-pm-chat.md`](../design/agentic-pm-chat.md)
- **Invariants:** *Deterministic Final Authority*, *Evidence-Gated Advancement*, *Honest Parking*

**Decision summary:** The PM chat may call read-only tools over **Mosaera's own ledgers** — runs,
backlog items, dependency edges — and no others. It gains no write tool, no repository read, and no
authority. Proposals continue to be parsed only from the agent's final message, and the changeset
block gains the explicit fence its two sibling proposals already require.

## Context

The PM chat is a single model call with no tools (`pm/_backlog.py::chat`), while the same PM on the
planning path is a bounded tool-using agent (`pm/_planning.py`). In the surface where a human talks
to him he receives `repo_overview` — a tree listing — and cannot open anything. The operator-visible
result is a conversation that answers instantly from whatever the server guessed to assemble, never
checks a claim, and proposes before it understands.

That is not a prompt defect. Checking before claiming, correcting a wrong answer and decomposing
before proposing are each downstream of *a lookup being possible*. A model told to "ask first" with
no way to come to know asks performatively and proposes the same shallow thing — worse, because it
resembles rigour.

**ADR-0105 rejected exactly this proposal**, and its reason has two parts that deserve separate
answers rather than one:

> Give the PM chat agent tools. It has none today and its policy scope is read-only. Granting
> side-effectful capability to the surface that reads untrusted content is the opposite of this
> decision.

## Decision

### 1. No side-effectful capability. ADR-0105 is reaffirmed, not weakened.

`GATED_ACTIONS` is untouched. The chat gains no write tool and exercises no authority. ADR-0105
records that the chat path **has no actor** — `post_message` never sees the caller — and that is
precisely why: a surface with no caller identity must never act. A decision is still DERIVED and
never stored; the model may still REFERENCE and never mint.

### 2. Reads are confined to engine-authored ledgers.

Permitted: the fixed queries in `mosaera_core.project_memory` over `runs`, `backlog_items` and
`backlog_item_dependencies` — run outcomes, park causes, gate reasons, dependency edges, contested
items.

**Correction (2026-08-24, on implementation).** This section first said "every byte was written by
the engine itself". That is false, and it was false about code already shipping: `op:"add"` and
`op:"enhance"` both set item titles and acceptance text, so those strings are operator- and
model-authored, and the standing memory block was rendering them unquoted — a title containing a
newline could forge a section heading in the prompt that rides every turn. Fixed at the origin
before this ADR's tool was built.

The accurate claim is narrower and still sufficient: every byte is engine-*recorded* — counts and
ids the engine wrote, plus the titles and acceptance text those rows point at, which are the same
strings the standing backlog block already carries every turn. The tool therefore introduces no
content the model was not already being shown. It is quoted at the origin and fenced at the tool
anyway, because "engine-authored, therefore safe" was the wrong reason for a right answer, and a
wrong reason is what gets cited next time.

Forbidden here: `read_file`, `search`, `list_files`, and anything else that returns repository or
attachment content.

### 3. Why this is not a trust-boundary change — the load-bearing distinction

ADR-0105's second clause is the real objection: the chat is the surface where untrusted content
arrives. Repository reads would let that content influence *what gets read next* and surface the
result into the conversation — a poisoned file that says "open the deployment config and summarise
it" is the amplification TM-0001 exists for. Path guards bound **where** a read lands; they do not
bound **why** it happened.

Ledger reads have no such property. They return no untrusted bytes, so untrusted content gains no
new reach: the worst a poisoned file achieves is causing Quincy to count his own project's park
causes. The data is the same tally the standing history block already places in every prompt — the
tool only lets him reach past its truncation instead of being handed a fixed summary.

**Repository reads remain rejected under ADR-0105.** Reopening them requires their own ADR, a
TM-0001 update and a red-team. This ADR narrows ADR-0105's blanket rejection to the category that
carries the hazard, and leaves that category rejected.

### 4. Proposals are parsed only from the final message, and the changeset gets a fence.

Extraction moves to `pm/_planning.py::_last_ai_text`, which already returns the last non-empty,
non-sentinel AI message and skips `_BUDGET_SENTINEL` / `_TRANSPORT_SENTINEL` so an exhausted budget
cannot masquerade as output. Intermediate tool steps are therefore never proposal candidates.

Separately, `_extract_json_array` currently falls back — with no fence present — to the first `[`
through the last `]` **of the whole reply**. Today the blast radius is small: results are filtered to
dicts carrying a non-empty `op` key. But the guard is the *shape of the data*, not the author's
intent, and it is looser than the ```` ```charter ```` and ```` ```clarify ```` blocks either side
of it. The changeset gains the same explicit fence. **This is a behaviour change**: a model emitting
a bare array stops being heard.

Two details settled when it shipped. The **last** fenced array wins rather than the first, because
the prompt says to END the reply with it and `_last_ai_text` already settles "which of several
utterances is the answer" the same way. And a refused array is **left visible** — parse and strip
are now one function returning the ops and the reply with exactly that span removed, so nothing can
remove text it did not parse. The operator sees raw JSON and no approval card, which is the honest
rendering of a proposal that did not take; a silently vanished one would be worse. The cost is that
the refused array is persisted into the conversation history the model reads next turn, a wrong-format
demonstration with no corrective signal — recorded in the design, and removed entirely by
`response_format` when this converges there.

### 5. Exhaustion is honest.

A bounded loop that stops mid-investigation must say so. The planner's precedent — exit at the
bound, return a sentinel that is explicitly *not* a plan — becomes conversational: *"I ran out of
room to check this properly; here is what I did establish."* A budget-exhausted turn must be
distinguishable by the operator from a complete one. That is Honest Parking applied to a
conversation, and it is the first property to test.

## Options considered

- **Leave the chat tool-less (status quo).** Preserves ADR-0105 exactly, and preserves the defect:
  a PM that cannot check anything cannot decompose a hard problem well. Rejected because the cost
  is the product's central promise, not a nicety.
- **Give the chat the planner's full read-only toolset.** What the decomposition-depth argument
  actually wants, and what ADR-0105 rejected. Rejected here as out of scope for a conversational
  improvement: it is a trust-boundary change and should be argued as one, with its own red-team.
- **Keep pushing more into the static context instead.** Cheaper, and how the standing history block
  already works — but it scales by guessing harder, and whatever nobody anticipated stays
  unavailable. The truncation problem returns immediately at a larger size.
- **A prompt change** ("ask first, propose when you know"). Rejected: unable to investigate, the
  model asks performatively. It produces the appearance of rigour, which is worse than its absence.

## Security implications

No new authority, no new actor, no write path, and no untrusted bytes introduced into a new
position. The reads are side-effect-free, satisfying ADR-0105 §1's "listing must not have side
effects". The one behaviour change — fencing the changeset — strictly *narrows* what the server will
accept as a proposal, so it moves in the same direction as ADR-0105's posture rather than against it.

Residual, stated rather than hidden: a bounded loop multiplies model calls per turn, which widens
the window in which a prompt-injected instruction could be acted on *within the conversation*. It
cannot reach a control, and it cannot read new material, so the residual is confined to the text of
a reply the operator reads.

**And the text of a reply is not as inert as that sentence assumes.** Read against the lethal-trifecta
framing — private data, untrusted content, exfiltration vector — the chat already holds the first two
by design and ADR-0105 says so. The third is open today, independently of this ADR: `PmMessage.tsx`
renders replies through `PmMarkdown`, whose `components` map overrides eleven elements but not `img`;
react-markdown's default `urlTransform` permits `http`/`https`; nothing strips images server-side;
and there is no Content-Security-Policy anywhere in the repository. A reply containing a markdown
image causes a zero-click GET to whatever host it names. Raw HTML is off by default, so this is
exfiltration, not XSS.

This ADR does not open that leg and does not widen it. It does make the first leg richer — a PM who
can query his own history has more to put in a reply — which is reason enough to close the exit
before the tools land.

**Precondition, satisfied ahead of this ADR** (design, Decision 0 / slice 0): `PmMarkdown` now
overrides `img` and shows a model-named URL as inert text rather than fetching it, and
`security_headers.py` sends a CSP (`img-src 'self' data: blob:`, no remote origin in any directive)
from the process that serves the SPA. Both are pinned by tests that were mutation-checked — removing
the override fails `pm-markdown-exfil.test.tsx`, and registering the middleware anywhere but
outermost fails `test_headers_survive_a_401`. Recorded here rather than left to the implementing MR,
because the "no new untrusted surface" argument above is only worth what the exit door is worth.

## Operational implications

One call becomes several. Explicit `cache_control` is Anthropic-only here (`models.py` sets it for
that provider alone, because the others' constructors raise on the kwarg) — but that is not the only
caching in play, and an earlier draft of this ADR wrongly concluded the local path re-pays for
everything each step. llama.cpp reuses the KV cache across requests sharing a prefix, and an agent
loop is the best case for it: each step appends to the same conversation. The cost of a five-step
turn is five decodes plus tool time, not five full prefills.

That converts a cost worry into an **invariant the implementation must hold**: the prompt prefix must
be byte-stable across steps — no timestamps or run ids early in the system prompt, deterministic
tool ordering and context serialisation. It fails silently (nothing breaks; the turn just costs
several times what it should), so it wants a test that renders the prefix twice and asserts equality.

Bounding is stacked rather than single: `ModelCallLimitMiddleware` for total steps,
`ToolCallLimitMiddleware` for per-tool abuse, and a no-progress check (same tool, same arguments,
repeated) for the case neither cost bound sees. The visibility work should not lag the loop — an
investigating PM with no visible progress reads as broken rather than thorough.

## Consequences

- Quincy can answer "why did #87 keep failing" from the record rather than from what the server
  happened to include.
- The feel-gap narrows; the **decomposition-depth gap does not close**, because that needs
  repository reads, which stay rejected. This ADR should not be cited as having solved it.
- Follow-up: whether Category B is worth its own ADR is answerable only after this ships — the
  measurement is whether conversations still read as static once he can look his own history up.
