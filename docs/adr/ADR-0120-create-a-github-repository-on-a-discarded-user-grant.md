# ADR-0120 — Create a GitHub repository on a discarded user grant, with the name derived and never sent

- **Status:** accepted
- **Date:** 2026-08-28
- **Issue:** #120
- **Supersedes / amends:** extends [ADR-0114](ADR-0114-github-delivery-on-an-app-installation.md); reuses [ADR-0104](ADR-0104-gitlab-oauth-connect.md)'s state machinery
- **Scope:** api + connectors + core/config + web

**Decision summary:** A project with no repository can have a **public** GitHub repository created
for it by authorizing on GitHub — no token to paste, no second app to register. The authorization
code is exchanged for a **user** access token, which creates the repository and is **discarded in the
same request**. The repository's name is **derived server-side** from the project, so nothing that
names or locates the repository crosses the redirect. Delivery is untouched: it continues to
authenticate with installation tokens only.

## Context

ADR-0114 delivered to GitHub on App installation tokens and deliberately avoided an OAuth redirect,
because the value GitHub's setup redirect hands back — an `installation_id` — is documented by GitHub
as forgeable, and because the question it answered could be asked of GitHub directly instead.

Repository creation offers neither escape:

- **An installation token cannot create a repository.** GitHub's creation endpoints
  (`POST /user/repos`, `POST /orgs/{org}/repos`) name OAuth-app and personal-access tokens; an
  installation token is not among them. This was checked against GitHub's REST documentation before
  the design, not assumed.
- **No server-side question substitutes for consent.** Creating a repository is an act by a person on
  their own account. There is nothing Mosaera can ask GitHub that stands in for the user agreeing.

So this needs a real handshake. The design question is therefore not *whether* to redirect but **what
the redirect is allowed to carry**.

## Decision

### 1. A user grant, used once and never stored

`github_app.exchange_user_code` posts the code to the OAuth host (`github.com`, not the API host) and
returns a user access token. `github_repo.handle_github_repo_callback` spends it immediately on one
call and lets it go out of scope. Nothing persists it — the same discipline ADR-0104 applies to its
GitLab grant, and the reason neither has a per-user token table.

The credentials are the **same GitHub App's** client id and secret. A GitHub App issues both at
registration, so repository creation adds **no second app to register**: the values come off the
settings page the operator is already on for the App id and private key.

### 2. The repository name is derived, never transmitted

`repo_name_for(project_name, project_id)` computes a GitHub-legal name from the project's own name at
callback time. There is no `name` parameter in the authorize URL, the callback, or anywhere between.

This is the direct descendant of ADR-0114 §2's reasoning. A supplied name would be an
attacker-controlled string that decides **which repository, on whose account** gets created — a slash
changes the owner, `..` a path. Deriving it removes the parameter rather than validating it. Pinned
by tests over exactly those shapes.

### 3. Public only, enforced in code

`create_public_repo` hardcodes `private: False`; visibility is **not a parameter**. `clone.py::_auth_url`
injects a credential only for the configured GitLab host, so a private GitHub repository cannot be
cloned and its runs would never start. A visibility toggle would let an operator create a repository
this system then cannot use. The limit lives at the call site rather than in prose, and the UI states
it.

Private support requires extending the clone credential path to a second host family — its own
decision and its own red-team round, exactly as ADR-0114 §7 already deferred it.

### 4. Everything else is ADR-0104's proven shape

Single-use hashed state with a TTL, bound to the initiating admin + project + provider; **spent before
any code is exchanged**, so a stolen code alone is worth nothing; a live-session re-check against that
binding, because the state binding alone does not authorize; fail-safe redirects to a fixed internal
literal built only from a project id we resolved ourselves.

A **separate callback path** (`/oauth/github/callback`) rather than sharing ADR-0104's: state is spent
per-provider, so the handler must know the provider before it can spend anything. The URL answers
that instead of guessing, and the GitLab callback is untouched.

### 5. `source_repo` becomes mutable, and clears a stale installation id

