# ADR-0004: Authentication and session model

- Status: accepted
- Date: 2026-07-11
- Owners: Alejandro Rengifo
- Related issue: multi-user login (MR !139) + two-tier admin token (MR !94, finding #4)
- Related threat model: docs/threat-models/TM-0002

## Context

Mosaera is self-hosted and executes code in a sandbox while holding repository tokens, so
"who can reach the API" is a real trust boundary, not a convenience. Until now the only
credential was a single shared service token (`MOSAERA_API_TOKEN`): everyone with the token
was the same anonymous principal, the SPA carried it in `localStorage` and appended it as a
`?token=` query param to SSE/media URLs (a leak surface — query strings land in logs,
`Referer`, and browser history), and there was no human identity to attribute a run to.

Two things forced a proper account model. First, a small team wants named logins, not a
pasted secret. Second, MR !94 (finding #4) had already split capability into two tiers — the
service token grants API access, `MOSAERA_ADMIN_TOKEN` grants config/secret writes — and that
distinction needed to survive once humans logged in, rather than being flattened back into
"anyone with the token is admin."

Constraints that shaped the design: it must run on Windows/WSL loopback and LAN-`http`
deploys without a build toolchain or TLS; it must not break the existing service-token path
that headless callers and `guard_bind` depend on; and an unconfigured local dev box must stay
open (zero-friction first run).

## Decision

**1. Named accounts, capped, two roles.** A `users` table (Alembic `0007`) holds up to **5
seats** (`_MAX_USERS`, enforced in the store, not the schema). Role is a single boolean
`users.is_admin` — admin vs member. A `user_sessions` table backs server-side sessions.
Accounts require a database: with no `MOSAERA_DB_URL` the endpoints report
`users_supported: false` and no-op, and enforcement stays off.

**2. Passwords: stdlib `hashlib.scrypt`, no native build.** `hash_password`
(`apps/api/mosaera_api/auth.py`) uses memory-hard `scrypt` (`N=2**14, r=8, p=1`) with a
per-password 16-byte salt, encoding scheme+params+salt into the stored string
(`scrypt$N$r$p$salt$hash`) so cost can evolve without a migration. `verify_password` is a
constant-time `hmac.compare_digest`. This is a deliberate choice of the standard library over
argon2/bcrypt specifically to avoid fighting a native build on Windows/WSL.

**3. Sessions ride an HttpOnly cookie; only the token *hash* is stored.** `new_session_token`
mints `secrets.token_urlsafe(32)`; the DB stores only its **SHA-256** (`hash_token`), so a
database leak cannot be replayed as a live session. The token travels in a cookie
(`mosaera_session`) that is **HttpOnly**, **SameSite=Lax**, `path=/`, with a 14-day TTL, and
**Secure** when `MOSAERA_COOKIE_SECURE=1` (off by default so loopback/LAN `http` works). This
was chosen **over** a bearer token in `localStorage`: it removes the `?token=` query-param hack
(XSS/log-leak surface) and makes SSE and media requests "just work" same-origin with no header
plumbing. Logout, kick, or the opportunistic expiry sweep delete the row and revoke access
immediately.

**4. First-run bootstrap that self-locks.** `POST /api/auth/setup` creates the first account
as admin and works **only while zero users exist**; it returns `409` the moment any account
exists. `GET /api/auth/status` tells the SPA whether to show setup, login, or the app.

**5. Middleware: session OR service token, enforced only when configured.** The `_authenticate`
middleware in `app.py` authorizes an `/api/*` request by **either** a valid session cookie
(`current_user`, a DB lookup only when a cookie is present) **or** the shared
`MOSAERA_API_TOKEN` (constant-time compare, accepted as `Authorization: Bearer` **or** `?token=`
for header-less transports). It rejects only when **auth is configured** — a token is set **or**
users exist (`users_exist`); an unconfigured loopback dev box stays fully open. The three
bootstrap routes (`/api/auth/status|setup|login`) are always exempt, and `OPTIONS`/non-`/api`
paths (healthz, the SPA shell) pass through.

**6. The admin gate became a role check, preserving the #4 two tiers.** `_require_admin_ctx`
authorizes config/secret/user writes: a logged-in **admin** passes, a logged-in **member** is
refused (`403`), and with **no session** it falls back to the module-level `_require_admin` —
i.e. the `MOSAERA_ADMIN_TOKEN` header (`X-Mosaera-Admin`, constant-time) on a token-protected
instance, or the same-host gate on plain loopback dev. So the plain service token still grants
API access but **not** config/secret writes, and `MOSAERA_ADMIN_TOKEN` remains the headless
admin escape hatch.

**7. `guard_bind` intentionally unchanged.** A public (non-loopback) bind still requires
`MOSAERA_API_TOKEN` (and the Docker sandbox) as a network-level gate. User login layers human
identity **on top of** that gate, it does not replace it — defense in depth.

### Amendment (2026-08-18) — destroying a branch is admin authority; driving delivery is not

The 2026-08-18 process review established that a member must be able to drive a project end to end,
and the red team that followed (finding 6,
[`redteam-charter-gate-and-branch-guards-2026-08-18.md`](../engineering-history/redteam-charter-gate-and-branch-guards-2026-08-18.md))
found the resulting asymmetry: **installing** a project's GitLab token is admin-gated here as a
secret write, while **spending** it to irreversibly delete branches on the customer's repository was
available to any authenticated member. `make_project_delivery_router` was the only router not handed
the admin gate.

- **Branch destruction** — `POST …/branches/prune` and `…/branches/{branch}/delete` — is **admin-only
  by default**, and an admin may opt members in with the `member_branch_delete` knob (default off,
  env > stored > default like every other knob). The refusal names the setting so an operator can act
  on it rather than guess.
- **Even when opted in**, a member may delete only a branch GitLab reports as `merged`, and the check
  **fails closed**: without an api-scoped token merge state is unknowable, so a member deletes
  nothing. An admin may still delete an unmerged branch deliberately.
- **`retarget` and MR-opening stay member-available.** Retarget destroys nothing — it edits one field
  of an existing MR and is how a member unsticks their own work. Gating recovery behind an admin
  would recreate the dead-end the ADR-0047 amendment removed the same day.

The rule this draws: a member may *drive* delivery; spending an admin-installed credential
*irreversibly* is a separate authority. The knob is enforced on the live path and its control is
mutation-tested — `config/_knobs.py` records why a toggle that gates nothing is worse than no toggle.

## Options considered

- **Bearer token in `localStorage` vs an HttpOnly cookie.** Rejected the bearer approach:
  `localStorage` is readable by any injected script (XSS → token exfiltration) and forces the
  `?token=` query-param workaround for SSE/`<img>`, which leaks into logs and history. The
  HttpOnly `SameSite=Lax` cookie is script-unreadable and same-origin by default.
- **`scrypt` vs argon2/bcrypt.** Rejected argon2/bcrypt as the default: both pull a native
  build that is painful on Windows/WSL for a self-hosted product. `scrypt` is memory-hard,
  in the standard library, and params are encoded in the hash so we can raise cost later.
- **Replace vs keep the shared service token.** Kept it — as a **service credential** for
  headless/automation callers and as the network gate `guard_bind` enforces. User sessions are
  additive, not a replacement.
- **Relax `guard_bind` now that users log in vs leave it.** Left it unchanged: identity at the
  app layer is not a substitute for refusing an unauthenticated public bind of a code-executing,
  token-holding service.

## Security implications

- **Session theft/replay.** Only the SHA-256 of the token is stored, so a DB read cannot forge
  a session; the raw token lives only in an HttpOnly cookie, out of reach of page scripts.
  `SameSite=Lax` limits CSRF on state-changing cross-site requests; `Secure` (`MOSAERA_COOKIE_SECURE`)
  keeps the cookie off plaintext once TLS is present. Sessions are server-side and revocable
  (delete the row); the sweep prunes expired ones.
- **Seat cap and enumeration.** The 5-seat cap bounds credential sprawl. Login does constant-ish
  work whether or not the username exists and returns a single generic error, avoiding username
  enumeration.
- **Last-admin lockout.** `DELETE /auth/users/{id}` refuses to remove the last admin
  (`count_admins() <= 1`) so the instance can't be orphaned; the residual risk is a forgotten
  sole-admin password, recoverable via the `MOSAERA_ADMIN_TOKEN`/DB path, not the UI.
- **Unconfigured-loopback-open posture.** With no token and no users, `/api/*` is open — safe
  only because `guard_bind` refuses a public bind without a token. The moment a token is set or
  the first admin is created, enforcement flips on. See `docs/threat-models/TM-0002` for the
  session-theft, CSRF, and open-loopback trust-boundary analysis.

## Operational implications

- **Accounts need a database.** `MOSAERA_DB_URL` must be set for login; without it the instance
  runs exactly as before (service-token or open-loopback). Schema lives in Alembic `0007`, not
  `create_all`.
- **TLS.** Set `MOSAERA_COOKIE_SECURE=1` behind a TLS-terminating proxy so the session cookie is
  never sent in cleartext. Leave it off for loopback/LAN `http`.
- **First-run-then-expose flow.** Bring the instance up on loopback, hit `/auth/setup` to create
  the first admin, then expose it (a non-loopback bind still needs `MOSAERA_API_TOKEN` for
  `guard_bind`). Add teammates via the admin user CRUD, up to 5.

## Consequences

- Good: named human identity and per-user attribution; no secret in `localStorage` and no
  `?token=` leak surface; SSE/media work same-origin; no native crypto build to install;
  the #4 two-tier capability split is preserved as an app-layer role; the network gate is
  untouched.
- Cost: accounts require Postgres; sessions add a table and an expiry sweep; the "open on
  unconfigured loopback" rule is a deliberate convenience that must be understood alongside
  `guard_bind`, not in isolation.
- Follow-up: ~~TM-0002 formalizes the session trust boundary; … per-user rate limiting and
  audit-log attribution are natural next steps once identity exists.~~ **Corrected 2026-08-18**
  (`docs/audits/adr-corpus-review-2026-08-18.md`) — all three landed. Delivered since: TM-0002
  (`docs/threat-models/TM-0002-mosaera-api-web-server.md`); per-credential rate limiting + run quota
  (ADR-0050, `apps/api/mosaera_api/ratelimit.py`); per-account login backoff (ADR-0051,
  `apps/api/mosaera_api/loginguard.py`); and run audit events
  (`packages/memory/mosaera_memory/store/_runs.py::add_audit_event`). A shared service token remains
  a coarse principal for automation.
