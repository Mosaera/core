# apps/api — Mosaera HTTP API

FastAPI service wrapping the orchestrator. Submit a run, stream progress (SSE),
and resolve the human approval gates over HTTP instead of stdin. Reuses the same
`build_graph` orchestrator as the CLI; the CLI remains fully functional.

## Run

```bash
uv run mosaera-api            # 127.0.0.1:8000 (MOSAERA_API_HOST / MOSAERA_API_PORT)
```

Configuration is the same env as the CLI (`MOSAERA_SANDBOX`, `MOSAERA_DB_URL`,
`MOSAERA_OLLAMA_BASE_URL`, …) — see `docs/onboarding/`.

## Endpoints

App endpoints live under `/api` (top-level paths belong to the SPA router).

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | liveness |
| POST | `/api/runs` | submit `{repo, task, max_iterations?, scan?, sandbox?}` → run snapshot |
| GET | `/api/runs` | list run ids |
| GET | `/api/runs/{id}` | run snapshot (status, pending interrupt, result) |
| POST | `/api/runs/{id}/approve` | resolve the current gate `{approve, feedback}` (409 if not awaiting) |
| GET | `/api/runs/{id}/events` | Server-Sent Events: `update` / `interrupt` / `done` / `error` |
| GET | `/api/history`, `/api/history/{id}` | past runs from durable memory |

A run pauses at each approval gate with `status: awaiting_approval` and the
interrupt payload; `POST …/approve` resumes it. Approvals and audit events persist
to durable memory when `MOSAERA_DB_URL` is set (`approvals`, `audit_events` tables).

## Scope

Uses an in-process checkpointer (`InMemorySaver`): runs are resumable across HTTP
requests within one server process. A server-lifetime Postgres checkpointer for
cross-restart resume is follow-up work; durable run *memory* already persists to
Postgres today. The future web dashboard (`apps/web`) consumes this REST/SSE seam.
