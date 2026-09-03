# North Star — The Mosaera Blueprint

This document defines Mosaera's **enduring purpose, architectural direction, and non-negotiable
boundaries**. It is the durable architectural **constitution**. It is not a source of implementation truth or
issue status, and not the agent execution contract — that is `CLAUDE.md`.

- The repository and `docs/architecture/README.md` describe **what currently exists**.
- `docs/adr/` contains **binding architectural decisions**.
- `docs/roadmap.md` defines **approved build order and current status**.
- The tests and the repository determine **what is true right now**.

When this document describes an unbuilt capability it is **DIRECTION** — it does not authorize
*production implementation*. Research, documentation, prototypes, and ADR proposals in support of a
future capability are still legitimate, but they too require explicit issue scope. This document
determines what the system should *become*; the repository determines what it *is*.

> **Mosaera is a framework for operating an autonomous AI firm.** Its first team — software
> engineering — is **not** a PM-to-coder pipeline and **not** a swarm of conversational agents. It is
> a **governed decision engine with institutional memory**, modeled on the control structure of an
> elite engineering organization and compressed into a small number of explicit accountabilities.
> Work advances through **versioned artifacts, independent control points, and tool-backed
> evidence**. Models may propose, analyze, and implement; they do not approve their own work,
> manufacture proof, or act as the final release authority. **The intelligence belongs to the
> harness** — orchestration, artifacts, retrieval, tools, policy, verification, memory. Models remain
> replaceable.

---

## How an agent must apply this

The **execution contract** — the authority order, the pre-change checklist, the implementation test, the decision rules, and the completion report (`clean_deliver` / `honest_park`) — lives in `CLAUDE.md`. This document states the *principles*; `CLAUDE.md` says how an agent must *act* on them.

## The reframe — why this is not another coding-agent framework


Most frameworks build `PM → Coder → Reviewer → Done`. That is not how elite organizations work, and
it is why those systems plateau. Three shifts define Mosaera instead — each is a named invariant
below:

1. **A governed decision engine, not a code generator.** Work flows through decisions with
   accountability and independent approval, not a hand-off queue. → *Independent Approval*.
2. **Review claims, not code.** When the engineer says "complete," the validator says **"prove it"** —
   advancement is gated on *evidence per acceptance criterion*, never on a completion narrative.
   Mosaera's founding instinct, "prove at the door," generalized to the whole org. → *Evidence-Gated
   Advancement*.
3. **Orchestrate artifacts, not agents.** Agents read, update, approve, reject, and **version a chain
   of engineering artifacts** — not free-form chat. The intelligence lives in the harness, which is
   what makes Mosaera model-agnostic and gives it institutional memory. **The defining bet.** →
   *Artifact-Centric Execution*.

## What Mosaera is for — the operator's product (owner-stated, 2026-08-02)

Mosaera is not only an auditable execution harness. It is a **guardrail for industry-standard
software engineering practice** — it should make it *difficult* to produce spaghetti code, weak
infrastructure, poorly designed environments, or projects that cannot scale. Many firms have no
strong engineering background: they don't know how to write an ADR, establish coding standards,
choose a stack, structure a repository, design scalable infrastructure, or build the
project-management process around the work. **Proven practice is built into the workflow, not
assumed of the user.**

The target is a **complete senior engineering team that can take a project from zero to
flagship** — project management, work-item decomposition, architecture, scaffolding, security,
infrastructure, testing, long-term scalability — including the judgment calls: when to recommend a
pivot, when foundational work must be corrected, and what has to change for the next stage to
succeed.

- **Greenfield:** establish the correct foundation from the beginning, so the product is secure,
  maintainable, scalable, and production-ready — not merely "working". *(DIRECTION beyond the
  current scaffolding path.)*
- **Brownfield:** assess the current state, guide the operator through the refactoring that brings
  the project up to standard — and when the foundation is too weak or costly to repair, **say so**,
  with the professional case for rebuilding. Honest parking, applied to whole codebases.
  *(DIRECTION; the recon/onboarding map is the seed.)*

