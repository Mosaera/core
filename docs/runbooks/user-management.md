# User management / seat administration

How to set up accounts, add and remove teammates, and recover access on a
self-hosted Mosaera instance. Everything runs locally; there is no hosted service
and no password-reset email.

Multi-user login is optional and **requires a database**. Without `MOSAERA_DB_URL`
set, the auth endpoints report `users_supported: false` and no-op — the instance
stays single-operator (loopback dev) or protected only by the shared service token.

## Concepts (how auth is wired)

Two independent credentials, plus per-user login:

| Credential | Env var | Sent as | Grants |
|---|---|---|---|
| User session | _(none — created by login)_ | `mosaera_session` HttpOnly cookie | API access; **admin** actions if the account `is_admin` |
| Service token | `MOSAERA_API_TOKEN` | `Authorization: Bearer …` or `?token=…` | API run/read access — **not** admin config/user writes |
| Admin token | `MOSAERA_ADMIN_TOKEN` | `X-Mosaera-Admin` header | Admin config/secret/user writes (headless escape hatch) |

- A request to `/api/*` is authorized by **either** a valid session cookie **or**
  the service token. Auth is enforced only when it is *configured* — a token is set
  OR at least one user account exists. An unconfigured loopback dev box stays open.
- The only endpoints left open pre-auth (so the SPA can bootstrap):
  `/api/auth/status` and `/api/auth/login`. Neither creates anything — `/api/auth/setup` was the
  third and is gone (ADR-0116).
- Admin writes (user CRUD, GitLab tokens, pricing) require a logged-in **admin**
  session; with no session they fall back to the admin-token tier, then — on a
  loopback dev box with neither token set — to a same-host check.
- Passwords are **scrypt-hashed** (`hashlib.scrypt`, memory-hard) and never stored
  in cleartext or logged. They are **unrecoverable** — you reset by setting a new
  hash or recreating the account, never by decrypting.
- Sessions store only the **SHA-256** of the token, ride an HttpOnly cookie, and
  last 14 days. Deleting the row (logout / kick / expiry sweep) revokes immediately.
- The seat cap is **5 accounts total**, admin included (`_MAX_USERS`).

## 1. First-run setup (create the first admin)

Prerequisite: a database is configured (`MOSAERA_DB_URL` — `make up` sets this for
you; set it directly only for an external DB). Restart the API after setting it.

**The first administrator is created in a terminal, not a browser (ADR-0116).** On the machine that
runs Mosaera:

```bash
cd <install dir> && uv run mosaera-setup
```

The wizard installs prerequisites with per-item consent, brings up the database, chooses the bind
and creates the first account — then starts the instance and hands you a URL that resolves. It is
also what `curl -fsSL https://install.mosaera.dev | bash` ends by running, so a fresh install
never sees this step as a separate act.

- Username: 3–64 chars, letters/digits/dot/dash/underscore.
- Password: at least 8 characters.

**There is no HTTP endpoint that creates the first account**, and that is the point: `POST
/auth/setup` had to be unauthenticated, which is what made the first-admin race (CWE-1188) possible
at all. ADR-0040 guarded it with a one-time token printed to the logs; ADR-0116 removes the endpoint
instead. Running the command on the host IS the proof the token stood in for. A browser opened
against an instance with no accounts says so, and names the command.

**For an orchestrated deploy that never sees a terminal**, pre-provision with
`MOSAERA_INITIAL_ADMIN_USER` + `MOSAERA_INITIAL_ADMIN_PASSWORD` — the admin is seeded at boot with
no open window. Invalid values are reported on stderr and create nothing.

Check instance state at any time (open, no auth required):

```bash
curl http://localhost:8000/api/auth/status
# {"users_supported":true,"needs_setup":false,"auth_required":true,"user":{...}|null}
```

## 2. Add / remove teammates

Admin only, in the dashboard: **Settings → Users**. The card shows `N / 5 seats`.

