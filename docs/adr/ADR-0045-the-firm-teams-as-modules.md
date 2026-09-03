# ADR-0045: The firm — teams as pluggable modules, Quincy as the single interface

- Status: accepted
- Date: 2026-07-16
- Owners: Alejandro Rengifo
- Related issue: #31 (design ADRs for Waves B/C), #18 (the software org), #6 (project onboarding)
- Related: [ADR-0002](ADR-0002-deterministic-first-and-model-agnostic.md) (the DNA the firm inherits), [ADR-0013](ADR-0013-adding-an-agent.md) (the `AgentSpec` registry + the adding-an-agent SOP this generalizes), [ADR-0032](ADR-0032-adding-a-languagepack.md) (the `LanguagePack` seam **and the extract-from-N=3 precedent this ADR obeys**), [ADR-0034](ADR-0034-only-executed-evidence-may-ship.md) (the executed-evidence invariant the firm collides with), [ADR-0044](ADR-0044-oracle-make-real.md) (the independent oracle), [ADR-0046](ADR-0046-posture-and-autonomy-governance.md) (posture governs every team), [ADR-0047](ADR-0047-project-onboarding-and-the-durable-map.md) (the map Quincy scopes against)
- Related threat model: docs/threat-models/TM-0001 (a team defines its own tools + oracle + delivery = engine trust) — **no threat-surface change lands with this ADR; nothing is built yet**

## Context

The north star ([`../architecture/north-star.md`](../architecture/north-star.md)) is an autonomous
AI **firm**: pluggable *teams* you hire, each a real department with its own craft, workflow,
definition of "done," tools, and delivery — with **Quincy as the single operator interface**, and
"adding a team is registering a module, not forking the engine." The software-engineering team is
the first and hardest; an **editorial team** (draft → edit → schedule → publish to LinkedIn/blogs
via Postiz) is the next planned vertical.

Today there is exactly **one team**, and the engine is shaped around it. A seam-by-seam audit of
the four SWE-bound seams found they are *unevenly* mature, which is the single most important input
to this decision:

| Seam | Today | How SWE-bound |
|---|---|---|
| **Delivery** | `deliver_node` (`graph/nodes_deliver.py:13`) is **39 lines** — `commit_all` + `write_report` + `persist_run`. MR opening already lives **outside the graph**, in `apps/api/mosaera_api/delivery.py:58` (`open_project_mr`). | Deeply git/GitLab-shaped (`is_gitlab_source` hard-gate `delivery.py:66`; `git push -o merge_request.create` `gitlab.py:181`; branch presence *is* the idempotency marker `delivery.py:141`) — **but structurally best-positioned**: the graph touches git through one call. |
| **Tools** | `ROLE_TOOL_ALLOWLIST: Mapping[str, frozenset[str]]` (`policies/allowlist.py:25`) — per-role, flat, **global; no team axis**. A closed set of 7 repo tools built by `build_repo_tools()` (`tools/repo/factory.py:105`). No tool registry. | Every tool is a repo op; `run_tests` *is* the validation plan. Separation of duties is expressed as path prefixes (`write_prefix="tests/"`, `build.py:148`). Blocked by `Role` being a type-level `Literal` (`config/_types.py:12`) that ADR-0013 deliberately keeps underivable at runtime. |
| **Workflow graph** | `build_graph()` (`graph/build.py:97`) is a **fixed spine**: 15 literal `add_node` calls (`build.py:202-216`), hardcoded edges, node names as string literals. Two injection points exist (`team_factory`, `model_factory`) — both about *who fills a role*, not *what the roles are*. | `RunState` (`graph/state.py:12`) is the most SWE-bound artifact we have: of ~45 fields the majority are code-specific (`diff`, `commit_sha`, `tests_passed`, `integrity_baseline`, `hygiene_findings`, `quality`…). A declared **hot file**. |
| **Validation/oracle** | Already a real seam — `LanguagePack.detect` (`languages/base.py:50`), confidence-scored dispatch, language-agnostic dataclasses. | Generalizes across **programming languages, not across disciplines**. `ValidationStep.cmd` is `list[str]` — **sandbox argv** (`run_plan` → `sandbox.run`, `validation.py:321`). ADR-0032 is Stage 0 (detection only) by its own docstring. |