Pointing a project at a repository just created for it is the first write to `source_repo`. ADR-0114's
`resolve_installation` already reasons about this divergence and re-asks GitHub on every connect, so
the hazard is handled — but a cached `github_installation_id` must not survive the move looking like a
live connection, so `update_project` clears it in the same write.

## Consequences

- A project can go from "no repository" to "delivering pull requests" without the operator leaving
  the app or handling a credential.
- The GitHub path now has **two** credential classes: installation tokens (delivery, unchanged) and a
  transient user grant (creation only). ADR-0114 §8's token-routing invariant still holds — the
  creation path reads no installation token and the delivery path obtains no user token.
- Three new settings (`MOSAERA_GITHUB_OAUTH_CLIENT_ID` / `_SECRET` / `MOSAERA_GITHUB_WEB_URL`), all
  following ADR-0005 precedence (env > stored > default), the secret `repr=False` and
  stored-encrypted.
- `config/_settings.py` was at 499/500 against the god-file ratchet, so `role_model_for` and
  `held_out_ok` moved to `config/_roles.py` as thin delegators — the split that module already exists
  to make, and which its docstring already describes. No call site changed.

## Amendment 2 (2026-08-28) — SETTLED: an App user token cannot create repositories

The open question is closed, by the live leg rather than by reading. Creating a repository with a
GitHub App user token returns:

```
403 {"message":"Resource not accessible by integration",
     "documentation_url":".../repos#create-a-repository-for-the-authenticated-user"}
```

"Not accessible by **integration**" is GitHub's phrase for *this is an App token, and Apps are not
permitted here*. The endpoint accepts OAuth-app and classic personal tokens only, exactly as its
documentation says and as this ADR recorded it might.

**The fallback was designed for and is now taken.** Repository creation uses an **OAuth App**,
configured separately from the GitHub App. Everything else is unchanged — the same authorize URL
shape, the same `state` machinery, the same discarded grant, the same derived repository name, the
same push-then-repoint ordering. Only which client id and secret are used differs.

**What had to change, and why it mattered.** ADR-0121's manifest flow stored the App's OAuth pair
as this credential, on the reasonable assumption it would work. It cannot — so the wizard was
producing a configuration that **read as complete and provably could not function**: the
green-by-vacancy shape, this time in the credential layer. The manifest conversion no longer stores
that pair (nothing depends on it), and repository creation has its own explicit setup at
`POST /api/github/oauth-app` with the callback URL and instructions stated in the panel.

The failure is also no longer a dead end: when GitHub answers "not accessible by integration", the
error names the remedy — an OAuth App, and where to configure it.

**Why this design survived being wrong.** The callback was written to pass GitHub's own message
through verbatim rather than a generic "could not create". That text is what identified the cause
on the first attempt, and it is why the correction is a configuration surface rather than a
redesign.

## Alternatives rejected

## Alternatives rejected

- ~~**A second, separate OAuth App.**~~ **Now the decision** (Amendment 2). It was rejected as
  doubling the operator's registration work; that trade no longer exists, because the alternative
  does not function. The cost is real and is now stated plainly in the panel: without it, projects
  still deliver — they just cannot have a repository created for them.
- **Asking the operator for a personal access token.** Works today and needs no ADR — and reintroduces
  exactly the pasted long-lived credential the GitHub path was built to avoid.
- **Letting the operator name the repository.** The name would then be attacker-controllable input
  deciding what gets created where. Deriving it deletes the parameter instead of validating it (§2).
- **Creating private repositories.** Out of reach until `clone.py` grows a second credential host
  family (§3).

## Status of the evidence

Unit-tested only: the derived name (including path/owner injection shapes), the state mint and its
binding, the refusal to exchange a code without a live state, the session re-check, the discarded
grant, public-only creation, and the verbatim error pass-through.

**Not yet demonstrated live**, and it will not be marked done on unit tests
([ADR-0110](ADR-0110-agent-ownership-and-environment-truth.md)): the authorize round-trip, an actual created
repository, and the token-type question in §Unverified. ADR-0114's own live leg (#120 criterion 4) is
**also still owed**, so this inherits no demonstrated precedent.

