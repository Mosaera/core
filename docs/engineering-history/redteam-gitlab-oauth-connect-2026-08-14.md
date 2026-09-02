# Red-team — GitLab OAuth "Connect" (2026-08-14)

**Scope:** ADR-0104 — the new OAuth "Connect" flow (`apps/api/mosaera_api/routes/oauth.py`, the
`OAuthState` store, `gitlab_write` OAuth calls). Trust-boundary file-domain: external auth, a client
secret, a pre-auth redirect surface, and a fresh CSRF vector. Durable, load-bearing → **3 rounds**.
**Target:** *can a callback mint or store a project token that the initiating admin did not
authorize, leak the client secret, or bounce the browser off-site?* Probes are direct pytest cases
in `apps/api/tests/test_oauth_connect.py` (endpoint logic) + `packages/memory/tests/
test_oauth_state_store.py` (DB semantics, run against a throwaway pgvector Postgres).

## R1 — state forgery / replay / cross-user / expiry. **0 FIX-NOW**

| Probe | Result |
|---|---|
| Forge a state without the plaintext | Only the SHA-256 is stored; a 256-bit `secrets.token_urlsafe` can't be guessed. Nothing to forge |
| Replay a spent state | `spend_oauth_state` is `DELETE … RETURNING` — the second call finds nothing (`test_mint_then_spend_returns_the_binding_exactly_once`); 8 racing spenders → exactly one winner |
| Steal a state bound to admin 7, complete as admin 9 | Callback re-checks the live session: `id == bound_user_id` fails → refused, no exchange, nothing stored (`test_..._not_the_initiating_admin`) |
| Expired state | `spend` returns `None` past the TTL and the row is deleted regardless — can't be retried (`test_expired_state_does_not_authorize`) |
| Cross-provider spend | `provider` is matched in the DELETE (`test_provider_must_match`) |

No finding. The state is the CSRF token AND the authorization binding, and the callback trusts
neither the state alone (adds a session re-check) nor the session alone (requires the bound match).

## R2 — pre-auth callback abuse / open redirect / SSRF. **0 FIX-NOW**

| Probe | Result |
|---|---|
| Hit `/oauth/callback` with no state | Rejected before any spend/exchange (`if not code or not state`) → redirect to `/projects`; no side effect |
| `?redirect_uri=https://evil.example` (open redirect) | Ignored — every outcome redirects to a FIXED internal `/projects/{id}/settings` derived from the spent state, never a request param (`test_callback_redirect_target_is_always_internal`) |
| SSRF via the token exchange | `exchange_oauth_code` posts only to `{settings.gitlab_url}/oauth/token` (operator config); the attacker-supplied `code` is a body param to the trusted host, not a URL |
| SSRF via the mint | `create_project_access_token` targets only `{gitlab_url}/api/v4/projects/{gl_project}` where `gl_project` is `project_from_source` gated by `is_gitlab_source` (ADR-0042 host equality) |
| Provider denial (`?error=access_denied`) | Redirect with honest error, no spend, no store (`test_..._provider_error`) |

No finding. The route is outside `/api` by design (the provider must reach it pre-auth) and carries
its own authorization; the middleware's absence is not a hole because the handler gates on the spent
bound state + the session re-check.

## R3 — client-secret confinement / token handling / mint failure. **0 FIX-NOW**

| Probe | Result |
|---|---|
| Client secret reachable by the client? | `repr=False` env-only Settings field; sent server-to-server only in the exchange body; the status endpoint returns `configured`/`is_admin`/`host` — never the secret. `client_id` (public in OAuth) is the only id on the authorize URL |
| Is the OAuth user grant persisted? | No — used once to mint the project token, then dropped. `test_..._discards_grant` asserts the grant value never reaches `update_project` |
| Mint fails after a good exchange | Fail-closed: nothing stored, honest error redirect (`test_..._when_the_mint_fails`) |
| Minted token at rest | `update_project(gitlab_token, gitlab_api_token)` — encrypted (ADR-0039), write-only, presence-only in payloads (inherited ADR-0103 controls) |
| Header/token admin with no session starts the flow | 400 — refuses to mint an unbindable state (`test_start_400_without_a_logged_in_session`); the flow is session-only by construction |

No finding. Defense-in-depth worth noting: the mint is authorized by the operator's OWN GitLab
identity (`POST /projects/:id/access_tokens` requires Maintainer+ on the GitLab project), so even a
compromised Mosaera admin session cannot mint a token for a GitLab project the underlying user can't
administer.

## Dispositions

- **ACCEPT — state-mint DoS by an admin.** `start` is admin-gated, so only an admin can flood
  `oauth_states`; the TTL bounds each row and `sweep_expired_oauth_states` reclaims them. Admin-only
  + self-limiting → accepted, fails safe (a full table only blocks new connects, never mis-authorizes).
- **ACCEPT — the callback session re-check relies on `SameSite=Lax`** letting the cookie ride the
  top-level redirect. This is the same browser-cooperation assumption the existing CSRF row already
  documents; not new exposure.
- **DEFER-TO-SUCCESSOR — live provider round-trip.** The offline suite pins the endpoint logic and
  the Postgres suite the state store, but the actual GitLab authorize→exchange→mint is unexercised
  until the OAuth app is registered on `gitlab.rengifo.me` and the env is set. Tracked as the owed
  live validation (TM-0002 ADR-0104 row).

## Verdict

**No FIX-NOW across three rounds; no defect class recurred (STOP rule not reached).** The trust
boundary holds under the modeled attacks: a project token is minted only for the project the
initiating admin selected, for that admin, once per single-use bound state, against the configured
GitLab, with the client secret confined to the server and the OAuth grant discarded. `clean_deliver`
for the code; the live provider round-trip is the one owed piece of evidence.
