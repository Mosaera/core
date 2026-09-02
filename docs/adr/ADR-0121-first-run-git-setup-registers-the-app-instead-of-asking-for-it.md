# ADR-0121 — First-run Git setup registers the App instead of asking for it

- **Status:** accepted
- **Date:** 2026-08-28
- **Issue:** #120
- **Builds on:** [ADR-0114](ADR-0114-github-delivery-on-an-app-installation.md), [ADR-0120](ADR-0120-create-a-github-repository-on-a-discarded-user-grant.md), [ADR-0104](ADR-0104-gitlab-oauth-connect.md)
- **Scope:** api + connectors + core/config + web

**Decision summary:** Connecting a forge is a first-run **wizard**, not a list of environment
variables. Both providers get the same shell — step indicator, instructions derived from *this*
instance, fields, Back/Continue. Their middle steps differ because the providers differ: **GitHub
registers its own App in one click** via GitHub's App-manifest flow, returning the app id, private
key, slug, client id and client secret in a single response; **GitLab is a three-field form**,
because it has no equivalent. Credentials are stored server-side, secrets encrypted, and env still
wins over stored.

## Context

Everything ADR-0114 and ADR-0120 built was reachable only by setting environment variables and
restarting: `MOSAERA_GITHUB_APP_ID`, `_PRIVATE_KEY`, `_SLUG`, and then `_OAUTH_CLIENT_ID` /
`_SECRET`. The GitHub panel's unconfigured state was a paragraph naming those variables — accurate,
and not a product. An operator who reached it had to leave the app, register an App by hand, copy
five values including a multi-line PEM, edit a file, and restart.

The owner asked for the setup interface a hosted product has. A hosted product can skip setup
because the vendor registered one central app; a self-hosted instance cannot, and pretending
otherwise would be a lie in the UI. The honest goal is therefore not *no setup* but **no
credential handling** — the operator should never hold a private key.

## Decision

### 1. GitHub registers itself (the manifest flow)

`GET /api/github/setup/manifest` (admin) returns a manifest and a single-use state; the browser
POSTs it to `github.com/settings/apps/new`; the operator approves on GitHub; GitHub returns a
one-hour code to `/oauth/github/setup/callback`, which converts it via
`POST /app-manifests/{code}/conversions` into **id, slug, pem, client_id and client_secret at
once**. Mosaera stores them and the instance is configured.

This was verified against GitHub's REST reference before building — the conversion response
schema explicitly includes `client_id`, `client_secret` and `pem` — because two earlier GitHub
assumptions in this arc turned out to be wrong or undocumented.

Consequences worth stating:

- **Nothing is typed and no key touches a clipboard.** The private key goes GitHub → server.
- ~~**It also configures ADR-0120.**~~ **Corrected 2026-08-28 — this was false.** The manifest does
  return an OAuth pair, but a GitHub App's pair is refused by the repository-creation endpoints
  (`403 Resource not accessible by integration`, found live). Storing it made the instance look
  configured for a capability it could not perform, so the conversion no longer stores it and
  repository creation has its own setup (ADR-0120 Amendment 2). Registering the App still requires
  nothing typed; creating repositories is a separate, optional OAuth App.
- **Least privilege is declared at registration.** The manifest asks for `contents: write` and
  `pull_requests: write` and no events. An over-broad App is never created, rather than created
  and narrowed later at token-mint time.
- The manifest declares **two different callbacks** — `redirect_url` for this setup return leg and
  `callback_urls` for ADR-0120's user authorization. They are distinct endpoints; conflating them
  breaks one flow silently, so they are separate paths and a test pins both.

### 2. The conversion call is unauthenticated, and that is the correct shape

There is no token to send — the caller does not have one yet, which is what it is fetching. The
code is the secret: single-use, one hour, and worthless without the `state` this server minted and
re-checks. `_api` now **omits** the `Authorization` header when given no credential rather than
sending `Bearer ` with an empty value, which is a malformed header rather than an absent one.

### 3. GitLab is a form, and says exactly what to create

No manifest equivalent exists, so the operator creates an OAuth application by hand. The wizard's
contribution is removing the ambiguity: the **Redirect URI is derived from this instance** and shown
verbatim, along with the required scope (`api`) and Confidential: Yes. A hardcoded redirect URI
would be wrong for every self-hosted install, and wrong in the worst way — it surfaces much later as
an opaque OAuth error. It reuses `/gitlab/config` unchanged; no new endpoint.

### 4. Storage, and what it does not override

`write_settings` persists the five GitHub keys; the private key and client secret go through
`encrypt_secret` (ADR-0039), the id/slug/client_id do not because they are not secret. **Env still
wins over stored** (ADR-0005), so an operator who pins values in the environment is never
overridden by the wizard.

`_ALLOWED_KEYS` in `settings_store` is deny-by-default, so the five keys had to be added there.
This is recorded because it was found by a test and not by reading: without it the wizard reported
success and stored nothing — the exact "green by vacancy" shape this repo keeps meeting.

