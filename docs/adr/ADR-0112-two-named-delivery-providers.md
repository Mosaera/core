# ADR-0112 — Two named delivery providers, detected not configured

- **Status:** proposed
- **Owners:** @rengi
- **Amends:** [ADR-0102](ADR-0102-delivery-spine-truth-up.md) — narrowly, and only its consequence
  "no forge abstraction is introduced by this ADR, **and none is authorized**". That sentence
  withheld authorization pending a decision; this is that decision. ADR-0102's spine — `push` and
  `open_pr` outside `GATED_ACTIONS`, the authenticated endpoint or `auto_open_mr` as the human
  control — is unchanged and reaffirmed in §4.
- **Related:** [ADR-0001](ADR-0001-stack-and-architecture.md) (the `gh`-CLI draft-PR flow and its
  CLI-only caller set), [ADR-0103](ADR-0103-mr-rest-metadata-api-token.md) (the three-way
  token-routing invariant a second forge must not break),
  [ADR-0104](ADR-0104-gitlab-oauth-connect.md) (why GitHub was deferred, and what changes that),
  [ADR-0089](ADR-0089-intake-reachability.md) (a capability boundary expressed as data, checked
  before the work rather than after it), [ADR-0042](ADR-0042-clone-token-host-equality.md) (host
  equality, and the look-alike-host defect that made it necessary)
- **Scope:** connectors + api + web · **no trust-boundary change in slice 1** (no new credential, no
  new egress, no schema); slice 2 adds both and carries its own red-team · threat model
  [TM-0002](../threat-models/TM-0002-mosaera-api-web-server.md) updated
- **Invariants:** *Capability through Auditability*, *Honest Parking*, *Control Points, not Headcount*

**Decision summary:** Mosaera recognizes **exactly two** delivery providers, `gitlab` and `github`,
named in code as concrete branches — not a registry, not a plugin seam. Which one a project uses is
**derived from its source URL on every call**, never stored and never chosen in a form. A source
that matches neither is `unknown`, and says so. Slice 1 makes the refusal honest and early; slice 2
makes GitHub actually deliver, on a GitHub App installation token.

## Context

The wired delivery path is GitLab-only. `packages/connectors/mosaera_connectors/github.py` has
existed, exported and tested, since ADR-0001 — but its sole non-test caller is the core CLI's
`--open-pr` (`packages/core/mosaera_core/cli.py:227`). A GitHub user driving from the web UI does
the whole job — intake, backlog, runs, approval, a commit — reaches the Delivery page, presses the
button, and receives:

> `400 — project source is not on the configured GitLab; merge targets GitLab repos you can push to`

Two things are wrong with that, and only one of them is the missing feature. The message reads as
*your URL is wrong*, which is false; it sends the operator to re-check a setting that was correct.
And it arrives at the finish line, after all the work, when it was knowable at the first character
of the source URL.

That second half is the **F64 defect class**. F64 found that the `api`-scoped token bit — which
alone decides whether a project can ever read as "Delivered" — was invisible until the end; the
disposition was *surface it*, and `DeliveryCredentials.tsx` was the fix. The provider is the same
bit one level up, and it was still invisible.

The 2026-08-24 alpha-readiness audit filed this as alpha-outsider stopper #2 (#120): *"a GitHub PR
opened from the Delivery page, or at minimum an honest GitLab-required gate at intake instead of a
dead end at the finish line."*

## Decision

### 1. Two providers, named — and no third mechanism

`DeliveryProvider = Literal["gitlab", "github", "unknown"]`
(`packages/connectors/mosaera_connectors/provider.py`). Two concrete branches in the two places that
already branch. **No plugin API, no forge registry, no adapter protocol, no `Team`-style seam** —
those remain on the North Star's *Not Yet* list, and this ADR authorizes none of them. A third forge
is a new decision requiring a new ADR, not a new entry in a table.

This is the narrow authorization ADR-0102 withheld. ADR-0102 was right to withhold it: it was
describing a port it had not scoped, and an abstraction invented for one hypothetical caller is the
failure mode `CLAUDE.md`'s *Change discipline* exists to prevent. Two named branches for two real
providers is not that abstraction.

### 2. The provider is DERIVED, never stored

`detect_delivery_provider(source_url, gitlab_url)` is a pure function of the project's `source_repo`
and the configured GitLab host. There is **no `provider` column, no migration, and no selector at
project creation**.

Acceptance criterion 1 of #120 permits either ("chosen **or detected** at project creation — remote
URL is a strong signal"), and detection is the better of the two for a reason this repo has already
paid to learn: *a status a human types is structurally unfixable; a status that is DERIVED cannot go
stale* (`scripts/check_doc_claims.py`, and the research behind it). A stored provider is a second
origin for a fact the URL already carries, and would silently disagree with it the moment a
project's source changed. It would also re-open the intake surface ADR-0104 Amendment 2 deliberately
closed when it removed the New Project token field.

**Host EQUALITY, never substring**, inheriting `is_gitlab_source`'s parser rather than writing a
second one — `_host_of` moved to `_shared.host_of` for exactly this reason. ADR-0042 records what a
substring test cost: `gitlab.example.com.evil.io` matched, and a scoped PAT was injected into an
attacker-chosen host. Detection decides which credential a later slice spends and against which
host, so the same defect here would be the same severity. `github.com` and `www.github.com` only.

**GitHub Enterprise Server is `unknown`.** A GHES install lives on the customer's own host and is
indistinguishable from any other self-hosted forge by URL alone. Guessing would reintroduce the
dead-end-at-the-finish-line failure this ADR exists to remove; supporting it means asking the
operator, which is a decision and not a parser fix.

### 3. Naming: `delivery_provider`, never bare `provider`

