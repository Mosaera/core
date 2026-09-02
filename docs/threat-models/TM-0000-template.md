# Threat Model: <system or feature>

- Status: draft / current / superseded
- Owner:
- Last reviewed:
- Next review trigger: <the event that should prompt a re-review — e.g. a new external entry point, a new trust boundary, an auth change>

## Scope

What component, feature, or service is covered?

## Assets

What must be protected? Data, credentials, integrity, availability, reputation.

## Actors

Users, admins, services, attackers, AI agents, CI/CD systems.

## Architecture and trust boundaries

Link diagrams and list boundaries (CLI, orchestrator, model runtime, sandbox,
filesystem, network, CI/CD, etc.).

## Entry points

Endpoints, jobs, CLIs, webhooks, files, background workers.

## Threats

Each threat has a stable **ID** (`T-1`, `T-2`, …) and a **Status** (`open` · `mitigated` · `accepted`
· `superseded`) so a control that lands later updates the row's status — the register stays current
instead of growing append-only prose. Keep the *why-and-how* of a mitigation short here; deep
implementation detail belongs in the linked ADR.

| ID | Threat | Abuse case | Impact | Mitigation | Status | Residual risk |
|---|---|---|---|---|---|---|

## Security controls

Authn, authz, validation, logging, rate limits, secrets, runtime isolation,
review gates.

## Validation plan

Tests, scans, manual review, post-deploy checks.

## Revision history

| Date | Change | Trigger |
|---|---|---|
