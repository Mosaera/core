# Mosaera — Project Brief

A short, durable statement of *what Mosaera is and who it is for*. It intentionally omits anything
that dates quickly — roadmap, pricing, packaging, model or hardware choices, and architecture — each
of which has an authoritative home: **why/direction** → `docs/architecture/north-star.md`; **what
exists** → the repository + `docs/architecture/README.md`; **decisions** → `docs/adr/`; **sequence**
→ `docs/roadmap.md`.

## Mission

Build **governed AI execution systems** that autonomously deliver real work while remaining
**deterministic, auditable, and accountable** — capability comes from the harness (orchestration,
evidence, policy, memory), not from any single model.

## Vision

Replace isolated AI assistants with **governed AI organizations** — teams of specialized
accountabilities operating under explicit authority, evidence, and policy. Users hire governed teams
while retaining full control of the models, memory, tools, repositories, and approvals.

**Mosaera improves capability by adding independent control points, not additional autonomous
agents.** Everything else follows from that.

## Problem

Today's AI coding tools are a `PM → coder → reviewer` line that ships on a model's say-so. They
self-report "done," review code rather than *claims*, and provide **no governed chain of authority
explaining why a delivery was permitted**. That is unacceptable wherever code is valuable, regulated,
or hard to reverse.

## Current product

**Mosaera Lite** — an autonomous **software-delivery team**: it takes a software issue, plans it,
implements on an **isolated clone**, validates in a sandbox, reviews the result against acceptance
criteria, and produces a **governed delivery record** (a reviewable merge request with its evidence)
— pausing at human approval gates. It either delivers correct, reviewable work **or honestly
refuses**. The software-engineering team is the first and hardest; it is the proving ground for the
wider firm.

## Target users

- Open-source maintainers and individual power users who want self-hosted autonomy.
- Startups and engineering teams that want governed automation without building a platform.
- Security-conscious and regulated organizations that must keep source, evidence, and control local.

## Core principles

- **Control Points, not Headcount** — quality comes from independent, evidence-backed control points, not more agents.
- **Evidence-Gated Advancement** — review *claims*, not code; nothing advances without tool-backed evidence per acceptance criterion.
- **Deterministic Final Authority** — a model may propose or analyze; it never issues the final release clearance.
- **Honest Parking** — the system delivers cleanly or parks with a reason; it never dresses non-delivery as done.
- **Artifact-Centric Execution** — decisions and evidence are versioned artifacts, not free-form chat; the result is institutional memory.
- **Governed & auditable** — scoped tools, a delivery evidence gate, a tamper-evident trail; autonomy is *granted*, never assumed.
- **Local-first & user-controlled** — runs on your infrastructure; you keep control of the models, memory, tools, repositories, and data (any role, any provider).

## Success

Users confidently delegate **meaningful engineering work** because every advancement is **governed,
auditable, reproducible, and reviewable** — and the system refuses work it cannot prove.

## Out of scope

- Replacing engineers (Mosaera is a governed teammate, not a headcount substitute).
- Autonomous production deployment (Mosaera delivers a reviewed artifact; operating what it ships is a future, posture-gated direction).
- Unrestricted self-modification.
- Opaque reasoning — every advancement is backed by inspectable evidence.
