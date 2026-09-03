# Case study: gearing Quincy (the PM) for success

> **HISTORICAL design study — not current authority.** Its recommendations were largely realized in
> the ADRs it informed (ADR-0008/0009/0010/0011) and the roadmap; kept for design rationale. For
> current direction see [`../architecture/north-star.md`](../architecture/north-star.md).

- Status: design study (not yet an ADR)
- Date: 2026-07-11
- Related: [ADR-0007](../adr/ADR-0007-capability-benchmark-suite.md) (the benchmark), [`docs/audits/mcb-first-run-2026-07-11.md`](../audits/mcb-first-run-2026-07-11.md) (the run that motivated this)

## Thesis

The goal is autonomous whole-project delivery — Mosaera building a complete webapp (UI,
DB, services, dependencies, MCPs, skills) not in one giant run, but by **decomposing a
brief into a dependency-ordered backlog and running each item autonomously.** In that
world the single highest-leverage role is the **PM ("Quincy")**: it decides *what* the
work is, *in what order*, and *what "done" means* for each item. The coder and reviewer
only execute against those decisions.

The first full MCB run makes the case sharply. With a **context-starved** PM (the
benchmark runs it cold), the PM+coder pair still scores **96–100 on focused, backlog-sized
tasks**. So the models are *not* the bottleneck for a well-scoped item — **decomposition
quality and cross-item coherence are.** That is a PM problem. Making Quincy a boss is the
work that unlocks the whole-project vision.

This study maps what Quincy is today, where it is starved, and a concrete, phased plan to
gear it for success — grounded in the current code.

## 1. What the MCB run tells us (the evidence base)

From [the first run](../audits/mcb-first-run-2026-07-11.md):

- **Per-item execution is strong.** moderate tier 98; every moderate feature/robustness
  case hit 100; real hidden graders, real solves.
- **The ceiling is reasoning-hard + discipline**, not basic capability: refactor-hard and
  feature-hard sit at ~90–93; the two failures were a *half-finished refactor the reviewer
  over-approved* (MCB-05) and *thrashing on a subtle left-associativity edge with a debris
  field of scratch files* (MCB-11).
- **The PM ran blind.** The benchmark harness passes only the brief — no repo context, no
  memory. That the pair still scores 96–100 tells us: for small items the starved PM is
  survivable; for a **whole project** (dozens of items, dependencies, a growing
  architecture) a blind PM cannot decompose or sequence well. The starvation is the wall.

Two concrete lessons the failures hand to the PM:
- MCB-11's `8/2/2` edge is exactly the kind of constraint a good PM states explicitly in
  the acceptance criteria ("division is left-associative"). **Sharp, testable acceptance
  prevents thrashing.**
- MCB-05's "refactor *in* `checkout.py`, keep the orchestrator short" is a structural
  constraint the PM should restate and the reviewer should verify. **Ambiguous "done"
  invites half-finished work and over-approval.**

## 2. What Quincy is today (grounded map)

### 2.1 The in-run planner is tool-less and near-blind

- **Model:** `get_chat_model("pm", …)` → default **`gpt-oss:20b`**, temp 0.2
  (`config.py:373`, `models.py:25`). Same model as the reviewer.
- **Plan stage** (`plan_node` → `pm.plan_task`, `graph.py:228`, `pm.py:264`): the planner
  sees the task, an optional project-context block, a **flat file *listing* (≤120 names, no
  contents)** (`graph.py:204-214`), and accumulated feedback. It emits a **free-text 3–6
  step plan**. It has **no tools** — it cannot open a file, grep, or list beyond the 120
  names handed to it.
- **Design stage** (`design_node` → `pm.design_item`, `graph.py:235`, `pm.py:293`): the one
  place real code is read — but the file selection is **deterministic string-matching**
  (`plan_named_files`, `graph.py:99-133`): it keeps files whose names appear in the plan
  text, reads **≤6 files, ≤3000 chars each**. The model does not choose what to read; it
  gets whatever the plan happened to name.
- **The tools already exist but are unwired.** `ROLE_TOOL_ALLOWLIST` declares
  `"pm": {list_files, read_file, search}` ("PM plans; it may look but not touch",
  `allowlist.py:27`) — but nothing ever calls `scoped_tools("pm", …)` or builds a PM agent.
  **The planner is allowed to look and simply never does.**

