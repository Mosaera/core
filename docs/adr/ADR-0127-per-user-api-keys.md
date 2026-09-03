# ADR-0127: Per-user API keys — a revocable, attributed headless credential

- Status: accepted
- Date: 2026-08-31
- Owners: Alejandro Rengifo
- Related: [ADR-0004](ADR-0004-auth-and-session-model.md) (the session/service-token model this
  extends), [ADR-0116](ADR-0116-setup-is-a-terminal-wizard.md) (which DELETED this repo's previous
  credential-issuing endpoint), [ADR-0040](ADR-0040-first-run-setup-token.md) (superseded, the
  endpoint in question)
- Related threat model: [TM-0002](../threat-models/TM-0002-mosaera-api-web-server.md) — updated
- Red-team: **DONE** (2026-08-31, 3 rounds, 27 attacks). 0 findings in the credential; 1 finding
  in the red team itself. One residual ACCEPTED — see §Red-team.

## Context

`MOSAERA_API_TOKEN` is the only headless credential and it is **one shared secret**: env-only, no
revocation, no attribution, no rotation. Everyone holding it is indistinguishable from everyone
else, and changing it breaks every consumer at once because there is only one.

ADR-0004 kept that token deliberately — "as a **service credential** for headless/automation
callers" — and that reasoning is unchanged. What it does not provide is *per-caller* identity: a
key for a CI job that can be revoked without disturbing a laptop, and a `last_used_at` an operator
can read before deciding whether revoking is safe.

**The prior art here is a warning, not a precedent.** ADR-0040 created a first-run setup token and
ADR-0116 removed it: *"CWE-1188 is now closed by there being no such endpoint rather than by a
token guarding one."* This repository has already deleted a credential-issuing endpoint on security
grounds. Adding one back is only defensible if it cannot reintroduce that class.

## Decision

A `api_keys` table and three session-authenticated endpoints. Two properties carry the security of
the feature, and **both are structural rather than checked** — they hold because of where the code
sits, not because a branch remembers to test for them.

### 1. A key authenticates, and is NEVER admin

`apikey_auth.authenticate_api_key` resolves a key to its owner and **sets no session user**.
`current_user()` therefore stays `None` for the remainder of the request, `_require_admin_ctx`
falls through to the service tier, and an admin-gated write still demands `MOSAERA_ADMIN_TOKEN`.

> **This paragraph was false as first written, and the correction is the interesting part.**
> Setting no session user does not only skip the *grant* branch of `_require_admin_ctx` — it also
> skips the **refusal** branch, the one that answers a logged-in non-admin with 403. A key
> therefore fell through to `_require_admin`, whose two secure-by-default tiers detect exposure by
> reading the *environment* (`MOSAERA_ADMIN_TOKEN`, then `MOSAERA_API_TOKEN`). An API key is a
> credential the environment cannot see, so a token-less instance was read as a developer laptop
> and the last tier is a **same-host** check. `guard_bind` requires no token for a loopback bind,
> which is exactly the recommended exposed topology — bind `127.0.0.1`, reverse proxy in front —
> where every request presents as `127.0.0.1`. Any user could mint their own key and create an
> administrator with it. The audit reproduced the full chain end to end.
>
> `_require_admin` now refuses a request carrying `request.state.api_key` before that same-host
> fallback, so the sentence above is true in *every* configuration rather than only when an env
> token happens to be set. The guard sits **below** the admin-token tier deliberately: a key
> holder may still perform an admin write by also presenting `MOSAERA_ADMIN_TOKEN`, and never on
> the strength of the key alone.
>
> Both load-bearing tests passed throughout, because `TestClient`'s socket peer is the literal
> string `"testclient"` — not in `_LOCAL_HOSTS` — so the same-host gate refused them for a reason
> unrelated to API keys. The peer address was doing the work the credential was credited with.
> `test_api_keys.py` now runs both properties through a `proxied` fixture as well, with a control
> test that fails if that fixture ever stops looking local.

This holds *even when the key belongs to an administrator*. An admin's own key cannot create an
account or rewrite config and secrets — so a leaked one cannot either. This is ADR-0004's "the
token is not admin", preserved for a credential a human can now mint from a browser.

The store's `api_key_owner` returns `{user_id, username, key_id}` and deliberately **omits
`is_admin`**. Reusing `_user_summary` (which carries it) would leak admin authority the moment any
caller read the flag; the distinct shape makes a key holder structurally unable to be mistaken for
a session user. `request.state.api_key` carries **attribution without authority**.

### 2. A key cannot mint a key

Every endpoint in `routes/keys.py` requires a logged-in **session**, and refuses a request
authenticated by a key. This is the ADR-0116 lesson generalised: a credential that can issue
credentials is self-propagating, and a leak becomes permanent rather than bounded by one revocation.

### 3. Revocation is a soft delete

