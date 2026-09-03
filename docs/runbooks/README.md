# Runbooks

Operational procedures — an **index** of what exists today and what's planned.

## Available

- [Getting started](../getting-started.md) — install, run, configure, troubleshoot.
- [User management](user-management.md) — accounts, seats, access recovery, safe public exposure.
- [Releasing a version](versioning.md) — the CONOPS: what earns which digit, the benchmark evidence a
  release requires, who authorizes, and the bump/tag sequence.
- **Aborting a run** (below).

## Planned incident runbooks

Not yet written; tracked to be added as the operational surface grows (roadmap → Continuous/debt):
leaked secret in repo/CI logs · compromised dependency · compromised CI workflow or runner · bad
deployment rollback · vulnerable release artifact · a malicious agent-generated change merged by
mistake.

## Aborting a Mosaera run

`Ctrl+C` the CLI. Workspaces are disposable: delete `.mosaera/workspaces/<run-id>/`. The source
repository is never touched by a run; no cleanup is needed there.