**Quincy is the firm's face.** The operator collaborates with Quincy the way a founder works with
a trusted senior partner — iteratively, with a human in the loop directing the work — but with
every important decision, assumption, work item, and outcome **auditable**. The flagship product
is not full autonomy; it is **governed collaboration**: autonomous stretches between human
touchpoints, each stretch held to the same evidence standard.

As a project develops, Quincy **continuously learns it** — architecture, history, standards,
constraints, product direction — and answers from **recorded truth, never guesswork**: *"it works
this way because this decision was made, this alternative was rejected, and these were the
reasons."* That grounded institutional knowledge is a core deliverable, and it is why the defining
bet above (artifacts, not chat) matters: the decision chain Quincy cites **is** the artifact
chain. *(DIRECTION: the charter/map/doctrine stores and the claim ledger are the substrate; the
answering capability is unbuilt.)*

## Non-negotiable DNA


Enduring, uniquely-named invariants. Reason from the **named rule**, not from prose restatements of
it. Markers: **MUST** = enforced invariant · **SHOULD** = preferred unless evidence supports
otherwise · **DIRECTION** = intended future state, not implementation authorization.

| Invariant | Rule | Strength |
|---|---|---|
| **Deterministic-First** | Cached evidence / deterministic tools before an LLM; a model call must earn its place. ([ADR-0002](../adr/ADR-0002-deterministic-first-and-model-agnostic.md)) | SHOULD (default), MUST on the interactive/verification path |
| **Model Substitutability** | All model access through one seam (`get_chat_model`); no provider hardwired; the workflow must function if the provider changes. | MUST |
| **Independent Approval** | No producer approves its own output. Independence comes from **control pathways and deterministic gates**, not from asking two prompts to behave independently. Separate models or prompts add *diversity* but do **not** establish independence unless *evidence ownership* and *decision authority* are also separated. | MUST |
| **Evidence-Gated Advancement** | A stage advances only on **tool-backed evidence** per acceptance criterion. "Done" is asserted by one accountability and *proven* by another. | MUST |
| **Deterministic Final Authority** | The delivery gate is deterministic. A model may author, analyze, or propose — **never issue the final release clearance**. (The ADR-0070 dead-end.) | MUST |
| **Honest Parking** | The engine emits `clean_deliver` **or** `honest_park(reason)`; it never dresses non-delivery as done. Evidence is *measured*, not asserted. ([ADR-0006](../adr/ADR-0006-durable-transcript-and-honest-outcomes.md)) | MUST |
| **Capability through Auditability** | Safety = containment (the sandbox wall) + traceability (a tamper-evident audit log) + verification (prove the output at the door) — **never** process-restriction. Free inside the wall, logged throughout, proven at the door. ([ADR-0063](../adr/ADR-0063-capability-through-auditability.md)) | MUST |
| **Artifact-Centric Execution** | Decisions, claims, and evidence are **versioned artifacts**, not chat. No unstored decision counts; no uncited artifact is current truth; no task is done without tool-backed evidence. | MUST (target); partially built (see *Where we are today*) |
| **Unsuppressible Ask** | The channel that carries a question to the operator is never gated by the policy governing whether work may **ship**. A control may refuse to act; it may not refuse to speak. Any suppression of the ask is itself recorded and visible. ([ADR-0107](../adr/ADR-0107-decision-specific-admission.md)) | MUST |
| **Control Points, not Headcount** | Scale quality by adding independent, evidence-backed **control points** (a domain veto = a gate + evidence adapter), not by multiplying LLM agents. | MUST |

## The accountabilities (the minimal SWE organization)


The first credible SWE organization requires **six explicit accountabilities**. They may be realized
as model agents, deterministic gates, human authorities, or combinations — but **none may disappear
merely because two are backed by the same model** (*Control Points, not Headcount*; *Independent
Approval*). The number is not the eternal constraint; the **six independent decision functions** are:
product intent, technical architecture, security/risk, implementation, independent validation, final
authorization.

