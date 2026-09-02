# ADR-0114 — GitHub delivery on an App installation, resolved from the repo and never from a redirect

- **Status:** proposed
- **Owners:** @rengi
- **Implements:** [ADR-0112](ADR-0112-two-named-delivery-providers.md) §5 — with one correction,
  recorded in §6 below rather than left to look like drift.
- **Related:** [ADR-0104](ADR-0104-gitlab-oauth-connect.md) (the GitLab Connect flow this
  deliberately does **not** mirror, and why), [ADR-0102](ADR-0102-delivery-spine-truth-up.md)
  (`delivery.py` as the seam; PR opening is not graph-gated),
  [ADR-0103](ADR-0103-mr-rest-metadata-api-token.md) (the token-routing invariant this extends to a
  fourth lane), [ADR-0042](ADR-0042-clone-token-host-equality.md) (host equality before a credential
  is spent), [ADR-0001](ADR-0001-stack-and-architecture.md) (the `gh`-CLI path, unchanged)
- **Scope:** connectors + api + web + memory (**Alembic 0033**) · **trust-boundary change** —
  threat model [TM-0002](../threat-models/TM-0002-mosaera-api-web-server.md) updated ·
  **red-team: done** (3 rounds, 2 FIX-NOW both fixed — see §8)
- **Invariants:** *Capability through Auditability*, *Honest Parking*, *Independent Approval*
  (unchanged — a human still opens, a human still merges)

**Decision summary:** A project on a public GitHub repository delivers from the Delivery page. The
credential is a **GitHub App installation token**, minted immediately before each delivery, scoped to
that one repository, valid an hour, never stored. Which installation to use is **resolved by asking
GitHub about the project's own `source_repo`** — never read out of a redirect, because GitHub
documents that value as forgeable.

## Context

ADR-0112 closed the honesty half of #120: a GitHub project now says it cannot deliver instead of
failing at the finish line. It could still not deliver. ADR-0112 §5 recorded the intended credential
shape — a GitHub App — because ADR-0104 had deferred GitHub on a specific and correct ground:

> "GitHub remains deferred (ADR-0001): a GitHub OAuth App issues user tokens, not a clean per-repo
> token, so the 'mint a project token then discard the grant' shape doesn't map; revisit with a
> GitHub App if/when GitHub delivery is scoped."

#120 scopes it, and a GitHub App resolves exactly that objection: installation tokens are per
installation, narrowable to named repositories, and expire in an hour.

## Decision

### 1. Nothing from a redirect is trusted — so there is no redirect to trust

The obvious mirror of ADR-0104 would redirect the operator to GitHub, receive a callback, and read
the `installation_id` it carries. **GitHub's own documentation forbids this:**

> "Bad actors can hit this URL with a spoofed `installation_id`, so you should not rely on the
> validity of the `installation_id` parameter."

GitHub's suggested remedy is to obtain a user token and cross-check `GET /user/installations`. This
ADR takes a stronger route that removes the question rather than answering it: **ask GitHub which
installation owns the repository this project already points at** — `GET /repos/{owner}/{repo}/installation`,
authenticated by the App JWT. Every input to that question is already server-side. There is nothing
for an attacker to supply.

The consequence is that ADR-0104's machinery is **not needed and not built**: no `oauth_states` row,
no single-use state, no pre-auth callback outside `/api`, no client secret, no code exchange.
`POST /api/projects/{id}/github/connect` is an ordinary admin-gated endpoint. This is a *smaller*
trust surface than the GitLab flow, not a shortcut around it — the CSRF and replay defenses ADR-0104
needed exist to protect a handshake that does not occur here.

**This is a deliberate divergence from ADR-0104's shape.** Recorded loudly because a future reader
comparing the two providers will otherwise read it as an oversight and "fix" it by adding a callback.

### 2. The credential is minted per delivery, scoped down, and never stored

`POST /app/installations/{id}/access_tokens` with `repositories: [repo]` and
`permissions: {contents: write, pull_requests: write}`. An installation token defaults to everything
the installation was granted — for an operator who installed the App org-wide, that is a far larger
credential than opening one pull request warrants.

Only the **installation id** is persisted (`projects.github_installation_id`, Alembic 0033), and it
is deliberately **not encrypted**: an id is an identifier, not a credential. The token expires in an
hour, so minting at connect time and storing it would hand out something usually already dead.

**The stored id is a record that a resolution once succeeded — it is never spent.** The
installation is re-resolved from the project's *current* `source_repo` on every delivery, and the
stored value is read only by the UI as a presence bit.

That is stronger than the first draft, which used the cached id and re-resolved only after a mint
failure. **Red-team round 1 rejected it:** the id is cached against a *project*, but the thing it
must match is that project's *current* repository, and the two diverge the moment someone edits the
source. Changing a source from `acme/widget` to `other/widget` would mint against `acme`'s
installation scoped to a repository named `widget` — a credential for the wrong repository, then
sent to the new repo's push URL. Nothing was writable across repositories (the push is rejected),
but minting a credential for a repository nobody asked about is not a state worth reasoning about
later. Delivery is human-initiated and infrequent; one extra `GET` is the right price for the class
disappearing. Both the general rule and the concrete same-bare-name case are pinned by tests.