- **Add:** type a username + password, optionally tick **admin**, click **Add**.
  Same validation as setup (3–64 char username, 8+ char password).
- **Remove:** click the trash icon next to an account.

Guards enforced server-side (the UI just reflects them):

- **Seat cap:** creating a 6th account returns **409** (`user limit reached
  (5 max)`). The Add button disables at 5 seats — remove one first (see §5).
- **Unique username:** a duplicate returns **409** (`that username is taken`).
- **Last admin:** removing the only remaining admin returns **409** (`can't remove
  the last admin`) — the instance is never orphaned.

Headless equivalents (need a service/admin credential):

```bash
# List accounts + seat cap
curl http://localhost:8000/api/auth/users -H "Authorization: Bearer $MOSAERA_API_TOKEN"

# Create (is_admin optional, default false)
curl -X POST http://localhost:8000/api/auth/users \
  -H "Authorization: Bearer $MOSAERA_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"username":"bob","password":"another-long-pass","is_admin":false}'

# Remove
curl -X DELETE http://localhost:8000/api/auth/users/42 \
  -H "Authorization: Bearer $MOSAERA_API_TOKEN"
```

Note: user CRUD is an **admin** action. A plain service token satisfies the API
middleware but, on a token-protected instance, admin writes additionally require an
admin session or `MOSAERA_ADMIN_TOKEN` (see §3). On a loopback dev box with no
tokens set, same-host callers pass.

## 3. Lost / forgotten admin password (or orphaned instance)

Recovery WITHOUT the UI. Escalate in this order.

### A. Admin token escape hatch (preferred, no DB surgery)

If `MOSAERA_ADMIN_TOKEN` is set (or you can set it and restart), it authorizes
admin actions headlessly regardless of any user session. Use it to create a fresh
admin, then log in with that account and clean up:

```bash
export MOSAERA_ADMIN_TOKEN=…   # set in .env / env, restart the API if newly added
curl -X POST http://localhost:8000/api/auth/users \
  -H "X-Mosaera-Admin: $MOSAERA_ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"username":"recovery","password":"a-fresh-long-password","is_admin":true}'
```

The `X-Mosaera-Admin` header is proxy-safe (no IP heuristics), so this works even
behind a reverse proxy where the localhost gate would not.

### B. Last-resort database path

When there is no admin token and no working admin login, operate directly on the
`users` / `user_sessions` tables via the memory store. Run against the same
`MOSAERA_DB_URL` the API uses:

```python
from datetime import UTC, datetime
from mosaera_memory import MemoryStore
from mosaera_api.auth import hash_password

store = MemoryStore("postgresql://…")   # your MOSAERA_DB_URL

store.list_users()                       # find the account: [{id, username, is_admin}, …]
store.count_admins()                     # sanity-check how many admins remain

# Reset a forgotten password (also revokes that user's existing sessions):
store.set_user_password(user_id=1, password_hash=hash_password("a-new-long-password"))

# Or delete a wedged account (cascades to its sessions), then recreate it:
store.delete_user(user_id=1)
store.create_user("alice", hash_password("a-new-long-password"), is_admin=True)

# Force-logout everyone (e.g. suspected token theft) — expire all sessions now:
store.prune_sessions(datetime.now(UTC).replace(year=9999))
```

Notes and caveats:

