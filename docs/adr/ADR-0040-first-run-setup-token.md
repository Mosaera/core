# ADR-0040: The first admin is gated by a one-time setup token printed to the startup logs

- Status: superseded by [ADR-0116](ADR-0116-setup-is-a-terminal-wizard.md)
- Removed from the code: 2026-08-26. The token, `POST /auth/setup`, `POST /auth/setup/check` and
  `needs_setup_token` are gone; `setup_gate.py` is now `initial_admin.py` and does only the
  `MOSAERA_INITIAL_ADMIN_*` seed. The `setup_tokens` table and Alembic `0012` are deliberately
  KEPT — dropping them is a destructive migration bought against a rollback still worth having
  while the terminal wizard is young, and the table only ever held SHA-256 hashes of one-time
  tokens. See [ADR-0116](ADR-0116-setup-is-a-terminal-wizard.md) §4 for why, and note what
  survives it: `POST /auth/users` still refuses to create the FIRST account, which is now the
  whole of the HTTP-side defence against CWE-1188.
- Superseded because: Superseded ON THE NORMAL PATH: the first admin is created by `mosaera-setup` in the terminal, so the token has nothing left to gate. `MOSAERA_INITIAL_ADMIN_*` remains supported. The CWE-1188 reasoning below is why no unauthenticated endpoint may ever create an account again.
- Date: 2026-07-15
- Owners: Alejandro Rengifo
- Related: [ADR-0004](ADR-0004-auth-and-session-model.md) (session-or-token auth + the admin gate this bootstraps), [ADR-0035](ADR-0035-infrastructure-failure-is-loud.md) (fail-closed capability reasoning, reused for `needs_setup`/degraded stores), [ADR-0039](ADR-0039-secrets-encrypted-at-rest.md) (at-rest secrets — the store this token hash lives beside)
- Related threat model: docs/threat-models/TM-0002

## Context

Multi-user login (ADR-0004) creates the first admin through `POST /api/auth/setup`, which the auth
middleware leaves **open** so the SPA can bootstrap before anyone is authenticated. The only guard
was *"zero users exist"*: the first caller to reach a fresh, reachable instance became admin.

On a genuinely loopback-only dev box that is fine. But Mosaera is self-hosted, and the reachable
surface is not always the operator's loopback: a reverse proxy, a LAN bind, a port-forward, or a
container publish can all expose `/api/auth/setup` on an instance whose admin has not been created
yet. In that window **any** reachable client can race the operator and seize admin — and from admin,
write config and read secrets. This is CWE-1188 (insecure default initialization) and is exactly the
class of the Portainer `CVE-2026-55761` first-admin race. `guard_bind` does not close it: it requires
a token only for a *non-loopback bind*, and the dangerous case (a loopback bind behind a proxy) keeps
`guard_bind` satisfied while still publishing setup. The socket peer is not usable as authz either —
behind a proxy every client looks like `127.0.0.1` — so a "loopback peer may skip the token"
fast-path would reintroduce the very hole it appears to close.

## Decision

Gate `POST /auth/setup` with a **one-time setup token** that only someone who can read the server's
startup logs possesses — the same control Jenkins (unlock file), GitLab (`initial_root_password`), and
Portainer's fix all use.

At startup, in `create_app`, when a DB is configured but **no users exist**, `bootstrap_setup_gate`
either:

- **seeds the admin directly** from `MOSAERA_INITIAL_ADMIN_USER` / `MOSAERA_INITIAL_ADMIN_PASSWORD`
  (the Django/GitLab pre-provision model — zero open window; the right choice for orchestrated
  deploys), or
- **mints a setup token** (or accepts an operator-supplied `MOSAERA_SETUP_TOKEN`), stores **only its
  SHA-256** in a single-row `setup_tokens` table (Alembic `0012`), and prints the plaintext **once**
  to stderr.

`POST /auth/setup` then requires that token — sent as the `setup_token` body field or the
`X-Setup-Token` header — and checks it with a **constant-time** compare against the stored hash before
minting the admin. On success it deletes the row (global single-use) and the endpoint self-locks
(409) as before. `auth_status` gains `needs_setup_token` so the SPA knows to collect it.

