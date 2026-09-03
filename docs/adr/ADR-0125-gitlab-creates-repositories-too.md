# ADR-0125 — GitLab creates repositories too, and finishes credentialed

- **Status:** accepted
- **Date:** 2026-08-31
- **Issue:** #120
- **Builds on:** [ADR-0120](ADR-0120-create-a-github-repository-on-a-discarded-user-grant.md), [ADR-0104](ADR-0104-gitlab-oauth-connect.md), [ADR-0123](ADR-0123-a-project-may-start-with-no-upstream.md)
- **Scope:** api + connectors + web

**Decision summary:** A project not yet on a forge can have a **GitLab** repository created for it
and its history pushed into it, on the same flow ADR-0120 built for GitHub: authorize → create →
push → repoint. Two things differ, both because the providers differ rather than the flows:
GitLab needs **no second application**, and its repository is created **private**. And one thing
only GitLab can finish — the same grant mints the project's access token, so it ends **connected**.

## Context

ADR-0123 made local-first projects possible, and ADR-0120 let GitHub publish them. GitLab could
not, so the two forges had the same *shape* — one setup checklist each, after the previous slice —
and different *capability*. A project could be published to GitHub or nowhere.

That asymmetry had no principled basis. It existed because GitHub was built first.

## Decision

### 1. The same flow, deliberately

`routes/gitlab_repo.py` mirrors `routes/github_repo.py`: a single-use hashed state with a TTL bound
to the initiating admin + project + provider, **spent before any code is exchanged**, a live-session
re-check against that binding, a **server-derived** repository name that never crosses the redirect,
and **push before repoint** so a failed push leaves the project on its working source rather than
pointing at an empty repository.

Its own provider string (`gitlab-create`) and its own callback path, for the reason the GitHub
flows already have theirs: state is spent per-provider, so the handler must know which flow it is
before it can spend anything. ADR-0104's connect callback is untouched.

### 2. No second application

GitLab's `api` scope — the one ADR-0104's connect already asks for — can create a project. GitHub
needed a separate OAuth App only because its App tokens are refused by the equivalent endpoint
(ADR-0120 Amendment 2). So GitLab's third setup step stays "browse your projects", optional, and
publishing works as soon as the OAuth application exists.

### 3. Created **private**, and that asymmetry is correct

`clone.py::_auth_url` injects a credential for the configured GitLab host, so a private GitLab
project clones and its runs start. It does not do so for GitHub, which is why ADR-0120 is
public-only: a private GitHub repository would be one whose runs never start.

Each provider therefore gets **the most private option it can actually deliver**, rather than the
worse of the two for symmetry's sake. The difference is stated per provider in the UI, where the
operator is choosing, rather than smoothed over.

### 4. It finishes credentialed

ADR-0104 already mints a project access token from a user grant. Because creation and minting need
the same `api` scope, one authorization does both: the project ends created, pushed, repointed and
**credentialed**, with no connect step to go and do. A mint failure is not a failure of the publish
— the repository exists and the code is in it — so it degrades to connecting manually.

This is the closest either provider gets to one-click publish. GitHub cannot match it: its App has
to be installed on the new repository, and while an account-wide installation already covers it
(so the GitHub path auto-connects too), a repository-selected installation does not.

### 5. One push implementation, two spellings

`_shared.push_repository_to` is now provider-neutral and both forges call it. They differ only in
how the credential is spelled into the URL (`x-access-token:` vs `oauth2:`), and a second copy of
the hygiene — bounded subprocesses, scrubbed stderr, an explicit URL so the operator's own
`.git/config` is never touched — is how one copy quietly loses a protection the other has.

### 6. The project offers whichever forge can actually do it

`PublishProject` replaces the GitHub-only card on a project whose provider is `unknown`. It lists
the providers this instance can *perform*, not the ones it knows about: offering a button that
fails at the far end of a redirect is not honesty about configuration.

## Consequences

- The two forges are symmetric in capability, not only in shape.
- `POST /api/gitlab/repo/status` and `GET /api/oauth/gitlab/create/start` join the API surface;
  no schema change and no migration (the working path is derived, per ADR-0123).
- The `api` scope is broad — it is the scope ADR-0104 already required for connect, and the grant
  is still discarded in the same request, but a wider scope is being used for one more operation.
  That is the cost of not needing a second application, and it is recorded here rather than
  discovered later.

## Alternatives rejected

- **Public GitLab projects, to match GitHub.** Symmetric and worse: GitLab can clone a private
  project, so this would publish code more widely than necessary for the sake of a matching
  sentence in two docs.
- **A separate, narrower OAuth application for creation.** GitLab has no scope between `api` and
  read-only that can create a project, so a second application would carry the same scope for the
  same work and double the setup.
- **One shared route for both providers.** The state provider, the credential shape, the
  visibility decision and the finishing step all differ. A single route would be a chain of
  branches whose only shared part is the ordering — which is already shared, in the tests.

## Status of the evidence

Unit-tested: the `api` scope and bound state on start; refusal for a project already on a forge and
for a non-admin; the spend-before-exchange ordering; the session re-check; the derived name;
push-before-repoint and the fail-closed no-repoint on a push failure; the access-token mint; and the
UI offering both forges, withholding an unconfigured one, and not dead-ending when neither can
publish.

**Not demonstrated live** ([ADR-0110](ADR-0110-agent-ownership-and-environment-truth.md)): the
GitLab authorize round-trip and an actual created project. The GitHub equivalent is live-validated;
this one inherits its shape but not its evidence.