```
USER → QUINCY (what & why) → { ATLAS (how) ⇄ SENTINEL (risk, VETO) }
     → FORGE (build) → ROOK (prove it, VETO) → HUMAN (authorize, posture-scaled)
     → release → telemetry → Quincy opens the next backlog        (loop)
```

| Accountability | Owns (decision right) | Never does |
|---|---|---|
| **Quincy** — Product | **Outcome sequencing**: business priority, PRD, acceptance criteria, release slices, user-visible dependencies, backlog | Doesn't code; doesn't author a *technical* plan that bypasses Atlas; can't waive a security/quality gate |
| **Atlas** — Architecture | **Technical decomposition**: components, interfaces, migration sequence, architectural dependencies, failure boundaries → ADRs + task graph | Doesn't approve release |
| **Sentinel** — Security / Risk | Whether material risk remains — a **veto**. Three identities: **Control** (the deterministic gate, issues clearance), **Accountability** (the broader risk function), **Agent** (optional model analyst — proposes findings, never issues clearance) | The Agent never green-lights (*Deterministic Final Authority*); doesn't implement |
| **Forge** — Engineering | **Execution decomposition** within an approved task; code, tests, docs, and its *producer evidence* | Can't approve its own work; doesn't control *all* evidence generation |
| **Rook** — Independent QA | **Verification decomposition**: whether every acceptance criterion has evidence — a **veto**. Adversarial ("prove Forge wrong") | Doesn't modify code directly |
| **Human** | Final authority (posture-scaled); grants autonomy | Doesn't micromanage |

**Atlas is the clearest gap** — today a design *stage*, not yet an independent architecture control
point with ADRs and a veto. *(This doc states direction, not live build status — current state lives
in [`../roadmap.md`](../roadmap.md) and the repository.)*

