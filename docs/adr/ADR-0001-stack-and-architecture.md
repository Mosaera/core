# ADR-0001: Core stack and architecture for Mosaera

- Status: accepted
- Date: 2026-07-02
- Owners: Alejandro Rengifo
- Related issue: — (pre-issue-tracker; founding decision)
- Related threat model: TM-0001-mosaera-lite-repo-agent
- Superseded in part by: [ADR-0102](ADR-0102-delivery-spine-truth-up.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.

## Context

Mosaera is a self-hosted, model-agnostic AI team orchestration platform. The first
vertical (Mosaera Lite) is a PM → Coder → Reviewer loop that safely operates on a
cloned repository behind a human approval gate. We need to fix the core language,
repo shape, orchestration substrate, inference strategy, and dev environment before
writing code, because these decisions are expensive to reverse.

## Decision

1. **Core language: Python** (single-language core; TypeScript reserved for the
   future `apps/web` dashboard behind a REST seam; Go/Rust only later for a specific
   profiled hot component as an isolated service — never the core).
2. **Repo shape: Python monorepo** (`apps/`, `packages/`, `infra/`, `docs/`) managed
   as a **uv workspace**, with a root `Makefile` as the language-agnostic command
   contract (`bootstrap`, `fmt-check`, `lint`, `typecheck`, `test`, `build`, `run`)
   implemented over `uv` + `ruff` + `mypy` + `pytest`.
3. **Orchestration: LangGraph** (`StateGraph` + checkpointing + `interrupt` for
   human-in-the-loop) with **LangChain** `create_agent` for agent roles.
4. **Inference: local-only Ollama for the MVP** — PM/Reviewer: `gpt-oss:20b`;
   Coder: `qwen3-coder:30b` (coding-tuned, tool-capable variant of the planned
   `qwen3:30b`); embeddings: `nomic-embed-text`. The model gateway
   (`packages/core/mosaera_core/models.py`) is a thin role→model factory so a
   provider router (LiteLLM proxy / API escalation) can drop in later without
   rework. Ollama base URL is configurable (Windows host or WSL2).
   **Delivered (BYOM #21):** the anticipated provider router is realized — a role
   now maps to a `(provider, model)` binding and `get_chat_model` dispatches
   through LangChain's `init_chat_model`, so any installed provider (Ollama,
   OpenAI/-compatible, Anthropic) backs any role, keys stored server-side and
   admin-gated. Ollama stays the default → local-first is unchanged. Agents and
   the orchestrator were untouched, confirming the seam. See TM-0001 for the
   provider-key and model-egress threats this adds.
5. **Dev environment: WSL2 (Ubuntu)** — production parity (Mosaera ships as
   Docker/Linux), Docker sandbox workers are Linux-native, vLLM (roadmap) is
   Linux-only, and CUDA reaches the RTX 5090 via WSL2 passthrough.
6. **Persistence: per-run state only in this slice** — LangGraph SQLite checkpoints
   and a delivery-report file under `.mosaera/`. Durable cross-session memory
   (Postgres + pgvector) is the next plan.
7. **Sandboxing: interface-first** — `SandboxWorker` abstraction with a subprocess
   implementation (workspace-restricted cwd, scrubbed environment, timeouts,
   best-effort network isolation via `unshare -rn` on Linux). Immediate follow-up:
   Docker-backed implementation from `infra/docker/`.

## Options considered

- **TypeScript core** — rejected: LangGraph's TS port trails the Python one and the
  gravity well of the hard problems (vLLM, LiteLLM, LangGraph HITL, the OpenHands
  reference ecosystem) is Python. TS stays for the web dashboard.
- **Web dashboard framework: Vite + React SPA** (not Next.js, which this ADR loosely
  reserved). `apps/web` is a static client-rendered bundle served by the FastAPI service
  (`StaticFiles`) at the same origin — one runtime in production, no CORS, and clean
  air-gap packaging, which matters for the self-hosted/Gov tiers. Next.js's strengths
  (SSR/SEO, server components, token-streaming via the Vercel AI SDK) don't apply to an
  authenticated, API-driven dashboard that streams run events over SSE; its cost (a Node
  runtime beside Python in every deployment) does. Live run state comes from the API's
  in-memory `RunSession`; run history is read from Postgres memory via `/history`.
- **Go/Rust core** — rejected for MVP: no profiled hot path yet; ecosystem cost
  dominates. Reserved for isolated services later.
- **Windows-native dev** — rejected: sandbox workers and vLLM are Linux-native;
  bootstrap commands are Unix-first. Code still runs on Windows for convenience.
- **Multi-provider gateway now (LiteLLM)** — initially deferred (local-only Ollama
  was enough for the slice); **now delivered** as BYOM #21 via `init_chat_model`
  through the same `get_chat_model(role)` seam, no LiteLLM proxy needed.
- **Postgres/pgvector** — initially deferred to keep the first slice lean; **now
  delivered** (`packages/memory`, opt-in via `MOSAERA_DB_URL`). Runs persist durably
  and LangGraph checkpoints move to Postgres for cross-session resumability; SQLite
  remains the zero-config default. **Alembic now manages the schema**
  (`packages/memory/mosaera_memory/migrations/`, head `0028`; ~~`0007`~~ **corrected 2026-08-18** — the pin was a snapshot,
  not a decision, and the head advances with the schema, see `docs/audits/adr-corpus-review-2026-08-18.md`) — schema changes ship as
  migrations, never hand-rolled `ALTER`/`create_all`.

## Security implications

- Agents only ever touch **clones** under `.mosaera/workspaces/<run-id>/`; writes are
  path-guarded to the clone. The source repo is never modified.
- Deny-by-default tool allowlist and a human approval gate live in
  `packages/policies/` (CODEOWNERS-protected).
- Sandbox: `DockerSandbox` is now the default (throwaway container, `--network none`,
  read-only root, non-root user, resource caps, single `/work` mount) — real
  containment for untrusted test code. `SubprocessSandbox` (cwd/env/timeout,
  `unshare -rn`) remains the no-Docker fallback via `--sandbox subprocess`. The
  `SandboxWorker` seam made this an additive second implementation. TM-0001's
  "malicious test code" residual drops from medium-high to low under Docker.
- Repo content processed by models is untrusted input (prompt-injection surface);
  mitigations in TM-0001.

## Operational implications

- Ollama must be reachable from WSL2 (configurable base URL; runbook in
  `docs/onboarding/`).
- Single-GPU role multiplexing: agents run sequentially, one model active at a time.
- Rollback: each decision above is a seam (gateway, sandbox, checkpointer), so
  replacements are additive, not rewrites.

## Consequences

- Good: fastest path to a working governed loop; every later component (Docker
  sandbox, LiteLLM, Postgres memory, FastAPI/web) has a prepared seam.
- Bad: no durable cross-session memory yet; subprocess sandbox is weaker than the
  target Docker sandbox; Windows host + WSL2 adds one networking hop to Ollama.
- Delivered since: Docker sandbox worker, Postgres/pgvector memory, security
  scanners (Gitleaks concrete; Semgrep/Trivy same-interface follow-ups) feeding the
  Reviewer/report/memory, a GitHub draft-PR connector (`packages/connectors`), and a
  FastAPI service (`apps/api`) that submits runs, streams progress (SSE), and resolves
  approval gates over HTTP — the REST/SSE seam for the future web dashboard.
- Follow-up: ~~Semgrep/Trivy scanners, `apps/web` dashboard, live PR flow in CI, and a
  server-lifetime Postgres checkpointer for cross-restart run resumption.~~
  **Corrected 2026-08-18** (`docs/audits/adr-corpus-review-2026-08-18.md`) — three of the four shipped.
  Delivered since: Semgrep (`infra/semgrep-rules/python-security.yml`, registry in
  `packages/core/mosaera_core/tools/scan.py`), the `apps/web` dashboard, and the server-lifetime
  PostgresSaver (`apps/api/mosaera_api/factory.py`). Still open: **Trivy** (SCA/deps — the `scan.py`
  registry documents the seam) and the live PR flow in CI.