### 3. Token routing gains a fourth lane, and the lanes do not cross

ADR-0103's invariant becomes: **project-write / project-api / global-adhoc /
project-github-installation** never cross. A GitHub token is minted from a project's own resolved
installation and scoped to that project's own repository, so it cannot be spent on another project's
repo even by accident.

### 4. Push over git, open over REST

`github.push_branch` is the analogue of `gitlab.open_merge_request(push_only=True)` — the seam
ADR-0102 named — and copies its hygiene deliberately: the credentialed URL is built separately from
the display command so the token cannot reach a returned object; every subprocess is bounded; `git`
is resolved via `shutil.which`; stderr is scrubbed and capped. The token rides
`https://x-access-token:<token>@github.com/...`, the exact shape `redact.scrub_credentials` already
strips, and is percent-encoded so it cannot break out of the userinfo component.

Title and body come from `_shared.request_title/request_body`, the same helpers the GitLab and CLI
paths use, so a pull request and a merge request for the same run are byte-identical.

### 5. Endpoint-only, and the spine is untouched

GitHub delivery is reachable **only** from the authenticated endpoint — mirroring ADR-0103's rule
that the unattended path never touches `gitlab_write.py`. `GATED_ACTIONS` is unchanged, both
`interrupt()` sites are untouched, and nothing here merges.

**This is enforced, not merely stated, and it was not true when first written.** `open_project_mr`
has two callers — the endpoint and the sweep's `_maybe_open_project_mr` — and the first draft added
the GitHub branch inside the shared function, so the sweep could reach it while this section claimed
it could not. **Red-team round 3 caught it.** The function now takes `allow_github`, defaulting to
**closed**, which only the endpoint passes; a future caller that forgets it gets a skip, not an
unattended push. Two tests pin it: one on the parameter, one asserting the sweep's actual call site
does not pass it — because the defect was in the wiring, and a test of the default alone would have
missed it.

Recorded at this length because a documented control that cannot fire is the failure this
repository's guard family exists to catch, and this was an instance of it caught before merge rather
than after.

### 6. Correction to ADR-0112 §5

ADR-0112 §5 said `github.py` needed hardening "before any HTTP caller reaches it". **No HTTP caller
reaches it.** The `gh`-CLI `open_pull_request` remains the CLI's path (ADR-0001) and gains no
server caller: a subprocess that can hang has no business inside a request, and ambient CLI auth is
a host-global credential where a project-scoped one belongs. The server path is REST plus one bounded
`git push`. The hardening ADR-0112 asked for was applied to the **new** `push_branch`, which is
where a request actually spends time.

### 7. Public repositories only, stated rather than discovered

`clone.py::_auth_url` injects a credential only for the configured GitLab host, so a **private**
GitHub repository cannot be cloned — the run never starts. Extending it is a second
credential-injection host family and its own trust decision, so it is out of scope here. The
capability record carries the limit as a `note`, and the Delivery page shows it even when the project
is fully connected — a stated boundary rather than a dead end. This also places GitHub's
draft-PR restriction (unavailable on private repos under Free plans) out of reach rather than
silently downgrading a draft to a ready PR.

Per-item pull requests are also out of scope: GitLab's item MRs are *stacked*, and reproducing that
on a second forge deserves its own slice. `item_requests_supported` says so, and the page withholds
the control instead of offering one that would fail.

### 8. Red-team — **done** (3 rounds, pre-merge)

This lands in the trust-boundary file-domain (a new credential, a new egress host, a new
authenticated endpoint), so it was deny-by-default and scoped as a durable load-bearing change ⇒
3 rounds. Disposition:

| # | Target | Verdict |
|---|---|---|
| 1 | A token minted for project A spendable against project B's repo | **FIX-NOW — found and fixed.** The cached installation id was spent without checking it still matched the current `source_repo` (§2). Now re-resolved every delivery; two tests pin it. |
| 2 | The App private key reaching a log, an error string, or a client | **HOLDS.** `repr=False`, encrypted at rest, read only to sign. The malformed-key error deliberately does not echo its input (tested). No route returns it; `/api/github/status` exposes a boolean. |
| 3 | The autonomous sweep reaching GitHub | **FIX-NOW — found and fixed.** §5 claimed endpoint-only while the sweep shared the same function. `allow_github` now defaults closed; the parameter *and* the sweep's call site are pinned. |
| 4 | A non-admin reaching connect | **HOLDS.** `require_admin` is the first statement; a logged-in non-admin gets 403 and nothing is recorded (tested). |
| 5 | The token-routing invariant (four lanes) | **HOLDS.** The GitHub path reads no GitLab credential and vice versa; the installation id is never read from a request. |