`audit_events.run_id` is a **non-nullable foreign key to `runs.id`**, so there is no non-run audit
channel and issuance cannot be recorded there without inventing a synthetic run. The key row is
therefore itself the audit record: `revoked_at` is set, the row survives, and the history of a
credential that once had access remains reconstructable (*Capability through Auditability*).
Sessions hard-delete; this deliberately does not.

### 4. Mechanics

Only `sha256(key)` is stored, as with sessions — a database leak cannot be replayed. Lookup is **by
hash**, one indexed query, never a scan comparing every stored key. `last_used_at` is written only
when already stale (~5 minutes), so authenticating does not cost a write per request. Ownership on
revoke is enforced in the store's `WHERE` clause rather than by a check a future route could forget.
20 live keys per user bounds accidental accumulation; it is not a security boundary.

## Consequences

- `MOSAERA_API_TOKEN` is unchanged and still required for a non-loopback bind (`guard_bind`). This
  is additive; nothing is replaced.
- An operator can now issue a credential from the browser. That is a new issuance path, which is
  why the two structural properties above matter more than the feature itself.
- A key is useless for administration by design. An operator who wants a headless *admin* action
  still needs `MOSAERA_ADMIN_TOKEN`, and that remains env-only and unmintable.

## Alternatives rejected

- **Scoped/permissioned keys.** A per-key permission set is a policy engine, and the honest version
  needs a decision about what the scopes even are. "Authenticates, never admin" is one rule that
  can be stated in a sentence and verified in a test; scopes are deferred until something needs
  them.
- **Expiring keys.** A session expires because a browser walked away. A CI job does not, and a
  credential that silently stops at 3am is worse than one an operator revokes deliberately.
- **Replacing the shared token.** ADR-0004's reasoning for keeping it is untouched: it is also the
  network gate `guard_bind` enforces, and it works before any account exists.

## Evidence

12 tests, run against a real PostgreSQL (not skipped): a key authenticates; **an ADMIN's key is
refused both `GET /api/auth/users` and account creation**; a key cannot issue, list or revoke keys;
revocation takes effect and the row survives; the plaintext never reappears; another user's key
cannot be revoked; `last_used_at` does not write on every call; the owner projection has exactly
`{user_id, username, key_id}`.

Three tripwires verified — each property was broken in turn and the corresponding test went red:
a key that sets a session user, a guard that accepts `request.state.api_key`, and a revoke that
deletes the row.


## Red-team (2026-08-31, 3 rounds)

Target: the merged change, not the codebase. Durable and load-bearing → three rounds.

**Round 1 — authority (12 attacks).** Privilege escalation via the `?token=` spelling, a different
verb, a guessed `X-Mosaera-Admin` header, and combination; self-propagation by every verb and
spelling; a revoked key; a deleted user's key; session/key token confusion in both directions; and
enumeration by comparing a revoked refusal against an unknown one. **All refused.**

**The one finding was in the red team, not the code.** A companion probe — asserting each attacked
path exists and that an admin *session* can do the thing the key was refused — showed **3 of the 12
attacks had been refused by ROUTING rather than authorization**: `POST /api/settings/general` (it is
a `PUT`), a `/api/secrets` that does not exist, and a `DELETE` against a user id that did not exist.
Those attacks were green and proved nothing. Corrected to real routes and real ids; the probe is
kept so the same vacancy cannot return.

**Round 2 — surface (11 attacks).** The credential echoed in a refusal; the plaintext recoverable by
reading `api_keys` directly; hostile names (`<script>`, SQL, 500 chars, emoji, control characters);
the 20-key cap and whether revoking frees exactly one slot; revocation immediacy across repeated
requests; double-revoke idempotency. **All refused.**

**Round 3 — the browser (4 attacks).** The plaintext lives in the UI, so: persistence to
`localStorage`/`sessionStorage`, whether "Done" removes the key from the DOM or merely hides it,
whether a hostile name renders as markup, and whether the key is left in the form input.
**All refused.**

### Residual, ACCEPTED and asserted

**A key presented as `?token=` reaches access logs, proxies and browser history.** ADR-0004 already
names this cost for the shared service token — a query param "leaks into logs and history" — and
keys inherit the spelling because SSE and `<img>` cannot set headers, and a credential that worked
for one caller but not another would be a trap.

Bounded by the two properties that make a key weak: it is never admin and it cannot mint another,
so a leaked one reads and submits runs and nothing more; revocation is per-key and immediate, so
the remedy costs no other caller anything.

`test_H1` asserts the spelling still works, deliberately. If it ever fails because the spelling was
removed, that is a HARDENING — update this ADR rather than delete the test.

### Not covered

Concurrency was tested sequentially, not with genuine parallel requests: `TestClient` is
synchronous, so a true revoke-during-in-flight race is unproven. The lookup is a single indexed
query against a row whose `revoked_at` is set transactionally, so the window is a database
statement wide — small, and not zero.