- **Passwords are unrecoverable.** There is no decrypt — `set_user_password` writes
  a *new* scrypt hash (and revokes that user's sessions); `create_user` makes a new
  account. Always hash with `hash_password(...)`; never write a raw string into
  `password_hash`.
- **Promoting an existing user to admin** has no store helper. If you must flip an
  existing account rather than recreate it, run raw SQL:
  `UPDATE users SET is_admin = true WHERE username = 'alice';`
- `delete_user` and `create_user` respect nothing about the *last-admin* guard
  (that lives in the HTTP route) — at the DB level you can strand the instance, so
  make sure an admin remains.
- `create_user` still enforces the seat cap (`max_users`, default 5) and unique
  username inside one transaction; it raises `ValueError("user_limit")` /
  `ValueError("username_taken")`.

## 4. Rotate the service token / admin token

Set a new value and **restart the API** — both tokens are read from the environment
at startup.

```bash
# In .env (or real env), then restart:
MOSAERA_API_TOKEN=$(openssl rand -hex 32)      # service token
MOSAERA_ADMIN_TOKEN=$(openssl rand -hex 32)    # admin token
```

- The **old token stops working** immediately after restart. Update any service
  callers (CI, the transcript API, scripts, the dashboard's stored token).
- **User sessions are unaffected** — they are cookie/DB-backed, not derived from
  these tokens. Logged-in humans stay logged in across a token rotation.
- To also invalidate live user sessions (e.g. a real compromise), sweep them at the
  DB level as in §3B (`prune_sessions` with a far-future `now`), or have each user
  log out.

## 5. Seat cap reached (5/5)

The cap is **5 accounts total, admin included**. There is no way to raise it at
runtime — it is the constant `_MAX_USERS`. To onboard someone new when full:

1. **Settings → Users**, remove a seat you no longer need (trash icon), then
2. add the new account.

Headless: `DELETE /api/auth/users/{id}` then `POST /api/auth/users` (see §2). You
cannot remove the last admin to free a seat — promote or add another admin first.

## 6. Exposing the instance publicly

A non-loopback bind is refused unless it is authenticated and contained — this is
enforced at startup by `guard_bind`, not just documented here:

- `MOSAERA_API_TOKEN` **must** be set for any non-loopback `MOSAERA_API_HOST`
  (`127.0.0.1`/`::1`/`localhost` are exempt). Without it the API exits with a
  refusal. Set `MOSAERA_API_HOST` explicitly — a host passed only via
  `uvicorn --host` is invisible to the guard.
- The **Docker sandbox** is required on a public bind: `MOSAERA_SANDBOX=subprocess`
  is refused because it runs untrusted test code on the host with no containment.
- Behind TLS, set **`MOSAERA_COOKIE_SECURE=1`** so the session cookie is marked
  Secure (HTTPS-only). It defaults off so a plain-http loopback/LAN deploy works.
- Config/secret writes stay off the network by default: with tokens set they require
  `MOSAERA_ADMIN_TOKEN`; the localhost gate alone is unreliable behind a reverse
  proxy (every client appears as the proxy address), so prefer the admin token or an
  admin session for a proxied deployment.

See also the deployment runbook ([`deployment.md`](../getting-started.md)) for the API
server knobs, and `.env.example` for every variable.

## Reference

- Code: `apps/api/mosaera_api/routes/auth.py` (endpoints, seat cap, last-admin
  guard), `apps/api/mosaera_api/auth.py` (scrypt hashing, session cookie,
  `MOSAERA_COOKIE_SECURE`), `apps/api/mosaera_api/app.py` (`guard_bind`, the
  auth middleware, `_require_admin` fallback tiers).
- Store: `packages/memory/mosaera_memory/store.py` (`create_user`, `delete_user`,
  `set_user_password`, `count_admins`, `list_users`, `prune_sessions`); models in
  `packages/memory/mosaera_memory/models.py` (`User`, `UserSession`).
- Agent/security policy: [`AGENTS.md`](../../AGENTS.md) — auth/authz and
  secret-handling logic is CODEOWNERS-protected; changes need human approval.
- Auth design & threats: [`docs/adr/ADR-0004-auth-and-session-model.md`](../adr/ADR-0004-auth-and-session-model.md)
  (the decision record) and [`docs/threat-models/TM-0002-mosaera-api-web-server.md`](../threat-models/TM-0002-mosaera-api-web-server.md)
  (session/CSRF/admin-gate/recovery analysis).
