# packages/connectors

Outbound connectors from Mosaera to external systems.

## github (`mosaera_connectors.github`)

Branch/PR flow for a finished run:

- `assemble_pull_request(...)` — builds the PR title and body from the task and the
  delivery report.
- `open_pull_request(workspace_root, plan, dry_run=...)` — pushes the run branch and
  opens a **draft** PR via the `gh` CLI (honors existing auth). `dry_run=True` returns
  the exact `git`/`gh` commands without executing them.

Opening a PR is **not** a graph-gated action (ADR-0102 — it never had a
`request_approval` caller): authorization is the caller's own control. Invoked from the
CLI via `mosaera run --open-pr` / `--pr-dry-run`, whose interactive confirm is that
control (and `--approve-all` bypasses it — CI/testing only). Live PRs require the `gh`
CLI authenticated and a GitHub remote on the workspace clone.

Future connectors (Slack, Postiz, …) live here alongside `github.py`.
