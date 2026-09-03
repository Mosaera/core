# ADR-0008: PM foundation — tool-using planner, doctrine, actuated foresight

- Status: accepted
- Date: 2026-07-11
- Owners: Alejandro Rengifo
- Related: [ADR-0007](ADR-0007-capability-benchmark-suite.md) (the benchmark that motivated this), [`docs/design/quincy-pm-case-study.md`](../design/quincy-pm-case-study.md) (the case study this implements)

## Context

The first full MCB run ([`docs/audits/mcb-first-run-2026-07-11.md`](../audits/mcb-first-run-2026-07-11.md))
showed the models execute focused, backlog-sized tasks at 96–100 **even though the
planner ran cold** — so for autonomous whole-project delivery the bottleneck is the
**PM ("Quincy")** (decomposition, cross-item coherence, foresight), not the coder. The
case study mapped a starved planner: tool-less, seeing only a 120-name file listing, no
doctrine, no memory — while a per-role model seam and a PM read-only tool allowlist
*already existed unwired*. This ADR records the foundation ("Phase 1") that makes the PM
capable, delivered as four stacked MRs.

## Decision

Four seams, each a minimal first implementation with depth deferred:

**1. EYES — a tool-using planner.** `plan`/`design` now run as compiled agents with the
read-only repo tools (`list_files`, `read_file`, `search` — the PM allowlist already
existed, no policy change), built by `build_pm_agent` (a transplant of the reviewer's
agent factory) and invoked via `plan_with_agent`/`design_with_agent` (mirroring
`review_change`). The planner reads the actual code before it writes, instead of
guessing from a filename list. The old prompt-only `plan_task`/`design_item` remain as a
no-tool fallback. The deterministic design-grounding is trimmed (6×3000→4×2000 chars)
because the PM now reads on demand — keeping net planner context roughly flat.

**2. BRAIN — the per-role model seam.** The stronger-model path already exists (BYOM:
`role_providers`/`pm_model`). We **verified** that `deepseek-r1:32b` — the strongest
local reasoner on the endpoint — **does not emit tool calls on Ollama**, which is
incompatible with EYES, whereas `gpt-oss:20b` (a reasoning-family model) tool-calls
reliably. So the PM default **stays `gpt-oss:20b`** (reasoner *and* tool-caller); a
stronger PM comes from a **cloud reasoning model** via the existing seam
(`MOSAERA_PROVIDER_PM` + `MOSAERA_MODEL_PM`), not a local swap. Added a `pm_step_limit`
knob bounding the planner's read-tool loop.

**3. DOCTRINE — a corpus the PM follows.** A curated **global** baseline
(`mosaera_core/doctrine/`: methodology, decomposition, acceptance-criteria, pitfalls;
`core.md` is the compact always-on distillation) is injected into `planning_overview`
as a trusted `## Doctrine` block — reaching both plan and design — with framing that
marks it **trusted guidance to follow**, the inverse of the untrusted-data framing used
for repo files and attachments. A **per-project** channel loads project reference
material (academic/research/house standards) into `build_run_context`. A
`doctrine_chunks` table (scope `global`|`project`, with an embedding column) plus a
`similar_doctrine` query are the **seam for later semantic retrieval** of a large corpus
— defined now, wired later. A `doctrine_enabled` kill-switch drops the block for a
tiny-context model.

**4. FORESIGHT — actuated pre-mortem.** The design's inert "Risks" prose becomes a
closed loop: `DESIGN_SYSTEM` demands a `## Risks & mitigations` section of
`RISK → MITIGATION → CHECK` lines; the graph extracts it into a `foresight` state field,
appends the mitigations to the coder's instruction as build requirements, and threads it
to the reviewer, whose prompt now REQUEST_CHANGES when a claimed mitigation's CHECK
doesn't hold. This directly targets the MCB-05 failure (a reviewer over-approving
not-quite-done work).

## Options considered

- **Default the PM to `deepseek-r1:32b`.** Rejected after empirical verification — it
  doesn't tool-call on Ollama, which would defeat EYES. Kept as an opt-in reasoning
  binding for no-tool paths.
- **A dedicated `foresight` node** between design→implement. Deferred: it adds a model
  call and context weight, and a tool-using PM already reads the risky files while
  designing. The seam (a `foresight` state field + two consumers) makes the node a
  drop-in follow-up.
- **Full RAG doctrine now** (embed + ANN index). Deferred to keep the foundation
  focused; the table + `similar_doctrine` seam are laid so it's a drop-in.
- **Reuse the attachment channel for doctrine.** Rejected — attachments are framed as
  *untrusted data*; doctrine to be *followed* needs trusted framing and its own path.

## Security implications

Low, net-positive. The PM's tools are **read-only** and use the pre-existing allowlist
(no permission widening; the trust boundary in `packages/policies` is untouched).
Doctrine flows only through trusted, code-assembled strings with explicit trusted
framing; untrusted repo/attachment content keeps its untrusted framing, so the
injection does not blur the data/instruction boundary (TM-0001). The global doctrine is
stdlib text on disk (no DB dependency, no egress). The reviewer's new CHECK-verification
only *tightens* the gate.

## Operational implications

- **PM model:** `gpt-oss:20b` default; point at a cloud reasoner via the BYOM env vars
  when desired. Reasoning-family chain-of-thought is routed off-prompt, so it doesn't
  consume the context window.
- **Knobs:** `pm_step_limit` (~~default 12~~ **default 20** — `config/_knobs.py`; raised after this
  decision, corrected 2026-08-18, `docs/audits/adr-corpus-review-2026-08-18.md`), `doctrine_enabled` (default on) — both in
  `GENERAL_KNOBS`/Settings; `doctrine_enabled` is a budget kill-switch for small models.
- **Migration:** Alembic `0008` adds `doctrine_chunks`. Per-project doctrine is seeded
  via `add_doctrine_chunk` (an admin/curation surface lands later); with no DB it
  degrades to empty.
- **Context budget:** the grounding trim offsets the doctrine block; every block is
  hard-capped; net planner context stays ~flat under the 16k local window.

## Consequences

The planner now reads before it writes, follows an explicit doctrine, and anticipates
pitfalls that the coder must build against and the reviewer must verify. This is the
foundation for the deferred depth — semantic doctrine retrieval, PM-generated dependency
DAGs, between-item re-planning, and a dedicated foresight node — each of which now has a
seam to land into. The delta is measured against the committed MCB baselines (re-running
the two "wall" cases MCB-05/MCB-11), and the true one-shot-whole-project ceiling will be
measured by the project-scale benchmark track proposed in the case study.