**`AgentTeam` is a false friend.** `AgentTeam` (`agents_bridge.py:39`) is a Protocol meaning "the
bundle of the four agents for this run" — its methods are `plan/design/author_tests/review/…`. It
is *not* "a hireable department." `AGENT_REGISTRY` (`team.py:50`) is a flat 4-tuple of
*individuals*, each coupled to hardcoded graph node names. **There is no team-of-teams abstraction
anywhere in the codebase.** Anyone reading "team" in the source and assuming the firm layer is
half-built would be wrong; this ADR exists partly to kill that misreading.

### The collision that actually matters

The audit surfaced one finding that is not a refactoring cost but a **design contradiction**:

`strength="suite"` (`validation.py:197`) is defined as *"a real test suite executes"*, and it is
load-bearing in the delivery gate (`gate.py:117`) — [ADR-0034](ADR-0034-only-executed-evidence-may-ship.md)
narrowed autonomous delivery to **executed evidence only**, deny-by-default (`strength` defaults to
`"unknown"`). An **editorial team has no argv and no executed suite.** Under today's gate an
editorial run is permanently `shallow`/`unknown` → **it always parks**. The firm layer therefore
collides head-on with our strongest correctness invariant.

There are only two honest ways out, and one dishonest one. The dishonest one — let a team declare
its own `strength="suite"`, or exempt non-code teams from the gate — would convert ADR-0034 from an
invariant into a suggestion, and would let the *cheapest possible* team plug in and ship unverified.
We reject it explicitly. This ADR does not solve the editorial-evidence problem; it **names it as
the gating prerequisite for team #2** and refuses to let the firm layer be built around it.

## Decision

**1. The firm is built by staged EXTRACTION from a second real team — not designed from N=1.**

ADR-0032 earned this rule the hard way and stated it in its own title line: *"Extract-from-N=3, not
design-from-1."* It extracted the `LanguagePack` seam from what was *already* language-specific,
ported Python behaviour-preservingly, then added Node and SQL against it — and was written from
three concrete packs. We have **one** team. Designing the full team-plugin API now would be
designing from N=1, against four seams the audit just proved differ wildly in shape and maturity.
We would be guessing, and the guess would harden into a public contract.

Therefore: **no `Team` plugin API, no team registry, and no `RunState` split lands until the
editorial team exists as a concrete second implementation.** The firm layer is direction; this ADR
fixes the *vocabulary, the order, and the invariants* so that when team #2 arrives the extraction
is mechanical rather than exploratory.

**2. Vocabulary (binding — these names are load-bearing across ADR-0046/0047).**

- **Firm** — the whole operation; what the operator hires from.
- **Team** — a department (SWE, editorial). Owns a craft: a spine, a set of agents, tools, an
  evidence discipline, a delivery target. The unit of pluggability.
- **Agent** — an individual within a team (`AgentSpec`, ADR-0013). *Unchanged by this ADR.*
- **Quincy** — the firm interface. **Quincy is not the SWE team's PM wearing a firm hat.** Today
  Quincy *is* the `pm` role bound to the `plan` node (`team.py:50`). In the firm, Quincy sits
  **above** teams: scopes work, dispatches to a team, reports back with a point of view. The
  SWE team still needs its own planner. Splitting Quincy-the-firm-interface from Quincy-the-SWE-PM
  is part of the extraction, not a rename.
- **Portfolio** — the set of projects the firm holds, each with a durable map + charter (ADR-0047).
- **Posture** — the autonomy/compliance profile governing a run (ADR-0046). Posture is
  **firm-wide and per-project, never per-team**: a team cannot grant itself autonomy.

**3. Extraction order — cheapest and best-positioned seam first, hot files last.**

