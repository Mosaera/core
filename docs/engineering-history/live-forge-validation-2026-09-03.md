# Live-forge validation — 2026-09-03

Staging (`90d714fb`) deployed to app.mosaera.dev; every leg below was driven through the real UI
in a real browser against real forges, by the operator's assistant session with the operator
present. This closes the "OWED" live legs the roadmap carried for ADR-0112/0114/0120/0123/0125
and the wave-1 delivery work — and, as the readiness review predicted, the first real round-trips
found defects no unit test had seen. Both were fixed and deployed the same day.

## Validated

- **ADR-0114 criterion 4 — a real Mosaera-opened GitHub pull request.**
  Project `l` (`github.com/rengifosec/l`): intake → backlog → guided run
  (`20260903-054500-29dbc4`, Assayer tests + build + checks + review + delivery gate) → item
  approved → **Compose pull request** (provider-gated composer: no GitLab-only controls, target
  dropdown, faithful multi-line body) → **PR #1 opened by `mosaera[bot]`** with the operator-edited
  title verbatim: "Add README — Mosaera live delivery validation (ADR-0114 criterion 4)".
  The compose-passthrough fix is proven on the wire; the short-lived installation token path works.
- **ADR-0125 / ADR-0123 — local-first publish to GitLab, credentialed finish.**
  Project "Publish Round Trip" created with no upstream → Settings → Integration →
  Create repository (GitLab) → OAuth authorize (session previously authorized → auto-approved) →
  private repo created at `gitlab.rengifo.me/Ashura/Publish-Round-Trip.git`, history pushed,
  project repointed, **project token minted and stored in the same grant** (`…rmlx`, api scope ✓),
  landing on `?repo=created`.
- **Per-project GitLab liveness recheck** — the new Recheck action returned "Verified just now."
  against the freshly minted token.
- **GitHub App credential probe** — Settings → Git → GitHub shows "Credentials verified just now."
  (a real JWT-signed `GET /app`), with Disconnect present; installation `rengifosec` listed.
- **Guided-run realtime (#116) on the deployed instance** — two write gates approved and an
  ask→accept flip at a parked gate ("mode applies from the next gate — this one is already waiting
  on you below") with zero page reloads and no transcript duplication. (Also validated 2026-09-02
  on an isolated local instance, full loop to a sealed delivered receipt `d2221d96`.)
- **New-build smoke on the deployed instance** — the 404 catch-all renders at an unknown route;
  the consolidated 6-tab project nav and honest chat chips render.

## Found live and fixed the same day

1. **Readiness was GitLab-blind (`ab78855f`).** `deriveReadiness` credentialed only
   `has_gitlab_token`, so a connected GitHub project read "No GitLab token" forever and the
   open-PR action never rendered — ADR-0114 criterion 4 was unreachable from the UI on first
   attempt. Fixed: `capability.has_github_connection` credentials readiness; regression test.
2. **The OAuth-app instructions register one of two callbacks (`90d714fb`).** The repo-create flow
   authorizes against `/oauth/gitlab/create/callback`; both setup surfaces told the operator to
   register only `/oauth/callback`, so GitLab refused the authorize (no consent screen) on any app
   registered from our own instructions. Fixed: both URIs presented, one per line; the operator
   added the second URI to the live app registration.

## Still not exercised live

- GitLab's consent screen itself (the operator's session was already authorized → auto-approve;
  a first-time user's consent click remains unexercised).
- Disconnect flows (buttons render; not pressed — they destroy live credentials).
- Diverged-clone reset against a real force-pushed remote (endpoint + UI unit-tested only).
- A PATCH failure surfacing on an already-open PR.

## Cosmetic residue noticed (not fixed today)

- `READINESS_PLAIN.ready` still says "merge request" on GitHub projects (the button says PR).
- The PIPELINE card's standing line reads "no remote configured" for GitHub projects (the
  standing probe is GitLab-token-based).
- The decorative posture selector still surfaces in onboarding and PM intake questions.
- The PM composer placeholder still says "prepare the next run".