**Evidence ownership (so "Forge produces the evidence package" never becomes self-certification):**
*producer evidence* (Forge's own tests, notes, declared changed paths — **never sufficient alone**) ·
*independent evidence* (held-out tests, oracle results, scans, behavioral checks — **not controlled
by Forge**) · *gate decision* (the deterministic delivery gate evaluating completeness) · *Rook
report* (interpretation, adversarial findings, unresolved claims). **MUST:** advancement requires
*independent* evidence, not producer evidence. **MUST — Rook may veto but may not clear:** Rook
rejects or parks on unresolved findings, but only the **deterministic gate** establishes evidence
*completeness*, and the **human** retains final posture-scaled authorization — neither Rook nor any
model grants final clearance (*Deterministic Final Authority*).

## The governed decision loop


A loop, not a line — every stage owns a gate and can send work backward:

```
Goal → Clarify → PRD/Acceptance → Architecture + Threat model → Implementation plan
     → Implement + Evidence → Validate ⇄ Revise (until evidence passes) → Release → Telemetry → next backlog
```

- **Quincy never trusts "Done."** It asks *"does every acceptance criterion now have evidence?"*, not
  *"did Forge finish?"* (*Evidence-Gated Advancement* as a workflow rule.)
- **Forge receives a near-deterministic brief** — architecture + acceptance criteria + threat model +
  standards + repo context + interfaces + definition-of-done + constraints — so the outcome depends
  less on model luck.
- **Rook behaves adversarially** — red-team + regression + integration + perf + static analysis +
  behavior verification (the pattern Mosaera already uses to harden trust-boundary changes).
- **DIRECTION — the operate tail** (release → telemetry → next backlog): the SWE team's charter today
  ends at *deliver a reviewed merge request on an isolated clone* and hands off to the human's CI/CD.
  Full operability (PRR/SLO/canary/rollback/postmortem) is a future **Regulated-posture** arc.

## Orchestrate artifacts, not agents (the defining bet)


The defining architectural choice in Mosaera: agents do not rely on **free-form conversation as the
system of record**; they act through a versioned artifact chain.

```
User Goal → PRD → ADR → Task Graph → Implementation Plan → Source Code
         → Evidence Package → Review Report → Release Decision → Operational Telemetry
```

This is *Artifact-Centric Execution*, and it is why the other invariants hold: it **kills context
drift** (cite the current artifact, not a decaying prompt), makes work **resumable + auditable**
(rehydrate from artifacts; every advance leaves a tamper-evident trail), and makes Mosaera **truly
model-agnostic** (the moat is the harness + schema, not a vendor's weights) — yielding *institutional
memory*.

**MUST — artifact schemas are versioned contracts.** Any breaking change to an artifact's schema,
authority, lifecycle, or compatibility requires an **ADR**, a **migration strategy**, and a
**replay/resumption analysis**. *Who authors* each artifact is the accountability table above; *who
owns its schema and lifecycle* is a governance question for an ADR, not an ad-hoc code change.

**The direction:** promote the run's evidence to a **versioned artifact registry** — the full
PRD→ADR→evidence-package chain as first-class, queryable objects. This is the substrate Quincy, the
firm layer, and risk-scored autonomy need. *(Current build state lives in [`../roadmap.md`](../roadmap.md).)*

## Reaching the elite ceiling — depth without headcount


Fortune-500 caliber is more *specialization, independence, evidence production, and organizational
memory* — **not** more coding capacity. The elite reference (~15 specialties: business analyst, UX,
enterprise/solution architect, data engineer, QA/test architect, platform/SRE, compliance/privacy,
technical writer, standards curator, …) is a **map of accountabilities to keep explicit and
independent**, realized as *control points + artifacts*, never as fifteen chatty LLMs. Genuinely
separate crafts (editorial next) arrive as **teams** in the firm layer, not as more SWE roles.

## Not Yet — do NOT build without an active issue that authorizes it

The generic `Team` plugin API · the full regulated **operate tail** · a 15-agent specialist org ·
automatic **deployment** authority · any **posture-relaxation** mechanism · **conversational
agent-to-agent** messaging · abstractions justified only by hypothetical future teams · a generalized
artifact **platform** before the first artifact-registry use case is proven.

## Standing guardrails (binding constraints on the arcs)


- **No `Team` plugin API until team #2 exists** ([ADR-0045](../adr/ADR-0045-the-firm-teams-as-modules.md) — *extract-from-N, not design-from-1*). `AgentTeam` in the source is the agent bundle, **not** a hireable department. **MUST.**
- **Posture can only tighten, never loosen** ([ADR-0046](../adr/ADR-0046-posture-and-autonomy-governance.md)) — a second veto over the evidence gate, never an override. **MUST.**
- **The map informs scoping; it never reaches the gate** ([ADR-0047](../adr/ADR-0047-project-onboarding-and-the-durable-map.md)) — untrusted, repo-derived, durable: a hypothesis generator, not evidence. **MUST.**
- **Pivotability is foundational** — the posture layer is versioned + control-mapped, so changing regulation slots in without touching the engine. **SHOULD.**

## Where the detail lives


- **Current system:** `docs/architecture/README.md` · **Build order + status:** `docs/roadmap.md`
- **Decisions:** `docs/adr/` (DNA → ADR-0002; oracle → ADR-0044; security gate → ADR-0076; firm →
  ADR-0045; posture → ADR-0046; onboarding → ADR-0047; auditability → ADR-0063)
- **Threat surface:** `docs/threat-models/` · **v1.0 measured bar + benchmark spec:** `docs/roadmap.md` + [ADR-0061](../adr/ADR-0061-v1-measured-definition-of-done.md)

*This document is the authority on enduring direction and invariants. Every
unbuilt capability here — the artifact registry, Atlas as a control point, the firm layer, posture
governance, the operate tail — is **DIRECTION** except where a status tag marks a piece
Implemented/Enforced/Tested. The repository decides what is true.*