### 5. A manual path stays, one link away

An operator who already registered an App can paste its details. The server rejects an unreadable
PEM **at the form**, not at the first connect where it would read as a GitHub outage. It is not the
default, because making everyone copy five values is the setup this ADR removes.

## Consequences

- First-run setup for both forges happens inside the product; no file editing, no restart.
- The GitHub App private key and client secret are now accepted **through a redirect** and written
  to `settings.json`. That is a new trust boundary — see the red team below.
- `apps/web` gains a shared wizard shell (`SetupWizard`) usable by any future provider.
- Instruction lists render their own markers: this app resets `list-style: none` globally, so
  `list-decimal` silently produced an unnumbered list of numbered steps.

## Red team — done (2 rounds, pre-merge)

Target: the setup endpoints and what they store.

| # | Probe | Verdict |
|---|---|---|
| 1 | A non-admin registering or storing an App | **HOLDS.** `require_admin` is the first statement of both endpoints; tested for the manifest and the manual save. |
| 2 | A forged or replayed setup callback | **HOLDS.** State is single-use, hashed, TTL'd and bound to the initiating admin; spent **before** the code is converted, and the live session is re-checked. A dead state converts nothing (tested). |
| 3 | A setup state spent by the repo-creation callback, or the reverse | **HOLDS.** Distinct provider strings (`github-app-setup` vs `github`); `spend_oauth_state` matches on provider, and the fake store in the tests mirrors that so the test cannot pass by accident. |
| 4 | The stored secrets landing in plaintext | **HOLDS where a key is configured** — both go through `encrypt_secret`, tested. **Residual (pre-existing, unchanged):** with no `MOSAERA_SECRET_KEY`, `encrypt_secret` is identity by documented design, exactly as `gitlab_token` already behaves. Not introduced here; not silently fixed here either. |
| 5 | A half-configured App being stored | **HOLDS.** The conversion refuses a response missing any of id/pem/client_id/client_secret, and the manual path refuses an unreadable PEM — both before anything is written. |
| 6 | An over-broad App created on the operator's account | **HOLDS.** The manifest requests two permissions and no events; pinned by a test that fails if the set changes. |
| 7 | Open redirect on the setup fail path | **HOLDS.** A fixed internal literal; the reason is `quote`d and no part of the target comes from the request. |

**STOP rule not reached** — no defect class recurred.

## Amendment 1 (2026-08-28, same day) — two bugs the first click found

The button did nothing. Two independent causes, both fixed and pinned:

**1. The CSP silently blocked the whole flow.** `form-action 'self'` forbids a cross-origin form
POST, and the manifest flow *is* one. The browser refuses the navigation and reports only a console
violation — no error, no request, nothing on screen. That is the worst failure mode a setup step can
have, and no test caught it because every test exercised the endpoint rather than the browser.

`form-action` now names the configured GitHub host, **derived from `github_web_url`** rather than
hardcoded, so GitHub Enterprise works. This required narrowing an existing assertion that no
directive may name a remote origin. It was narrowed, not deleted: `form-action` is excluded from the
blanket rule (it governs where a *user-initiated navigation* may go, not where the page may fetch
from) and given a **stricter** dedicated test — at most one remote host, https, and equal to the
configured host. Every fetch directive is unchanged and still blanket-checked.

**2. First-run setup required a session that first run does not have.** The start endpoint demanded
a logged-in admin, so an instance with no accounts — precisely the instance a first-run wizard exists
for — refused its own setup button. The session is now required only where accounts exist;
`require_admin` still applies whichever gate the instance actually has. A state minted without an
identity records `_NO_USER`, and the callback skips an identity check that could never pass rather
than pretending one happened. Where a real admin starts the flow, the check is unchanged.

A third, correct behaviour was also made legible: without a database there is nowhere to store the
single-use state, so the flow fails **closed** — but it said "projects require durable memory",
naming the wrong thing at the worst moment. It now says the code protecting the handshake has
nowhere to live.

## Status of the evidence

Unit-tested: the admin gates, the state binding and its spend-before-convert ordering, the
provider-scoped state, the least-privilege manifest, the encrypted-at-rest write, the
half-configured refusal, and both wizards' UI contracts (GitHub asks for no credentials; GitLab
derives its redirect URI and validates before enabling Continue).

**Not demonstrated live** ([ADR-0110](ADR-0110-agent-ownership-and-environment-truth.md)): the
actual manifest round-trip against github.com, and the GitLab application round-trip — which is
ADR-0104's own still-owed live leg. Everything in this arc remains unproven against a real forge.

Amendment 1's fixes were verified at the API and header level (the policy now names the host; the
endpoint passes the session gate) but **the click-through was not re-driven end to end**: the state
store needs Postgres, none was running, and Docker Hub rate-limited the pull. So the claim here is
"the two causes found are fixed and pinned", not "the button is proven to work".