`provider` already means an LLM backend (`mosaera_core.models`, the `(provider, model)` binding) and
a backlog store (`connectors.backlog.BacklogProvider`). A third meaning on the same word, in a
codebase where `routes/_providers.py` is about model credentials, is a readability trap that would
be paid for indefinitely.

### 4. ADR-0102's spine is untouched

Opening a request stays **out of `GATED_ACTIONS`**. No `interrupt()` is added, no approval row is
written, and the human control remains the authenticated endpoint or the `auto_open_mr` opt-in.
Slice 1 changes no gate, no approval path, and neither of the two human-pause sites. The delivery
gate (`packages/policies/approval.py`) is not touched. This is pinned by a test, not by this
sentence.

The capability endpoint **informs and never gates**: every refusal it reports is one `delivery.py`
already returns. It states them in advance instead of surfacing them as a 400 at the end.

`can_finish` deliberately answers only *could a request be opened at all*. An empty diff or a
diverged base still refuse later, and promising otherwise would replace one dishonest signal with a
more confident one — which is not an improvement (*Honest Parking*).

### 5. Slice 2's credential is a GitHub App installation token

Recorded here because it is the part that changes ADR-0104's answer, and because it is the part not
yet built.

ADR-0104 deferred GitHub on a specific and correct ground: *"a plain OAuth App can't mint a clean
per-project token"*, and *"revisit with a GitHub App if/when GitHub delivery is scoped."* #120
scopes it. A **GitHub App** issues per-installation tokens, scoped to the repositories the operator
selected and expiring in an hour — which is the clean per-repo credential the OAuth App could not
give, and is a *stronger* posture than GitLab's stored PAT: only the installation id is persisted,
and the token is minted per delivery.

This preserves ADR-0103's three-way token-routing invariant by extending it rather than breaching
it: project-write / project-api / global-adhoc / **project-github-installation** never cross. It is
the reason slice 1 does **not** wire the existing ambient-`gh`-auth path to an HTTP caller — doing so
would spend a *host-global* credential on a project-associated remote write, which is precisely what
ADR-0102 §2 forbids.

**GitHub delivery will be endpoint-only and never available to the autonomous sweep**, mirroring
ADR-0103's "the autonomous sweep never touches `gitlab_write.py`". The most-automated, unattended
path does not gain a second forge's credentials.

Also recorded: `github.py` has never run outside the CLI. Before any HTTP caller reaches it, it
needs the hardening every GitLab counterpart already has — a `subprocess` timeout (a hung `gh` would
occupy a FastAPI worker indefinitely), `OSError`/`TimeoutExpired` handling, error strings capped at
`[:200]`, and `shutil.which("git") or "git"` rather than a bare `"git"`.

## Consequences

- A GitHub-sourced project now states its provider, that it cannot finish, and why — on the Delivery
  page, before any work is spent. The controls that could only 400 are **absent rather than
  present-and-broken**, the rule `DeliveryWorkspace.tsx` already states as "a button that 403s is the
  defect this review keeps finding".
- A new skip reason `github_not_connected` joins `SkipReason`. `not_gitlab` keeps its meaning and its
  wording for genuinely unrecognized hosts; nothing that previously succeeded changes.
- `GET /api/projects/{id}/delivery/capability` is a new read, middleware-gated only — it must be
  visible to exactly the people who see the delivery controls, or the page is back to offering a
  button whose refusal only the server knows.
- **Nothing newly succeeds in slice 1.** This is asserted by a test, because the failure mode of a
  capability surface is that it quietly becomes an authorization surface.
- TM-0002 gains a row for the second forge host (slice 2: a new egress destination and a fourth
  credential lane). Slice 1 adds neither.
- `docs/getting-started.md` was telling users that delivery opens a request against "GitLab or
  GitHub" and that this is a *"gated"* action. Both were false — the wired path was GitLab-only, and
  ADR-0102 removed the gate. Corrected here. ADR-0102 §"the invisible-control class had relocated
  into prose" records that this exact defect was hunted before and this file was missed.

## Alternatives rejected

- **A forge plugin API / adapter protocol.** The Not-Yet list, and #120's explicit non-goal. Two
  concrete providers do not need a seam, and one built for a third that does not exist is
  architecture without a caller.
- **A `provider` column chosen at project creation.** A second origin for a fact the URL already
  carries (§2), it re-opens the intake surface ADR-0104 Amendment 2 closed, and it would collide
  with #121's concurrent work on that same form.
- **Wiring the existing ambient-`gh`-auth path to the endpoint now.** It would ship GitHub delivery
  in one small slice — by spending a host-global credential on a project-associated write, breaking
  ADR-0102 §2 and reducing the "can this project finish?" bit from a project fact to a host fact,
  which is a weaker answer to F64 than the one this ADR gives.
- **Guessing GitHub Enterprise from the URL shape.** Unfalsifiable, and its failure mode is the
  dead end this ADR removes (§2).
- **Folding `merge_state_readable` into `can_finish`.** It would hide F64's own bit again: a project
  can open a merge request and still never read as delivered.

## Status of the evidence

Slice 1's criteria (#120 1, 3, 5) are closed by unit and endpoint tests plus a live check on the
staging instance. **Criterion 4 — a real run's delivery ending in an actual draft PR on a real
GitHub repo — is OWED**, and is not claimed by slice 1. Per ADR-0110, it will not be marked done on
unit tests. It requires a registered GitHub App installed on a real repository; the reproduction
steps are recorded in `docs/roadmap.md`.

Noted as a risk rather than assumed away: **ADR-0104's own live round-trip has been OWED since
2026-08-14** and has never completed against a real instance. Slice 2 is therefore the second
unproven forge round-trip in this repository, and is scoped as such — it does not inherit confidence
from a GitLab precedent that has not itself been demonstrated.
