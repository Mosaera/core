# Contributing

> **Read this first if you arrived via the public GitHub mirror.** That mirror is one-way: it cannot
> merge a pull request, and its issue tracker is not monitored. Everything below describes the
> workflow on the private GitLab instance where development actually happens. Nothing here is an
> invitation you can act on from the mirror — which is exactly why it says so, rather than leaving
> an Apache-2.0 repository with a CONTRIBUTING file to imply otherwise. To report a vulnerability,
> use `SECURITY.md`; that channel is read.

## Before you start

- Read `README.md`, `SECURITY.md`, and `AGENTS.md`.
- Open an issue for large changes before writing code.
- Keep changes small and single-purpose — one logical change per PR.

## Branching

- Branch from `main`; use short-lived branches.
- Branch naming: `feat/<topic>`, `fix/<topic>`, `docs/<topic>`, `agent/<run-id>`
  (agent-authored branches).
- Do not push directly to `main`.

## `staging` — validate before you merge

`main` receives only changes that have been **exercised on a running instance**, not merely
green in CI.

```
feature branch ──> staging ──(deploy + validate)──> MR ──> main
```

- **`staging`** is the long-lived deploy branch and is **not** protected, so landing work there
  is cheap — that is deliberate, because friction here is what pushes people to merge first and
  find out later.
- **The instance deploys from `staging`.** Point it once (`git checkout staging`), then a deploy
  is just `git pull` + restart. Run `make db-migrate` when the change adds a migration.
- **`main` is protected** and is promoted to by MR from `staging`, *after* validation. Say in the
  MR what was actually exercised; "CI is green" is not validation.

**Why this exists.** Two changes were merged to `main` on the strength of unit tests and then
found defective on the first real run — one of them reproduced the exact defect it was written
to fix. CI proves the code does what its tests say. It cannot prove the tests describe the
behaviour that matters, and a governed-agent system fails mostly in the gap between those two.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat(scope): description`
- `fix(scope): description`
- `refactor(scope): description`
- `test(scope): description`
- `docs(scope): description`
- `ci(scope): description`
- `chore(scope): description`
- `security(scope): description`

## Pull requests

- Explain **why** the change exists, not just what changed.
- Link the issue / ADR / threat-model update when relevant.
- Include tests for behavior changes.
- Do not mix refactors with behavior changes unless justified.
- Draft PRs are welcome for work in progress.
- **Deterministic-first (ADR-0002):** if the change adds an LLM call, justify it in
  one line — can this be code instead? what latency does it add to the interactive
  (human-blocking) path? what's the token/$ cost per delivered outcome?
- **Docs & direction:** a behavior or design change updates the docs it touches —
  record the design choice + why (direction) in `docs/adr/` and any change to the
  threat surface in `docs/threat-models/`. A behavior change with no ADR/threat-model
  note is incomplete (see `AGENTS.md`).

## Sensitive changes

Changes to any of the following require explicit owner review (see `CODEOWNERS`):
CI/CD workflows, `infra/`, `packages/policies/`, `AGENTS.md`,
`.github/copilot-instructions.md`, `.claude/`, `docs/adr/`, `docs/threat-models/`,
the `Makefile`, dependency manifests/lockfiles, and anything touching secrets.

AI-generated changes follow the **same or stricter** rules — see `AGENTS.md`.
Test deletions or assertion weakening in any PR are treated as suspicious until a
human justifies them.

## Local checks

Run before pushing (same commands CI runs):

```bash
make fmt-check
make lint
make typecheck
make test
```

`make fmt` auto-formats.
