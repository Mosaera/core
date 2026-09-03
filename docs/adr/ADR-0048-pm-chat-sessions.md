# ADR-0048: PM chat sessions — per-project conversation threads

- Status: accepted
- Date: 2026-07-17
- Owners: Alejandro Rengifo
- Related issue: `#30` (PM session & context management), Wave A `[prereq]` — see `docs/roadmap.md`
- Related threat model: none (no new trust boundary — see *Security implications*)

## Context

Quincy (the PM) was a single, unbounded **forever-chat per project**: one ever-growing
`project_messages` list keyed only by `project_id`, read whole on every turn and bounded only
by a token-budget trim at prompt-assembly time. There was no notion of a conversation *thread*.

This blocks the north star. The firm layer needs Quincy to front **multiple projects and teams**,
each with its own session, context boundary, and history — one forever-chat cannot hold parallel
lines of work without them bleeding together. It also hurts today: a single unbounded transcript
mixes unrelated discussions (a bug triage, a roadmap debate, an onboarding interview) into one
scroll, and the token-trim silently drops the older half.

The cross-*project* boundary was already handled (everything is `project_id`-scoped). What was
missing is a finer, within-project axis: a **session**.

## Decision

Introduce a **PM session** — a named conversation thread within a project. **Chat history is
scoped to a session; project knowledge is not.** The brief, backlog, runs, repo overview, and the
project-context registry stay project-scoped and are shared across all of a project's sessions —
they describe the *project*, not a conversation. Only the message history threads.

### Schema (Alembic 0013)

- New **`pm_sessions`** table (`id` = `sess-<hex>`, `project_id` FK CASCADE, `title`,
  `created_at`, `updated_at`, `archived_at`). The model lives in `models_chat.py`, re-exported
  from `models.py` to keep that module under the 500-line ceiling (same split pattern as
  `models_auth.py`).
- **`project_messages.session_id`** — nullable FK to `pm_sessions` (CASCADE). Nullable *only* so
  the migration can backfill; the store always sets it going forward.
- **Backfill**: every project that already has messages gets **one default session**, and all its
  turns are adopted into it — the old forever-chat becomes each project's first session. The
  session's created/updated span the real message times and its title derives from the first user
  turn, so a migrated project is indistinguishable from a freshly-created one. Nothing is
  orphaned; no history is lost.

### Store (`memory` leaf)

A `SessionsMixin` owns the lifecycle: `create_pm_session` / `get_pm_session` / `list_pm_sessions`
(active-first by recency, `message_count` included) / `rename_pm_session` /
`set_pm_session_archived` (soft — `archived_at`, transcript preserved) / `ensure_default_pm_session`.
`add_message`/`list_messages` gain an optional `session_id`: given → that thread; omitted →
resolve/create the project's current session on write, and read the **whole project** (the
decomposition path, which synthesizes the brief from everything the stakeholder said). Writing the
first user turn **auto-names** an untitled session and bumps its recency. A module function
`resolve_or_create_default_session` is shared by the write path and `ensure_default_pm_session`, so
"the current session" has exactly one definition and no cross-mixin coupling.

The methods are deliberately **`pm_`-prefixed**: `AuthMixin` already owns `create_session` for
*login* sessions, and `AppContext` owns `get_session` for *run* sessions. Three distinct "session"
concepts share the store's surface; the prefix keeps the PM one from shadowing login-session
creation in the MRO (which it silently would, unprefixed — caught by mypy + the rename).

### API

New session routes: `GET/POST /projects/{id}/sessions`, `PATCH /projects/{id}/sessions/{sid}`
(rename and/or archive). A named session is always addressed under its project — a mismatched pair
404s, so one project can never read or mutate another's threads. The message routes gain the scope
seam: `GET …/messages?session_id=` and a `session_id` on the POST body / `pm_chat`. Omitted on POST
→ `pm_chat` resolves the project's current session (first send creates it); omitted on GET → the
whole-project transcript (legacy). The **agent stays session-agnostic** — `pm.chat` is still a pure
function of (model, context, history, message); the boundary is enforced entirely by what history
the store returns.

