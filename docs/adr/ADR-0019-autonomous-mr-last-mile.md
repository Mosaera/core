# ADR-0019: The autonomous MR last-mile — the sweep opens the project MR

- Status: accepted
- Date: 2026-07-13
- Owners: Alejandro Rengifo
- Related: [ADR-0004](ADR-0004-auth-and-session-model.md) (admin-gated secret writes), [ADR-0006](ADR-0006-durable-transcript-and-honest-outcomes.md) (honest outcomes), [TM-0002](../threat-models/TM-0002-mosaera-api-web-server.md) (the API server threat model this updates)
- Amended by: [ADR-0102](ADR-0102-delivery-spine-truth-up.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.

## Context

The readiness audit named one defining gap: **the engine never opens the merge request.** A run —
and a whole autonomous project sweep — does clone → work → validate → review → gate → local commit +
report, and then *stops*, waiting for a human to click "open MR". The MR machinery already exists and is
safe: `open_merge_request` pushes the branch and creates the MR via **git push-options**, needing only a
`write_repository`-scoped token (no `api` scope), and it **only opens the MR — a human still merges it**.
What was missing is triggering it automatically, safely, on an approved autonomous delivery — so
"give it a project → it delivers an MR" is genuinely hands-off.

Architectural constraint: an autonomous sweep runs every backlog item on **one persistent project clone
with a single shared branch** (`mosaera/project-<id>`), accumulating commits. So the natural unit is
**one project MR, opened when the whole backlog is delivered** — not per-item MRs (which would re-push
the same growing branch). The existing human `POST /projects/{id}/merge` endpoint already assembles
exactly that MR from the delivered set, with the project's scoped token.

## Decision

**When an autonomous sweep leaves nothing left to run AND the whole backlog is delivered, open the
project MR — opt-in, gated, idempotent, honest.**

**1. One shared, guarded opener** (`apps/api/mosaera_api/delivery.py` `open_project_mr`). The MR-opening
logic is extracted from the `merge_project` endpoint into a module both the endpoint and the sweep call —
so there is exactly one audited, guarded implementation. It runs the same preconditions (`is_gitlab_source`,
scoped `get_project_token`, project clone present, non-empty diff), assembles the MR from the delivered
items, calls `open_merge_request(..., token=scoped, ensure_base=True)`, and on success sets the project
`in_review` + `mr_url`. It returns a structured `MrOutcome` (`opened` / `skip=<reason>` / `error`) rather
than raising, so the endpoint maps it to the same HTTP codes and the sweep can act on it. It lives in its
own module (not `routes/projects.py`) so `routes/context.py` reuses it without an import cycle.

**2. Opt-in knob** (`auto_open_mr`, `MOSAERA_AUTO_OPEN_MR`, default **OFF**). Auto-opening is an outward
action, so it is an explicit opt-in **distinct from the project's `autonomous` flag** — an operator may
want run-to-review without auto-opening.

**3. The sweep hook** (`AppContext._maybe_open_project_mr`, called from `advance_project` at the
"nothing runnable" point). It fires only when: `auto_open_mr` is ON **and** the backlog is *complete*
(every item in `{in_review, done}` — a backlog with `blocked`/`locked`/`todo` items left is *stuck*, not
complete, and keeps today's pause behaviour) **and** no MR is already open (`mr_url` unset → idempotent).
It's **best-effort**: wrapped in try/except, records `mr.opened` / `mr.failed` audit + a pause note on
failure, and **never breaks the sweep**. A benign skip (no token / not GitLab / empty diff) leaves the
project at review silently.

## Consequences

- Closes the audit's #1 gap at the whole-project level: an opted-in autonomous sweep now delivers an
  **open MR**, hands-off — while a human still reviews and merges it (the approval boundary is preserved).
- The manual `POST /projects/{id}/merge` button is unchanged (it now calls the shared opener; same codes).
- **Threat surface change (recorded in TM-0002):** this makes a previously manual, admin-gated outward
  push/MR **automatic** during an unattended sweep. Mitigations kept: opt-in (default OFF), scoped
  `write_repository`-only token (never a global token, never `api` scope), **opens-not-merges** (a human
  still merges), `is_gitlab_source` gate, honest `opened=False` on failure. Residual: **Low**.
- No migration (a global knob, not a per-project field) and no policy/allowlist change.

## Scope & deferred
- **Project-sweep only** this cut. **Deferred:** ad-hoc single-run auto-MR (+ fixing the pre-existing
  `POST /runs/{id}/open-mr` workspace-path resolution for project runs), a **per-project** auto-open
  toggle (vs the global knob), and auto-*merge* (always human — out of scope by the trust posture).

## Alternatives considered
- **Per-item MR on each approved item.** Rejected: all items share one branch, so it would re-push/target
  the same MR repeatedly. One MR at backlog completion is the correct unit.
- **Reuse the `POST /runs/{id}/open-mr` path.** Rejected for the sweep: it uses the *global* token and the
  ad-hoc `workspaces_dir/<run_id>` clone, wrong for a project sweep (scoped token, `projects_dir` clone).
