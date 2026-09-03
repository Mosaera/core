# ADR-0115: First run is a gated flow, and where it resumes is derived from facts

- Status: superseded by [ADR-0116](ADR-0116-setup-is-a-terminal-wizard.md)
- Removed from the code: 2026-08-26. The five screens, `lib/setupFlow.ts`, `api/setupFlow.ts`,
  `GET /setup/presets`, `GET /setup/state` and the `PUT /setup/ack/{step}` record all went with the
  flow. What outlived it: `GET /api/preflight` (the degradation banner polls it inside the
  authenticated shell, for every signed-in user, long after setup) and `SetupBanner`/`CheckRow`.
- Superseded because: Setup moved to the terminal on 2026-08-25 and the five-screen browser flow is removed. The reasoning below — resume DERIVED from facts rather than a stored cursor, and a control that reads as present but never fires — still holds, and is why this file is kept rather than deleted.
- Implementation: shipped
- Date accepted: 2026-08-25
- Owners: Alejandro Rengifo
- Related issue / MR: #119 (first-time setup)
- Supersedes / Superseded by: — (**amends** [ADR-0040](ADR-0040-first-run-setup-token.md): the token is now validated on a screen of its own, by an endpoint that creates nothing)
- Related: [ADR-0004](ADR-0004-auth-and-session-model.md) (the bootstrap routes the middleware leaves open; the first-admin self-lock), [ADR-0005](ADR-0005-config-in-ui-settings.md) (a model is chosen from a set, never typed), [ADR-0035](ADR-0035-infrastructure-failure-is-loud.md) (capability-degraded stores), [ADR-0051](ADR-0051-login-backoff-and-enumeration-equalization.md) (the per-subject backoff this endpoint joins), [ADR-0104](ADR-0104-gitlab-oauth-connect.md) / [ADR-0114](ADR-0114-github-delivery-on-an-app-installation.md) (delivery is registered per instance, connected per project)
- Related threat model: [TM-0002](../threat-models/TM-0002-mosaera-api-web-server.md) (a fourth unauthenticated `/api` route)
- Review trigger: a sixth step is added, or any step's completion stops being observable from the server

**Decision summary:** First run becomes five ordered screens — setup token · administrator ·
environment · models · delivery — that stand between a fresh install and the application. **Which
screen an operator sees is computed from facts the server already exposes, not from a saved
cursor**, so closing the tab, reloading, or arriving from another machine lands on the same step. The
only state stored is which steps have been *answered*, because an answer is the one thing that
leaves no fact behind.

## Context

Two unrelated things stood between a new install and the product: one form that asked for the
one-time token *and* the administrator's credentials together, and — after login — a single
model-configuration screen that could be skipped. The combined form meant a **wrong token was
refused only after** the operator had also chosen a username and a password, on a form they had no
reason to doubt. The skippable model screen meant an instance could be entered in a state where
nothing could run.

The owner asked for an ordered flow, blocking until complete, that survives a reload.

## Decision

### 1. Five screens, and the token gets its own

`POST /api/auth/setup/check` validates the token and creates nothing. It joins the three bootstrap
routes the auth middleware leaves open (ADR-0004 §5).

**It never spends the token.** `spend_setup_token()` is the atomic single-winner (`DELETE …
RETURNING`) and stays inside the same request that creates the administrator; screen 2 still submits
token and credentials together in one `POST /auth/setup`. A check that consumed the row would make
setup uncompletable; a check that *recorded* acceptance for a later request to trust would reopen
the race ADR-0040 closed.

**It discloses nothing new**: `_enforce_setup_token` already runs *before* `validate_credentials`,
so `/auth/setup` is a token oracle today. What it does add is an unauthenticated, pre-credential
route that is cheap to call — one SHA-256, no scrypt — which is precisely the gap `loginguard`
documents. It therefore takes the same per-subject backoff, **keyed on the socket peer**, because a
token-only screen has no username to key on. Not `X-Forwarded-For`: a forwardable header is
attacker-controlled, so keying on it would let one caller rotate into a fresh bucket per guess.
Behind a proxy every client collapses into one bucket — stricter than intended, never looser.

### 2. The resume point is derived

| Screen | Complete when | Read from |
|---|---|---|
| token | verified this session · or an account exists · or no gate is armed | `/auth/status` |
| administrator | an account exists | `/auth/status` |
| environment | docker + images + database are not failing | `/preflight` |
| models | `can_run` | `Preflight.can_run()` |
| delivery | a GitLab OAuth app or a GitHub App is registered | `/setup/state` |

A stored cursor can disagree with reality — it survives a database reset, a revoked key, a machine
that lost Docker. A derivation cannot, and it is correct across devices for free.

### 3. Exactly one thing is stored, and it is not progress

`settings.json` gains `setup_steps_acked`. A step is **answered**, which is not the same as
observable:

- `environment` and `delivery` are optional. `can_run` deliberately excludes Docker, the images and
  the database — *"gating the whole application on them would lock a newcomer out of the product
  while they fix a daemon"* — and a project can be driven end to end without ever opening a merge
  request.
- `models` is recorded for a different reason. Derived from `can_run` alone, an instance that
  finished setup and later lost its backend would put **the whole application** back behind the
  flow. That is a lockout, and the deferred-setup banner is the control that already exists to
  report exactly that condition.

The token screen is deliberately **not** ackable: passing it leaves no durable trace, so a reload
asks again. That is correct rather than unfortunate — nothing proves the visitor ever held it.

### 4. The models screen recommends nothing

Mosaera is bring-your-own-model. The operator's hardware is unknown to us, they may be running cloud
only, and every capability number this project has published was measured on **one** binding. So the
screen connects first and assigns second, and its dropdowns are populated from what the machine
actually has (`/api/tags`) or what a key actually grants (`POST /providers/test`) — never from a
shipped list of suggestions.

Each role is a card carrying the actor the operator will watch during a run. Role → graph node is
server data (`AgentSpec.nodes`), so the bridge to the run timeline's cast is derived rather than
hand-written a fourth time.

What a card states about models is a **requirement**, never a recommendation: every role is built
with `create_agent(tools=…)`, so **every** role needs a tool-calling model; the coder and the tester
additionally write files and run tests. The web previously claimed only those two needed tools,
which is false against `ROLE_TOOL_ALLOWLIST` — `read_only` is now carried through `_role_meta()` and
says the true thing.

## Consequences

- A newcomer cannot enter an instance that cannot run anything. That is the point, and it is also
  the risk: both connection paths must stay genuinely completable or the flow is a wall.
- The 60-minute token TTL now spans two screens. Expiry mid-flow is recoverable only by restarting
  the service — the same remedy as before, but the window is wider.
- Delivery is **registered** per instance and **connected** per project; the screen says so rather
  than implying an instance-level connection that does not exist.
- The preset-based first-run wizard (economy/balanced/premium) is removed from this path. Presets
  remain in Settings → Models; they route on locality and price, which is a ranking the owner
  explicitly ruled out of first run.

## Alternatives considered

- **A stored progress cursor.** Rejected: it is a second origin for a question the server can
  already answer, and every way it goes stale strands the operator on the wrong screen.
- **Holding the token client-side and validating only at submit.** Cheapest, and it recreates the
  exact dead end this flow exists to remove.
- **Recording "token accepted" server-side for screen 2 to trust.** Reopens the first-admin race.
