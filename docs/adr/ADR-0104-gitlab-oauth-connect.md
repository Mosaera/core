# ADR-0104 — GitLab OAuth "Connect": mint the project token by authorizing, not pasting a PAT

- **Status:** accepted (owner-approved 2026-08-14, in-session)
- **Scope:** api + connectors + web + memory (Alembic 0027) · **trust boundary** (external auth,
  a client secret, a pre-auth redirect surface) · threat model TM-0002 updated · red-team required
- **Builds on:** [ADR-0103](ADR-0103-mr-rest-metadata-api-token.md) (the per-project
  `gitlab_token` + `gitlab_api_token` model this flow POPULATES) · references
  [ADR-0004](ADR-0004-auth-and-session-model.md) (session/admin auth — the start endpoint
  is admin-gated, the callback re-checks the session), [ADR-0039](ADR-0039-secrets-encrypted-at-rest.md)
  (both minted tokens are encrypted at rest, unchanged), [ADR-0040](ADR-0040-first-run-setup-token.md)
  (the single-use hashed `SetupToken` pattern the state store mirrors),
  [ADR-0042](ADR-0042-clone-token-host-equality.md) (host equality — OAuth targets ONLY the
  configured GitLab), [ADR-0001](ADR-0001-stack-and-architecture.md) (**GitHub stays deferred** — a
  plain OAuth App can't mint a clean per-project token; GitLab can)

## Context — the PAT paste is the friction (and a wall for the assistant)

ADR-0103 gave a project two credentials: a `write_repository` `gitlab_token` (git transport) and
an optional `api`-scoped `gitlab_api_token` (REST metadata). Today an operator provisions both by
hand: open GitLab → Settings → Access Tokens → pick scopes → copy → paste into two fields. It is
error-prone (wrong scopes fail late), and an AI operator **cannot** complete it — entering a
credential into a field is a prohibited action, so the human is always in the loop for the paste.

The owner asked for a "Connect GitLab" flow: authenticate with the provider, let it provision the
project's tokens, land back with everything set. Research: **no OAuth / redirect / state / client-
secret infrastructure exists** anywhere in the repo. This is a new, security-critical surface.

## Decision

### 1. Mint-and-store, then discard the grant (no per-user token table)

The flow's PURPOSE is to provision the project's tokens, not to persist a per-user GitLab identity.
So after the OAuth `code`→token exchange (a short-lived user-scoped access token, scope `api`), the
callback immediately calls `POST /projects/:id/access_tokens` to mint **one project access token**
scoped `write_repository`+`api`, stores it as **both** `gitlab_token` and `gitlab_api_token`
(populating the whole ADR-0103 model in one shot), and **discards** the OAuth access/refresh token.
No new per-user grant table, no refresh columns, no expiry bookkeeping — the project token is a
normal ADR-0103 credential from that point on, revocable in GitLab like any other.

### 2. Self-hosted is the primary path — every endpoint derives from `settings.gitlab_url`

Mosaera targets a self-hosted GitLab (`gitlab_url` defaults to the operator's instance and is set
via `MOSAERA_GITLAB_URL` / `settings.json`, env > stored > default). The OAuth authorize/token
endpoints are therefore **derived** from `settings.gitlab_url` — `{gitlab_url}/oauth/authorize`,
`{gitlab_url}/oauth/token` — and the minted-token REST call hits `{gitlab_url}/api/v4/...`.
**gitlab.com is never hardcoded**; it is simply the case where `gitlab_url == https://gitlab.com`.
The OAuth application (client id/secret) must be registered on **that same** instance. The Connect
UI shows the configured host so the operator authorizes against the server they expect.

### 3. The client secret: env OR stored-encrypted (amended 2026-08-14)

`MOSAERA_GITLAB_OAUTH_CLIENT_ID` / `MOSAERA_GITLAB_OAUTH_CLIENT_SECRET`, plus `MOSAERA_BASE_URL`
(this instance's public origin, for the exact `redirect_uri`). Never sent to the client, never
logged; presence-only on any read (`oauth_configured` + a masked client_id, never the secret).
Absent ⇒ the Connect button is unavailable and the start endpoint 400s — the manual PAT path
(ADR-0103) remains the fallback, untouched.

**Amendment (turnkey setup, owner-approved 2026-08-14):** these three are now **`env OR
stored`**, not env-only. An admin can set them from the UI (Settings → Integrations), stored in
`settings.json` exactly like the global `gitlab_token` — the **client secret encrypted at rest**
(`encrypt_secret`/`try_decrypt`, ADR-0039), client_id + base_url plaintext (neither is secret).
**Env still wins** when set, so a deployment can pin them. Rationale: the original "env-only"
framing forced operators (and the assistant, which can't type a credential) to edit `.env`; storing
the secret encrypted is the *same posture as the already-stored `gitlab_token`*, not a new exposure
class. Caveat (identical to `gitlab_token`): without `MOSAERA_SECRET_KEY` the secret sits plaintext
in `settings.json` under `0600` — pair with the key to harden dumps/backups.

**Amendment 2 (one control, owner-approved 2026-08-18) — presentation only, no gate moves.** The
credential UX was spread over four entry points in three visual languages (global instance PAT,
this OAuth app form, a raw token field on the New Project form, and the per-project token card),
and nothing said which one an operator needed. Consolidated to **one button on the project**
(`components/settings/gitlab/`) whose label *is* the state — **Configure** (no app registered) ·
**Connect** (app ready, project unlinked) · **Manage** (linked) — opening **one dialog** carrying
the registration instructions, the redirect URI, and the two values. The instance-wide app is still
configurable from Settings → Integrations, but that surface now renders a read-only summary plus a
button opening the *same* dialog, so an admin with no projects yet still has a way in. The manual
PAT pair (ADR-0103) survives as an explicit disclosure inside the dialog; the New Project token
field is gone (the API still accepts a seeded token — no contract change).

**What did NOT change, and must not:** `/api/oauth/gitlab/start` stays admin-gated, the callback
still spends the bound state and re-checks that the live session is the same admin, and every
credential write (`saveGitlab`, `setProjectToken`) keeps its ADR-0004 admin gate. A **member sees
read-only status and no button** — the UI stops offering an action the server would 403, rather
than acquiring an ability. The only server-side edit is the redirect *target*: both the success and
failure 302s now carry `?pane=integration` so the operator lands on the pane that shows the result
(project settings panes became addressable via `?pane=`; they were local state, so every link
opened General). Those targets remain fixed internal literals built from a project id the server
resolved — **no part of a redirect may ever come from the request**. TM-0002 unchanged.

### 4. A single-use, hashed, bound state store (CSRF + binding)

New `OAuthState` table (Alembic 0027), modeled on `SetupToken`/`spend_setup_token`: a 256-bit
random `state`, stored **hashed** (SHA-256, plaintext never persisted), **single-use** (spent by an
atomic `DELETE ... RETURNING`), short TTL, **bound to `(user_id, project_id, provider)`**. The state
is the CSRF defense AND the authorization binding: the callback can only provision the project the
initiating admin selected, for that admin.

### 5. Two endpoints — an admin-gated start, a pre-auth callback that re-checks

- **`GET /api/oauth/gitlab/start?project_id=…`** — under `/api`, **admin-gated** (same gate as the
  token endpoint). Verifies the project is on the configured GitLab, mints + stores a bound state,
  302-redirects to `{gitlab_url}/oauth/authorize` (scope `api`, exact `redirect_uri`, the state).
- **`GET /oauth/callback`** — a **top-level** route (NOT `/api/*`): it arrives pre-auth from the
  provider with `?code&state`, and `SameSite=Lax` lets the session cookie ride the top-level GET.
  It: (a) spends+verifies the state (single-use, TTL, extracts the bound `user_id`+`project_id`);
  (b) **re-checks the live session** — the current user must exist, be admin, and MATCH the state's
  bound `user_id` (defense in depth over the state binding alone); (c) exchanges `code`→token;
  (d) mints the project access token; (e) `update_project`; (f) 302 to `/projects/:id/settings`.
  **Fail-safe:** any failure redirects to settings with an honest `?oauth_error=…` and stores
  nothing. Because the route is outside `/api`, it carries its OWN authorization (state + session
  re-check) — the middleware does not guard it.

## Consequences

- The operator (or the assistant, now unblocked for everything except the provider's own login/
  consent) provisions both project tokens with no manual PAT paste and no scope guesswork.
- New attack surface: a pre-auth callback, a client secret, an external redirect. Mitigations:
  state is single-use/hashed/bound + a session re-check; the redirect target is the fixed internal
  settings path (no open redirect — we never redirect to a URL from the request); the client secret
  stays server-side — env when set, else stored encrypted at rest (`encrypt_secret`, ADR-0039) per
  the 2026-08-14 amendment; host equality confines every call to the configured GitLab. Red-teamed
  (~3 rounds) before merge: state forgery/replay/cross-user, project binding, open-redirect,
  secret confinement, pre-auth abuse.
- GitHub remains deferred (ADR-0001): a GitHub OAuth App issues user tokens, not a clean per-repo
  token, so the "mint a project token then discard the grant" shape doesn't map; revisit with a
  GitHub App if/when GitHub delivery is scoped.

## Alternatives rejected

- **A per-user GitLab identity table (persist the OAuth grant + refresh).** More schema, a durable
  third-party credential to guard and refresh, and it isn't what the feature needs — the project
  token is the artifact. Rejected for least-persistence.
- **Client secret in `settings.json` / the UI.** ~~Puts an always-on secret in the stored-config
  surface and within reach of a non-admin read path. Env-only matches precedent.~~
  **REVERSED by the 2026-08-14 turnkey-setup amendment** (owner-approved) — this is now the
  fallback when env is unset. Retained for the record, because the objection was not wrong: the
  mitigation is that the write is admin-gated, the value is encrypted at rest (`encrypt_secret`,
  ADR-0039) exactly like the global `gitlab_token`, reads are masked, and **env still wins** when
  set, so a hardened deployment can pin it and never store one.
- **A generic multi-provider OAuth abstraction now.** DIRECTION, not authorized — one provider
  (GitLab), one use case. Build the second when GitHub delivery is actually scoped.