### 2.2 Memory is rich on paper, starved in the planning path

- Postgres + pgvector persists a lot: `runs`, `decisions` (plan/design/review/gate/…),
  `repo_changes` (full diffs), `test_results`, `artifacts` **with 768-dim embeddings**,
  `run_events`, and a `backlog_items` table **with a self-referential dependency edge
  table** (`models.py`, migration 0005).
- **The semantic-recall path is dead code.** Every run embeds its diff and task+plan
  (`persist.py:111-119`), but the only cosine-similarity reader, `similar_artifacts`
  (`store.py:1481`), has **exactly one caller: a unit test.** No agent, node, or route ever
  queries it. There is no "find the 3 most similar past changes" in any live path.
- **Cross-run context is a shallow SQL digest.** `project_history` (`store.py:928`) returns
  the last 8 **APPROVED** items' title + coder summary + changed *file paths* — no diffs, no
  decisions, no reviewer objections, and **failed/incomplete attempts are dropped** (the
  "we tried this and it didn't work" signal never reaches a later plan).
- **Conventions are invisible to planning.** `CLAUDE.md`, `AGENTS.md`,
  `coding-standards.md` exist as files but are never loaded into any planner prompt.
- **CLI and benchmark runs are fully cold** — only the API `factory.py` builds
  `project_context`, so `cli.py`/`harness.py` plan on task + 120 names and nothing else.

### 2.3 The backlog/autonomy skeleton is already built

This is the good news — the *plumbing* for the vision largely exists:

- **A real, persisted, dependency-aware backlog** (`BacklogItem` + `backlog_item_dependencies`,
  cycle validation), ordered by `position`, with a `todo→in_progress→in_review→done`
  lifecycle.
- **`decompose_brief`** (`pm.py:143`) turns a brief into an ordered set of 3–8
  `{title, description, acceptance}` items.
- **An autonomous chaining sweep** (`advance_project`/`_after`, `context.py:394,288`): picks
  the next unblocked `todo` item, runs it in its own governed graph on the **project's
  persistent clone** (so the repo grows across items), auto-resolves the gate via
  `autonomous_resolution` (deny-by-default; parks on any blocking evidence), and chains only
  on clean+approved delivery.
- **Within-item re-planning** on gate-deny with accumulating feedback.

**The gaps are "intelligence," not plumbing:** `decompose_brief` emits a flat list with **no
dependency edges** (the DAG must be authored by hand); there is **no re-planning *between*
items** (the sweep runs a static list and pauses to a human on any hiccup); there are **no
integration/e2e items**; and there is **no whole-project verification** terminal step.

## 3. What a "boss" PM needs — and the plan to get there

Five upgrades, ordered by ROI. Each is tied to the deterministic-first DNA: give the model
*sight and memory*, but keep everything code can do deterministic (the module map, the
dependency validation, the context assembly).

### Phase 1 — Give Quincy eyes (highest ROI, cheapest)

The planner should **read before it plans**, not guess from 120 filenames.

1. **Wire the already-declared PM tools.** Build the plan/design stage as a
   `create_agent` with the read-only allowlist that *already exists*
   (`{list_files, read_file, search}`, `allowlist.py:27`) — mirroring how the reviewer is
   built. Let the PM explore the repo (search for a symbol, open the module it will extend)
   before writing the plan. This is the single biggest lever and most of the wiring is
   already present.
2. **Put file *contents*, not just names, at plan time** for the files the task obviously
   touches — extend the design-stage grounding to the plan stage.
3. **Load conventions into the planner prompt** (`CLAUDE.md`/`coding-standards.md` excerpts)
   so plans conform to house style from the first step.
4. **BYOM a strong planner model.** Planning is called **rarely** (once per item, plus
   re-plans) vs the coder (every edit), so putting a large/cloud reasoning model **only on
   the `pm` role** is cheap and high-leverage — and it is a one-line config change through
   the `get_chat_model` seam (`role_providers`/`pm_model`). This directly attacks the
   reasoning-hard ceiling (the MCB-11 class of problem) at the point of most leverage.

### Phase 2 — Give Quincy memory (activate what's already persisted)

5. **Turn on semantic recall.** Wire `similar_artifacts` (already built, already fed by the
   embedding pipeline) into planning: "here are the 3 most similar past changes and how they
   were done." Dead code → live capability.
