# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| the newest release tag | Yes |
| anything else | No (experimental phase) |

The installer pins the newest `v*` tag, so "which version am I running" has an answer:
`git -C ~/.mosaera/core describe --tags`. Please include it.

## Reporting a vulnerability

Report vulnerabilities privately. Do **not** open public issues for unpatched
vulnerabilities.

- Preferred: email **security@mosaera.dev** with subject `[MOSAERA SECURITY]`.
- If the project's host offers confidential/private vulnerability reporting, that channel is also accepted.

## What to include

- Affected version / commit / tag
- Reproduction steps
- Impact assessment
- Logs, screenshots, or proof of concept if available

## Response targets

- Acknowledgement: within 3 business days
- Initial triage: within 7 business days
- Status updates: every 14 days until resolution

## Disclosure

We aim for coordinated disclosure after a fix is available.

## Scope notes for AI-agent risks

Mosaera runs AI agents against cloned repositories. Reports about **sandbox escape**
(agent writing outside its workspace clone), **approval-gate bypass**, **prompt
injection via repository content** that leads to policy violations, or **tool
allowlist bypass** are all in scope and treated as security vulnerabilities, not
model-quality issues. See `docs/threat-models/TM-0001-mosaera-lite-repo-agent.md`.