## Amendment 1 (2026-08-28) — the grant also pushes, and "no repository" stops meaning "no source"

Live use found the decision above half-built. Two linked defects:

**1. Creation was unreachable for every project that has code.** The precondition was "has no
`source_repo`", but a project whose source is a **local path** has a source and no *repository* —
and that is precisely the project this feature exists for. The rule is now "not already on a
forge" (`detect_delivery_provider` is `gitlab` or `github`), which keeps the red-team control
intact — a project on a forge still cannot be repointed at a new empty repository — while
admitting the case it was written for. The project settings pane no longer dead-ends an unknown
provider either; it offers the creation instead.

**2. An empty repository is worse than no repository.** Creating one and repointing the project
would leave its next run cloning nothing. So the grant now does two things before it is
discarded: create the repository, then **push the project's existing history into it**
(`github.push_existing_repository`). Only then is `source_repo` repointed.

**The ordering is the control.** Push, then repoint — never the reverse. A failed push leaves the
project pointing at its working source and says the repository exists but is empty, so the
operator is not hunting a phantom. Pinned by a test asserting the call order and by one asserting
nothing is repointed on failure.

**It reads the source and writes only to the remote.** The push targets an explicit URL rather
than a named remote, so it adds nothing to the operator's own `.git/config` and creates no
tracking ref — `source_path` is a real directory of theirs, not a throwaway workspace. Pinned by a
test that diffs the config across a real push to a real bare repository.

**Still discarded, still one request.** The user token now performs two operations instead of
one; it is still never stored, and delivery still authenticates with installation tokens only.
Widening what the grant *does* does not widen what it *is* or how long it lives.

## Red team — done (3 rounds, pre-merge)

Target: this change only — the user-grant flow, the installations listing, and `source_repo`
becoming mutable. Not "the codebase".

| # | Probe | Verdict |
|---|---|---|
| 1 | **The "no existing repository" rule lived only in the UI** | **FIX-NOW — found and fixed.** `GitHubConnection` withheld the control when a project had a source; the server checked nothing. `/api/oauth/github/start?project_id=<any>` would therefore repoint a WORKING project at a new empty repository and clear its installation id, reachable by any admin or by an admin following a crafted link. Now refused at **both** ends — at start (honest 400) and again in the callback, because a state minted while the project had no source could be spent after one was set. Both pinned by tests. |
| 2 | **A truncated installation list rendered as complete** | **FIX-NOW — found and fixed.** The listing took GitHub's default first page (30), so an App on more accounts showed a partial list, and the connections table undercounted, with nothing saying so. Now `per_page=100`. Beyond 100 it still truncates; since nothing is authorized on the list, the residual is a display limit rather than an access one. Pinned. |
| 3 | The user grant reaching storage or a log | **HOLDS.** Exchanged, spent on one call, out of scope in the same request. No field, no table, no return path. The secret is `repr=False` and never rides the browser redirect (tested). |
| 4 | A forged / replayed / cross-provider state | **HOLDS.** Spent before any code exchange, single-use, TTL, provider-matched; the live session is re-checked against the binding. A failed spend exchanges nothing (tested). |
| 5 | An attacker-named repository | **HOLDS.** There is no name parameter to attack — it is derived server-side. Path/owner shapes tested. |
| 6 | Open redirect via the fail path | **HOLDS.** The target is a fixed internal literal; the only interpolated value is a project id resolved from our own store, and the reason is `quote`d. |
| 7 | Delivery reaching a user token, or creation reaching an installation token | **HOLDS.** The two paths share no credential (ADR-0114 §8 lane 5 intact). |

**STOP rule not reached** — the two findings are different defect classes (a control that existed
only in the UI; a partial result presented as whole), so no class recurred.

**Residual, accepted and documented:** a project that holds a GitLab token *and* has no source can
have a GitHub repository created for it, leaving the GitLab token stored and unused. Delivery routes
by `source_repo`, so the stale credential is never spent — an unused credential, not a
wrong-target one. Widening the write to clear it was judged worse than leaving it inert.