The audit ranks the seams by distance-from-pluggable. We follow that ranking, because each earlier
step de-risks the next and none of them require touching a hot file until the end:

1. **Delivery → a `Publisher` protocol.** Best-positioned: `deliver_node` is 39 lines and the
   git-specific MR logic *already* sits outside the graph in the API layer. Extract a
   `Publisher.publish(artifact, destination) -> Receipt` behind `deliver_node`; the GitLab MR path
   becomes the reference implementation. The hard part is **not** the protocol — it is the
   **artifact model**: today "the work product" is a git clone and the evidence is `state["diff"]`.
   There is no abstraction for "a draft."
2. **Tools → key the allowlist by `(team, role)`.** Mechanical but CODEOWNERS-gated
   (`packages/policies` is the trust boundary). Requires opening the `Role` `Literal`, which
   ADR-0013 closed on purpose — so this step **reopens a deliberate decision** and must be argued,
   not assumed. A tool *registry* (teams contribute tools) is a separate, larger step: an editorial
   team needs `fetch_url`/`search_web`/`post_draft`, none of which exist.
3. **Evidence discipline → the collision above.** Blocked on solving editorial evidence honestly.
   See *Consequences*.
4. **Workflow graph → last.** The biggest lift (a node/edge registry + splitting `RunState` into a
   generic core + per-team extension, minding that LangGraph reducers are declared per-key), and
   `graph/build.py`/`graph/state.py` are declared **hot files** — per the parallel-sessions
   protocol, edits serialize. Doing this first would block every other session for the duration.

**4. A team is engine-trust. First-party only, indefinitely.**

A team defines its own oracle, its own tools, and its own delivery target. That is precisely the
set of things the trust boundary exists to constrain. A third-party/community team is therefore
**not a plugin — it is a co-maintainer with commit rights to the gate.** ADR-0032 reached the same
conclusion for community language packs and parked it as FUTURE, gated on a public-API + untrusted-
plugin contract. We adopt the same posture and go no further: **teams are first-party, in-repo, and
CODEOWNERS-reviewed.** "Pluggable" in the north star means *the engine doesn't fork*, **not**
*anyone can drop in a team.*

## Options considered

- **Design the full team-plugin API now (big-bang).** Rejected — designing from N=1 against four
  seams of provably different shape. This is the exact failure ADR-0032 documents, and the roadmap
  already logs one honest rabbit-hole (four adversarial rounds polishing a static heuristic) whose
  lesson was *escalate to the successor, don't keep guessing*.