6. **Feed prior decisions and *failures*, not just approved summaries.** Surface prior
   `design`/`review`/`gate` decisions and — critically — `INCOMPLETE`/`capability_limit`
   attempts, so the PM learns from what didn't work instead of only what shipped.
7. **A durable module/architecture map** (deterministic — a symbol/dependency index, not an
   LLM call) so the PM knows what modules exist and how they connect, beyond a 120-name list.
8. **Persist architecture decisions as first-class memory** the PM reads back (ADR-style
   "why we chose X"), so cross-item coherence has a source of truth.

### Phase 3 — Make decomposition intelligent

9. **Emit the dependency DAG from `decompose_brief`.** The edge table and cycle validation
   already exist; have the PM output `depends_on` per item instead of a hand-authored step.
   True dependency ordering, generated.
10. **Sharp, testable acceptance criteria.** The MCB-11 lesson: acceptance that names the
    edge cases ("division is left-associative: `8/2/2==2`") turns a thrashing coder into a
    targeted one. Make acceptance criteria explicit, testable assertions — the same shape as
    an MCB grader.
11. **Generate integration/e2e items**, not only "independently testable" units — the pieces
    of a webapp are correct only when they work together.

### Phase 4 — Intelligence *between* items

12. **A re-planning step in the sweep.** After each item, let the PM revise the remaining
    backlog: insert follow-ups, re-prioritize, adjust scope based on what actually got built
    (and what failed) — instead of a static positional list that pauses on any hiccup.
13. **A whole-project verification terminal step** — when the backlog is exhausted, an
    autonomous "assemble and verify the whole project" run, rather than stopping at
    per-item `in_review`.

## 4. How to measure Quincy (don't extrapolate — benchmark it)

Apply the same discipline the MCB just brought to capabilities, one level up. Add a
**project-scale benchmark track**:

- **Integration cases:** seed a repo mid-project, hand Quincy the next item, and grade
  whether the delivered change *integrates* (an e2e grader, not a unit grader).
- **Trajectory cases:** give Quincy a mini-app brief, let it decompose → sequence → run the
  backlog autonomously, and grade the **whole trajectory**: did it converge to a working
  app, in how many items, with how much drift/rework, and did the dependency ordering hold.

That is how you get a *true grasp* of the autonomous-whole-project ceiling instead of
extrapolating it from per-item scores — the exact move that turned the 2-case MCB into a
20-case capability read.

## 5. Trade-offs and guardrails

- **Latency:** PM tool use and a bigger PM model add latency — but planning is off the
  interactive hot path and infrequent (once per item), so this respects the "never block the
  interactive path on a model call" principle. The coder stays on the fast local model.
- **Cost:** a large PM model is affordable precisely because of its low call volume;
  optimize cost per *delivered outcome*, not per call (ADR-0002).
- **Deterministic-first:** the module map, dependency validation, context assembly, and
  convention loading are **code**, not model calls — the LLM earns its place only for
  decomposition, exploration, and re-planning judgment.
- **Over-decomposition / runaway backlog:** re-planning must be bounded (budget + a cap on
  auto-inserted items) so the sweep converges rather than sprawls.

## 6. Recommended first move

> **Status update (2026-07-11): Phase 1 shipped.** All four seams below plus the doctrine
> and foresight upgrades landed as four stacked MRs, recorded in
> [ADR-0008](../adr/ADR-0008-pm-foundation.md). Notably, verification found
> `deepseek-r1:32b` cannot tool-call on Ollama, so the PM default stays `gpt-oss:20b`
> (a reasoner that also tool-calls) and the stronger-model path is a cloud binding via
> BYOM. The remaining depth (semantic doctrine retrieval, dependency-DAG generation,
> between-item re-planning, a dedicated foresight node) is the deferred follow-on.


**Phase 1, items 1 + 4:** wire the already-declared PM read-only tools (make Quincy an agent
that reads before it plans) and BYOM a strong reasoning model onto the `pm` role. Together
they are a small, mostly-already-present change that attacks both starvation (sight) and the
reasoning ceiling (model) at the highest-leverage point — then re-run the MCB (and a first
project-scale case) to measure the delta. Everything else builds on eyes + a brain.