### Web

The PM tab gains a functional **session switcher** (`PmSessionBar`): a recency-ordered dropdown +
"New" + "Archive current". The selected session lives in the URL (`?session=`), so switching and
refresh are stable and shareable, and it **self-heals** — a stale/archived `?session=` falls back
to the most-recent live session rather than showing an empty void. React-Query keys become
`["messages", projectId, sessionId]` and `["sessions", projectId]`. Switching threads clears
thread-local UI (a pending changeset proposal must not bleed across sessions). The pre-backlog
intake (`StartWorkspace`) is left as a single conversation — no switcher — by making the switcher
props optional; it sends with no session id and the server uses the project's default.

## Options considered

- **Per-session vs shared project knowledge.** Moving the brief/backlog/context registry
  per-session was rejected — those describe the project, not a conversation; duplicating them per
  thread would fragment the project's understanding and multiply stale-context risk. Only chat
  history threads.
- **Nullable `session_id` + backfill vs a hard NOT NULL.** A NOT NULL column can't be added to a
  table with existing rows without a default; backfilling into a real default session (not a
  sentinel) preserves history honestly and keeps the column meaningful. The store always populates
  it, so the nullability is a migration artifact, not a live state.
- **`pm_`-prefixed vs bare method names.** Bare `create_session`/`get_session` collide with the
  auth and run "session" concepts; the PM mixin would shadow login-session creation in the MRO.
  The prefix is the cheap, unambiguous fix (and reads clearly at call sites).
- **URL `?session=` vs component state vs a new route segment.** A search param is
  refresh/share-stable and self-heals from the live session list without an extra route level or a
  synchronizing effect.
- **Create-on-mount vs create-on-first-send.** Eagerly creating a session when the PM tab opens
  would litter glanced-at projects with empty threads; resolving/creating lazily on the first send
  (`ensure_default_pm_session`) keeps sessions honest — one exists exactly when there's a reason
  for it.
- **Rename in the UI now vs later.** The lifecycle the issue requires is create/switch/archive plus
  auto-naming; rename is supported in the store + API but left out of the switcher UI for now (the
  first user turn names a thread well enough), to keep the surface functional-not-ornamental.

## Security implications

No new trust boundary. Sessions are a child of the project and inherit its `CASCADE` delete and its
existing auth (session-or-service-token middleware; config/secret writes still need admin). The one
authorization rule this adds — a session is only ever addressed **under its owning project**, and a
project/session mismatch 404s — closes the only new cross-tenant read/write path. `pm.chat` remains
untrusted-input-as-data; nothing about sessions changes what reaches the model. No change to
`packages/policies`, so no threat-model note is required.

## Operational implications

- One Alembic migration (0013): `pm_sessions` + `project_messages.session_id` + the backfill.
  Downgrade drops the column, index, and table. Schema changes go through Alembic, never
  `create_all`. **Coordinate the revision with `#29`** (concurrent, also owns `memory`): both base
  on `0012` → whoever lands second rebases and re-points `down_revision`.
- Backfill is a bounded one-time pass (one default session + one UPDATE per project with messages);
  no data is deleted or rewritten beyond stamping `session_id`.
- No restart concerns — sessions are ordinary durable rows.

## Consequences

- Good: Quincy can hold parallel, isolated conversations per project — the prerequisite for the
  firm (Quincy fronting multiple teams) and for onboarding (the interview lives in a session) — and
  daily chat is no longer one unbounded scroll silently trimmed at the token budget. History is
  thread-scoped; project knowledge stays shared and coherent. The agent stays a pure function; the
  boundary is a store concern.
- Cost: a second scoping key threaded through the message store, the chat API, and the PM tab; a
  third "session" concept in the store's vocabulary (mitigated by the `pm_` prefix).
- Follow-up: **per-team** sessions (this ADR ships per-project; `team` is a clean future column on
  `pm_sessions`), a session-rename affordance in the UI, and pulling the switcher into the firm/
  cockpit surface (`#11`) once teams land.
