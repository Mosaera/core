# Mosaera Documentation Map

Which document is authority for what — and which are current vs. historical. Every doc belongs to
exactly one **class**:

- **Canonical** — must be kept current; the authority for decisions and execution. If it conflicts
  with the repository or tests, **the repository wins** (docs describe intent; code is truth).
- **Operational** — current procedures: install, run, operate.
- **Historical** — research, audits, benchmarks, superseded designs. Preserved for institutional
  memory; **never** an authority on current state.

The precedence when canonical sources disagree is in `../CLAUDE.md` (Authority order): active
instruction → issue scope → ADRs → security policy → current architecture → roadmap → North Star.

## Canonical

| Doc | Answers |
|---|---|
| [`../README.md`](../README.md) | What Mosaera is · why governed execution · how to run it |
| [`../project-brief.md`](../project-brief.md) | Why Mosaera exists + who it's for (durable) |
| [`architecture/north-star.md`](architecture/north-star.md) | **Why** — enduring direction, invariants, control points (the constitution) |
| [`architecture/README.md`](architecture/README.md) | **What exists** — the current architecture |
| [`roadmap.md`](roadmap.md) | **What's next** — build order + live status |
| [`adr/`](adr/) | Binding architectural **decisions** (why each was made) |
| [`threat-models/`](threat-models/) | Threat surface, controls, residual risk |
| [`../CLAUDE.md`](../CLAUDE.md) | **How an AI agent must behave** — the execution contract |
| [`../coding-standards.md`](../coding-standards.md) | **How code is written** — normative standard |
| [`../AGENTS.md`](../AGENTS.md) | Security & permissions policy (untrusted input, restricted paths) |
| [`../SECURITY.md`](../SECURITY.md) · [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | Vulnerability reporting · human contributor workflow |

## Operational

| Doc | Purpose |
|---|---|
| [`getting-started.md`](getting-started.md) | Install, run, configure, troubleshoot |
| [`user-guide/dashboard.md`](user-guide/dashboard.md) | The operator dashboard |
| [`runbooks/`](runbooks/) | User management + operational procedures (index) |
| [`runbooks/versioning.md`](runbooks/versioning.md) | Releasing a version — what earns which digit, the required benchmark evidence, the bump/tag sequence |
| [`onboarding/README.md`](onboarding/README.md) | Contributor onboarding (dev setup) |

## Historical (never authority)

| Doc | What |
|---|---|
| [`engineering-history/`](engineering-history/) | The arc journal — diagnoses, benchmark snapshots, red-team dispositions, lessons |
| ↳ [`lessons-2026-08-06…`](engineering-history/lessons-2026-08-06-first-project-end-to-end.md) | **Start here after the roadmap.** What the first end-to-end project established, and what to build from it |
| ↳ [`ledgercli-run-ledger-2026-08-06.md`](engineering-history/ledgercli-run-ledger-2026-08-06.md) | The baseline: every run, outcome, cost and milestone for that project |
| ↳ [`ledgercli-friction-log-2026-08-05.md`](engineering-history/ledgercli-friction-log-2026-08-05.md) | Findings F0–F63 in detail. **A record, not a backlog** — load-bearing findings are tracked issues (#65–#70). Historical: it is not authority and it goes stale; check the issue before acting on an entry |
| [`research/`](research/) | Evidence studies behind the standards |
| ↳ [`documentation-retrievability-and-staleness-2026-08-06.md`](research/documentation-retrievability-and-staleness-2026-08-06.md) | Why documented knowledge failed to reach the work, and what is mechanically enforceable. **Evidence-graded** — records four tempting fixes the evidence says NOT to build (RAG over docs, bigger context files, Diátaxis, deeper hierarchy) |
| [`audits/`](audits/) · [`design/`](design/) | Point-in-time benchmark snapshots + design studies (banner-marked historical) |
| [`demos/`](demos/) | Demo evidence logs (issue #53; durable lessons flow to engineering-history) |

---

*The **repository and its tests** are the ultimate source of truth for what exists. This map, and
every canonical doc, describes what the system should be and how to change it — not what is currently
running.*