- **Fork the engine per team.** Rejected — contradicts the north star ("registering a module, not
  forking the engine") and would duplicate the trust boundary per team, which is how gates drift
  apart. ADR-0034 already had to collapse two drifted policy functions back into one.
- **Generalize the workflow graph first** (it looks like "the" architecture). Rejected — biggest
  lift, hot files, serializes every other session, and it is the seam we understand *least* for
  team #2. Delivery is 39 lines and teaches us more per unit of risk.
- **Let a team declare its own evidence strength / exempt non-code teams from the gate.** Rejected
  emphatically — see *Security implications*. This would make the firm layer a gate bypass.
- **Build editorial as a separate application** that reuses only memory + models. Rejected as the
  *product*, but noted as the honest fallback if the evidence problem proves unsolvable: better two
  honest engines than one dishonest gate. Revisit if step 3 stalls.

## Security implications

- **A team is a trust-boundary participant, not a consumer of one.** It supplies the oracle that
  decides "done," the tools its agents may call, and the destination its output ships to. First-party
  + CODEOWNERS is the control; there is no sandbox for "a team" because a team is not code we run,
  it is code that *decides*.
- **The gate must never be per-team.** The evidence gate (`packages/policies`) stays a single
  chokepoint evaluating a single vocabulary. Teams may extend *what evidence exists*; only the gate
  decides *what evidence suffices*. If a team could weaken the gate, the cheapest team becomes the
  attack path (ADR-0034's lesson: four mechanisms built under an old direction were never
  re-audited, and one composed into a ship with no validator and no reviewer).
- **Opening the `Role` `Literal` widens the allowlist key.** `scoped_tools` is deny-by-default — an
  unlisted role gets `frozenset()` (`allowlist.py:59`). That property must survive the `(team, role)`
  rekey: an unknown *team* must also get zero tools, not fall through to a default. Deny-by-default
  is only a property if it holds on the *new* miss path.
- **Quincy-above-teams is a privilege question, not just a UX one.** A firm-level Quincy that can
  dispatch to any team aggregates every team's capability into one agent. It must hold no tools of
  its own beyond scoping/dispatch, or it becomes the confused deputy for the whole firm.
- **No threat-surface change lands with this ADR** — nothing is built. TM-0001 gets updated by the
  MR that first makes a team seam real (per `AGENTS.md`), not by this one. Recording it here so the
  absence is a decision rather than an oversight.

## Operational implications

- **Zero runtime change. No migration, no knob, no schema.** This ADR is vocabulary + order +
  invariants. It is safe to land against a live system precisely because it changes nothing.
- **Docs-only domain** (`docs/`), disjoint from `#29` (core/memory) and `#30` (api/web) — safe to
  land in parallel per the CLAUDE.md parallel-sessions protocol.
- The extraction steps are individually shippable and individually revertable; step 4 (the graph)
  must be scheduled as an arc **foundation phase** so shared scaffolding is pre-placed and later
  parallel phases don't both edit `build.py`/`state.py`.

## Consequences

**Good.**
- Kills the "`AgentTeam` means the firm is half-built" misreading, in writing.
- Fixes vocabulary before three ADRs and two waves depend on it (ADR-0046/0047 bind to these names).
- Sequences the work so the cheapest, best-positioned seam (delivery, 39 lines) is the teacher, and
  the hot files are touched once, last, with the most information.
- Names the evidence collision **before** it becomes a shipped loophole rather than after.

**Bad / accepted costs.**
- The firm layer stays direction for another wave. `#18`'s framing is reconciled but not realized.
- Deliberately declines to answer "what is the `Team` interface?" — the question most readers will
  arrive with. That is the point, and it will feel like under-delivery until team #2 exists.
- Step 2 reopens ADR-0013's closed `Role` `Literal`; that debate is deferred, not settled.

**Follow-up work (in order; none scheduled by this ADR).**
1. **Solve editorial evidence honestly — the gating prerequisite.** Either (a) a `strength` ladder
   that admits non-executed evidence with honest weighting and a gate that treats it as *weaker*,
   never as `"suite"`; or (b) an editorial oracle that genuinely executes (link-checks, fact-check
   against cited sources, style-guide lint, libel/PII scan are all *deterministic and argv-shaped* —
   the DNA's escalation ladder says try that **first**, before concluding editorial can't execute).
   Option (b) is the deterministic-first answer and should be attempted before (a) is designed.
   **An LLM-judge as the editorial oracle is not evidence** — ADR-0044 made `oracle_verified` a
   *measurement* precisely to kill "the model said it's fine."
2. Extract the `Publisher` protocol + the artifact model behind `deliver_node` (reference impl:
   the existing GitLab MR path).
3. Rekey the tool allowlist to `(team, role)`; argue the `Role` `Literal` reopening on its own MR.
4. Split Quincy-the-firm-interface from Quincy-the-SWE-PM.
5. Only then: the node/edge registry + the `RunState` core/extension split.
6. Revisit third-party teams **only** behind a public-API + untrusted-plugin contract (with
   ADR-0032's community-pack question, which is the same question).

**Honest residual.** This ADR is a plan for a plan. Its whole value is negative — it forbids three
tempting shortcuts (design-from-1, gate-per-team, graph-first) and records why. If the editorial
team never gets an honest oracle, follow-up 1 fails and the firm's second team should be built as a
separate application rather than shipped through a weakened gate. That outcome is acceptable; a
weakened gate is not.