**STOP rule not reached** — the two findings were different defect classes (a stale-cache binding
and an unenforced claim), so no class recurred across rounds.

Residual, accepted and documented: `has_github_connection` can read *connected* after a
`source_repo` change, because the capability endpoint does not make a network call per page load.
The subsequent open then fails with a message naming the real cause. An honest late failure was
preferred over a per-render API call.

## Amendment 1 (2026-08-28) — a listing endpoint, and where Connect lives

Two changes to the *surface*, neither of which alters the credential design above.

**1. `GET /api/github/installations` (admin-gated, read-only).** The App's own JWT asks GitHub
`GET /app/installations`, and the Git settings panel renders the result. This exists because the
not-installed case had no home: an App installed nowhere surfaced only as an amber warning inside a
single project's Delivery card, phrased as a fault. It is the ordinary first-run condition and now
reads as the next step.

**This does not weaken §2's argument, and the distinction is the point.** The forgeable value was an
`installation_id` *supplied by a redirect* and then **spent** — minted against, pushed with. This
endpoint answers a different, weaker question ("where is this App installed at all?"), and nothing it
returns is ever spent: delivery still calls `installation_for_repo` against the project's own
`source_repo`. The separation is pinned by a test that fails if the listing path so much as calls
`installation_for_repo`, and by one asserting no token is minted during a listing.

Admin-gated rather than session-open like `/github/status`, because it names the accounts the App can
reach — organisation information, not a capability bit.

**2. Connect moved to the project's Integration pane.** It was on the Delivery card; the pane one
screen over rendered the *GitLab* card for every project regardless of forge, so a GitHub-backed
project was instructed to paste a `write_repository` token it can never use — exactly the untruth
[ADR-0112](ADR-0112-two-named-delivery-providers.md) removed from the Delivery page. The pane now
routes on the same capability record, and the Delivery card links to it instead of carrying a second
Connect button, which is the shape GitLab always had. The POST and its payload are unchanged: a
project id and nothing else.

**Unchanged and still owed:** the live round-trip (#120 criterion 4). This amendment is unit-tested
only.

## Consequences

- A public-GitHub project delivers end to end, and its PR state is polled so it can read as
  *Delivered* — without polling this would have reopened F64's gap on the other provider.
- `packages/connectors` gains its **first third-party dependency**, `cryptography`, for RS256. It is
  already a `mosaera-memory` dependency so the lock is unchanged, but the package's
  `dependencies = []` was a stated property and this ADR is where it stops being true. PyJWT was
  rejected: it would pull `cryptography` anyway for ~15 lines of signing.
- Two new skip reasons, `github_not_connected` (this repo lacks an installation) and
  `github_app_unconfigured` (this instance has no App). They are distinct because the remedies are:
  one is an operator installing the App, the other an admin configuring the instance once.
- **`scripts/check_migration_chain.py`** is added. Two parallel sessions each adding a migration
  produce *different filenames* chaining the same parent, so git merges both cleanly and Alembic
  silently acquires two heads; the only test that would notice is `requires_db`-gated and skips on
  `make test`. That is the green-by-vacancy shape, and this migration is the second half of a live
  instance of it (#121 carries its own `0033`).
- TM-0002 gains the fourth credential lane and `github.com` / `api.github.com` as egress
  destinations.

## Alternatives rejected

- **Mirroring ADR-0104 exactly (redirect + state + user token).** Consistency would be bought with a
  larger attack surface — a pre-auth callback, a client secret, and a CSRF-able handshake — to answer
  a question we can answer server-side without any of them (§1).
- **Trusting the setup-URL `installation_id`.** Documented by GitHub as forgeable.
- **Storing the installation token.** It lives an hour; a stored one is usually already dead, and it
  would convert an expiry into a stored credential to protect.
- **A default-scope installation token.** Simpler, and hands out every repository the installation
  can reach for an operation that needs one.
- **Extending `clone.py` for private repos in this slice.** A second credential-injection host family
  deserves its own decision and its own red-team round (§7).
- **Reusing the `gh` CLI from the server.** A hang would occupy a FastAPI worker, and its ambient
  auth is host-global where ADR-0102 §2 requires project-scoped (§6).

## Status of the evidence

Criterion 2 of #120 is closed by unit and endpoint tests. **Criterion 4 — a real run's delivery
ending in an actual draft PR on a real GitHub repo — is OWED** and is not claimed here; per ADR-0110
it will not be marked done on unit tests. It needs a registered GitHub App installed on a public
repository; steps are in `docs/roadmap.md`.

Recorded rather than assumed away: **ADR-0104's own live round-trip has been OWED since 2026-08-14**
and has never run against a real instance. This is therefore the second unproven forge round-trip in
the repository, and it inherits no demonstrated precedent — which is part of why §1 chose the design
that has to trust the least.
