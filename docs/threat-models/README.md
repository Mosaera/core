# Threat Models

Mosaera's threat register. Each model carries an owner, a last-reviewed date, and a next-review
trigger; the [template](TM-0000-template.md) defines the structure — a threat register with stable
**IDs** and a per-threat **status** (`open` · `mitigated` · `accepted` · `superseded`), plus a
revision history, so it stays current instead of growing append-only.

| TM | Scope | Status | Last reviewed |
|---|---|---|---|
| [TM-0001](TM-0001-mosaera-lite-repo-agent.md) | The CLI run agent — model gateway, sandbox, repo tools, the delivery gate | current | kept current with each run-gate arc |
| [TM-0002](TM-0002-mosaera-api-web-server.md) | The API / web server — auth, admin gate, config writes, rate limiting | current | 2026-07 (ADR-0050/0051 controls) |

Any MR that changes the **threat surface** updates the relevant model (or adds one) — see `AGENTS.md`.