Design specifics:

- **The token is the control — there is no loopback fast-path.** A proxy makes the socket peer
  unreliable as authz, so the gate is enforced whenever the store has the setup-token capability.
- **Multi-worker-safe.** The hash is claimed with an INSERT-if-absent on a fixed single-row primary
  key (`RETURNING` as the win-signal), so under `--workers N` exactly one worker wins the claim and
  prints; the rest no-op.
- **Bounded exposure.** `MOSAERA_SETUP_TOKEN_TTL` (minutes, default 60) caps how long a token leaked
  into log aggregation stays useful; a restart after expiry reissues a fresh one.
- **Capability-degraded, per ADR-0035.** A store without the setup-token tier (a duck-typed test
  fake, or a build without the table) has no gate to enforce — a capability answer, not a failure —
  mirroring `users_exist`. A store that supports the tier but has no armed row fails **closed** (403).
- **Escape hatch.** `MOSAERA_INITIAL_ADMIN_*` lets automation and dev skip the interactive token
  entirely without weakening the default.

**Amendment (2026-08-25, [ADR-0115](ADR-0115-first-run-is-a-gated-flow-resumed-from-facts.md)):**
the token is now collected on a screen of its own, so it is also validated on its own by
`POST /api/auth/setup/check` — a fourth open bootstrap route that **creates nothing and never
spends the token**. The spend stays inside `POST /auth/setup`, which is what keeps the single-winner
claim below true; a check that recorded acceptance for a later request to trust would reopen exactly
the race this ADR closes. The check adds no disclosure — `_enforce_setup_token` already runs before
`validate_credentials`, so `/auth/setup` answers the same question today — but it is unauthenticated
and cheap (one SHA-256, no scrypt), so it takes the [ADR-0051](ADR-0051-login-backoff-and-enumeration-equalization.md)
backoff keyed on the socket peer.

## Consequences

- The token closes the `/auth/setup` race on any instance where auth is actually enforced — a
  non-loopback bind (where `guard_bind` forces `MOSAERA_API_TOKEN`, so the middleware blocks the
  authenticated surface) or any instance with `MOSAERA_API_TOKEN` set.
- **Important scope limit (finding A1):** on a *fully dev-open* instance — a loopback bind with
  **no** `MOSAERA_API_TOKEN`, exposed via a reverse proxy — the token does NOT by itself close the
  race, because there the ENTIRE `/api` surface is open: an attacker could mint the first admin via
  `POST /auth/users` (the admin gate degrades to the proxy-unreliable localhost check), or simply
  write config / read secrets directly. As defence in depth, `POST /auth/users` now refuses to
  create the *first* account (that must go through the token-gated `/auth/setup`), so the token
  still governs first-admin creation. But the real fix for a proxied deployment is to set
  `MOSAERA_API_TOKEN` (which `guard_bind` already urges) — a dev-open API behind a proxy is exposed
  regardless of this feature.
- First-run setup now has one extra step on a DB-backed instance: read the token from the `make up` /
  startup logs (or pre-provision via `MOSAERA_INITIAL_ADMIN_*`). Instances with **no** DB have no
  account tier and are unaffected.
- New env knobs: `MOSAERA_SETUP_TOKEN` (supply your own), `MOSAERA_SETUP_TOKEN_TTL` (minutes),
  `MOSAERA_INITIAL_ADMIN_USER` / `MOSAERA_INITIAL_ADMIN_PASSWORD` (seed + skip). Documented in
  `.env.example`.
- **UI (SHIPPED).** ~~UI follow-up (deferred to the UI refresh):~~ **Corrected 2026-08-18** (`docs/audits/adr-corpus-review-2026-08-18.md`) — `apps/web/src/components/AuthGate.tsx` renders a "Setup token (printed in the server's startup logs)" field driven by `auth_status.needs_setup_token` and blocks submit without it. The `X-Setup-Token` header and body field remain supported for automation. As originally written: the SPA first-run screen must add a "setup token
  (from the startup logs)" field driven by `auth_status.needs_setup_token`. Until then the token is
  supplied via the `X-Setup-Token` header or the request body.
