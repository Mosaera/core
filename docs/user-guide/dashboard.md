# Mosaera Dashboard — user guide

The web dashboard (served at `http://localhost:8000` after `make up`) is the operator's interface to a
project. A CLI (`make run REPO=… TASK=…`) covers headless single runs.

See also: [the core workflow](core-workflow.md) for the everyday loop end to end, and
[troubleshooting a stopped run](troubleshooting-runs.md) for what to do when a run parks.

## Sections

- **Overview** — project health, objective, backlog state, and recent activity.
- **PM** — planning, prioritization, explanations, and proposed backlog work (Quincy).
- **Backlog** — a delivery-control board: item details, acceptance criteria, review gates, and run links.
- **Changes** — the repo delta and merge-readiness view.
- **Runs** — execution history and diagnostics for individual agent runs.
- **Artifacts** — produced files, the downloadable patch, file previews, and run reports.
- **Settings** — a sectioned area (Behavior · General · Autonomy · Advanced · Models · Git ·
  API keys · Users) that manages operational config in the UI, so editing `.env` is optional.
  Admins add up to 5 teammate accounts under **Users**.

## Multi-user login

With a database configured, the first administrator is created by the **terminal setup wizard** —
`uv run mosaera-setup`, run on the host (ADR-0116; details in
[getting started](../getting-started.md) and the [user-management runbook](../runbooks/user-management.md)).
The dashboard itself has no "create first admin" screen — there is deliberately no browser path to
a first account. It requires per-user sign-in; an admin manages seats (capped at 5 — self-hosted
small-team scope).

## Reading run state — four independent concepts

Mosaera keeps these distinct on purpose; they do not collapse into one badge:

- **Run status** — did the run reach a conclusion, or park / error?
- **Approval status** — did the delivery gate or a human approve?
- **Validation status** — did executed validation confirm correctness?
- **Merge readiness** — is the change ready to open as a merge request?

For example, **`Approved · validation failed`** means the run output cleared the gate's evidence check
but validation did not confirm correctness — an honest, visible combination, never hidden behind a
single "done".

## Changes vs Runs (boundary)

- **Changes** = repo delta + merge readiness.
- **Runs** = execution events + diagnostics.
