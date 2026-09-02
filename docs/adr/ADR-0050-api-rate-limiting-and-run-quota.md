# ADR-0050: Per-credential API rate limiting + a durable daily run quota

- Status: accepted
- Date: 2026-07-17
- Owners: Alejandro Rengifo
- Related issue: #34
- Related: [ADR-0004](ADR-0004-auth-and-session-model.md) (session-or-token; the identities this meters), [ADR-0005](ADR-0005-config-in-ui-settings.md) (env>stored>default — and the **env-only** class this joins), [ADR-0035](ADR-0035-infrastructure-failure-is-loud.md) (`guard_bind`/`guard_memory`; a misconfigured control must be loud, and the `--network host` clamp-at-the-sink lesson), [ADR-0038](ADR-0038-url-ids-are-untrusted-path-input.md) (validate at the boundary, contain at the sink), [ADR-0046](ADR-0046-posture-and-autonomy-governance.md) (where these limits will eventually be posture-clamped)
- Related threat model: [TM-0002](../threat-models/TM-0002-mosaera-api-web-server.md) (**updated** — new metering surface beside auth)

## Context

The roadmap carries "per-user rate limiting / quotas on the API" as independent debt. The API runs
code and spends a model budget, so a single runaway client — a retry loop, a stuck script, a
hostile caller with a valid credential — can saturate the interactive path and burn real money
before anyone notices. There is currently **no request metering of any kind**.

Two constraints shape the design more than the feature does:

1. **The interactive path must not pay for it** (the DNA: perceived latency is a feature). Whatever
   runs on every request has to be approximately free — no model call, no extra database round-trip.
2. **It sits beside authentication.** `app.py` holds `guard_bind` and the session/token middleware
   and is near the 500-line modularity ceiling. Metering must not perturb that verification path.

## Decision

### 1. Two controls, two mechanisms — split by what each one costs

They look like one feature and are not:

| | **Rate limit** | **Run quota** |
|---|---|---|
| Question | "too many requests right now?" | "too many runs today?" |
| Runs on | **every** `/api` request | **only** `POST /api/runs` |
| Storage | **in-process** fixed window | **durable** (Postgres, Alembic `0015`) |
| Keyed by | the **credential** (session cookie / token) | the **account** (`user:<id>` / `token`) |
| Survives restart | no (by design) | yes |

The split follows the cost constraint. A per-request control must not touch the DB, so it is
in-process and forgets on restart — acceptable, because a restart is not an attacker-reachable
reset (it costs the operator more than the attacker). A daily quota *must* be durable to mean
anything, and it can afford a DB write because it only fires on run creation — a rare, already
expensive action.

The keying differs for the same reason, and the difference is load-bearing: a per-session key is
fine for a rate limit but would let a user reset their daily cap **by logging in again**, which
would make the quota decorative. So the quota resolves the real account (one DB read, on run
creation only).

### 2. Config is ENV-ONLY — `MOSAERA_RATE_LIMIT_PER_MIN`, `MOSAERA_RUN_QUOTA_PER_DAY`

`#34` asked for `GENERAL_KNOBS` (env > stored > default). We are **not** doing that, for two
reasons — one architectural, one procedural.

**Architectural.** `GENERAL_KNOBS`' own docstring says it *"deliberately EXCLUDES infra / bootstrap
/ secret knobs (API host/port/token, admin token, db_url, sandbox backend/image, home) — those stay
env-only,"* and ADR-0005 fixes that as the rule. A **request-rate limit on the API server** is
squarely that family: it is a property of the deployment, not of a run. Adding it to
`GENERAL_KNOBS` would make it the first API-infra knob in a structure that documents excluding
them — and would put a protective control on the same write path a compromised admin session
already owns.

**Procedural.** A `GENERAL_KNOBS` knob is not a one-line append: it touches `_knobs.py`,
`_settings.py`, `settings_store.py` and `tests/test_config.py` in `packages/core` (two of them
declared **hot files**) plus `GeneralSettings.tsx` in `apps/web` — i.e. it collides with **both**
concurrently-running sibling issues (`#35` core/agents, `#36` web). The parallel-sessions protocol
says sequence, don't overlap. Env-only keeps the whole feature inside `apps/api` + a new memory
table, disjoint from both.

Values are parsed and **range-checked at boot**, and a bad one is **loud** (`SystemExit`, the
`guard_bind`/`guard_memory` precedent). This is the env-var analogue of the no-free-text rule: the
UI rule exists so a typo can't produce invalid config, and the same obligation holds here. An
operator who sets `MOSAERA_RATE_LIMIT_PER_MIN=1O0` (letter O) must not silently run at the default
believing they run at 100 — that is the silently-wrong-config class ADR-0035 exists to kill. **A
control you cannot read is a failure, not a suggestion.**

Defaults: **rate limit ON at 300/min** (a runaway client is the common failure; 5 rps sustained per
credential is far above any real SPA and far below a hot loop), **quota OFF**. A runs/day cap is a
fairness *policy* with no universally right number — the same reason `run_max_usd` /
`run_max_tokens` default to `None`. Deny-by-default governs *authorization*; a quota is not an
authorization decision.

### 3. The limiter runs INSIDE auth — everything it meters is already authenticated

Starlette's `add_middleware` inserts at position 0, so the **last** registered middleware is the
**outermost**. `install_rate_limit` is therefore called **before** the auth middleware is
registered, which places it *inside* — running *after* authentication.

This ordering is the property that makes an unverified cookie a safe bucket key: an invalid one is
401'd by auth and never reaches the limiter, so a client cannot mint fresh buckets with junk
credentials. It also means an unauthenticated flood is rejected by auth and never pollutes a
bucket. The ordering is asserted by a test (`a 401 wins over a 429`) because it is invisible in the
source — the code reads as if the limiter comes first.

### 4. There is NO loopback exemption — and that is the important decision here

`#34` says "loopback/admin exempt as appropriate." Exempting loopback would have been the obvious
reading, and it is a **trap**: it would disable rate limiting entirely in the exact deployment
where it matters.

The codebase already documents why, at `_require_local_config`: *"behind a reverse proxy (the
recommended exposed topology) every client appears as the proxy's address (usually 127.0.0.1), so
this reads as same-host for everyone — it is a same-host guard, NOT an authorization boundary in a
proxied deploy."* `X-Forwarded-For` is deliberately **not** trusted (a direct attacker can spoof
it). So on a proxied, exposed instance a loopback exemption is equivalent to **"rate limiting off"**
— while looking, in config, like it is on.

So: **the discriminator is the credential, not the socket peer.** A request with no credential is
skipped (auth 401s it, or the instance has no auth configured at all — a dev box the auth
middleware also leaves open). That single rule delivers the *intent* of "loopback exempt" — local
dev is untouched — without inheriting the proxy blindness. It also keeps the hot path free of any
DB call: credential *presence*, not a `users_exist` probe, is what we branch on.

**Admin** is exempt from the **quota** only (fair-share is between users; the operator is not
competing for their own capacity, and run budgets still bound them), and **not** from the rate
limit — an admin's runaway loop saturates the box exactly like anyone else's, and exempting them
would cost a DB lookup per request to discover.

### 5. Check-and-consume is ONE atomic statement

`QuotaMixin.try_consume_run_quota` is a single conditional Postgres UPSERT
(`ON CONFLICT ... DO UPDATE ... WHERE count < :limit RETURNING count`). Read-compare-write would be
a race: two concurrent submits both observe `count < limit` and both proceed, admitting
`limit + 1`. The conditional `WHERE` makes the check and the consume one step, so the cap holds
under concurrency with no lock and no compensating decrement. A conflicting row that fails the
`WHERE` returns no row at all — which *is* the "over quota" signal.

A refused attempt consumes **nothing**, so a client retrying past its cap cannot inflate its own
counter (otherwise recorded usage stops meaning "runs started").

## Options considered

- **`GENERAL_KNOBS`, as `#34` specified.** Rejected — §2. Architecturally the wrong family, and it
  collides with both live siblings. Recorded as a deliberate deviation from the issue's acceptance
  criteria, with a follow-up to promote it once `core`/`web` are free.
- **Exempt loopback.** Rejected — §4. It is the reading the issue invites and it silently disables
  the control on every proxied deployment.
- **Rate-limit by IP.** Rejected — same root cause: behind a proxy every client shares one address,
  so an IP limit would throttle *all* users together (one attacker locks out the team), and fixing
  that needs `X-Forwarded-For`, which we deliberately do not trust.
- **Redis / a shared counter store.** Rejected — a new infra dependency for a self-hosted
  single-node product. The honest cost is per-worker limits (§Operational).
- **A token bucket / sliding window.** Rejected — a fixed window is one dict lookup and no
  background task. The cost is a boundary burst (up to 2x across adjacent windows), acceptable for
  a control whose job is stopping a runaway loop, not shaping traffic.
- **Enforce the quota in `routes/runs.py` (a dependency).** Rejected — `routes/` belongs to a
  sibling session this cycle. The middleware matches `POST /api/runs` literally instead, with a
  test asserting the app still serves it so a rename fails **loudly** rather than silently
  un-metering the quota.
- **Count runs from the existing `runs` table.** Rejected — runs are not attributed to an account,
  and the service token has no user row at all. A dedicated counter also makes a refused attempt
  cheap to represent.
- **Put the limiter in `app.py`.** Rejected — the file is at 395/500 lines and holds the auth path
  `#34` explicitly says not to perturb. A leaf module keeps `app.py`'s change to an import and one
  call, and makes the limiter unit-testable without an app.

## Security implications

- **New surface beside authz** → TM-0002 updated. It is metering, not authorization: it can only
  ever *refuse* a request that auth already accepted. It cannot grant anything, which bounds the
  blast radius of a bug here to availability (a wrong 429), never to access.
- **The proxy blindness is the headline** (§4). Any future exemption keyed on `request.client.host`
  re-opens it. Stated here so a later "just exempt localhost" patch has to argue with this ADR.
- **Login brute-force is explicitly OUT of scope.** `/api/auth/login` is an open path with no
  credential yet, so the only key available is the IP — unreliable behind a proxy (see above), and
  limiting by it would let one attacker lock every user out through the shared proxy address. A
  real answer needs per-account lockout/backoff in the auth store, which is auth logic `#34` says
  not to touch. **Logged as a follow-up, not silently skipped** — an operator should not read
  "rate limiting shipped" as "brute-force protection shipped."
- **Not a defense against a credential holder deliberately evading it.** A caller holding the
  service token can present rotating cookies and land in fresh buckets. This is inherent to *any*
  limiter keyed on client-supplied identity, and the holder is already authorized for API access —
  the answer to a hostile credential holder is revocation, not a counter. The control's honest
  scope is **accidental runaway and unprivileged abuse**.
- **Credential rotation is bounded** so that evasion can't become a memory-exhaustion DoS: the
  tracking dict is capped (`_MAX_TRACKED_SUBJECTS`), pruning stale windows first and clearing as a
  last resort. Without the cap, a rotating caller grows it forever — turning a protection into a
  leak.
- **A live session token never becomes a dict key** — the bucket key is a SHA-256 prefix, for the
  same reason the store only ever holds session hashes.
- **A configured quota with no database refuses to boot.** Otherwise the policy silently does
  nothing — the class `guard_memory` already refuses to start on (ADR-0035).
- **`guard_bind`, session and token verification are untouched.** The limiter reads the credential
  to pick a bucket; it never decides authorization. `subject_for`'s token comparison is constant-
  time anyway, so the classification step adds no timing signal.

## Operational implications

- **Env-only ⇒ a change needs a restart.** Accepted (§2); it is the same contract as every other
  infra knob, and the follow-up below is the escape hatch if it chafes.
- **Multi-worker deployments get per-worker rate limits.** With N uvicorn/gunicorn workers the
  effective ceiling is `N × MOSAERA_RATE_LIMIT_PER_MIN`, because the window is in-process. The
  **quota is exact** across workers (it is in Postgres). Documented rather than solved: solving it
  means a shared counter store, which is a new dependency this product doesn't want. Operators who
  need an exact rate limit should set it to `limit / workers` or terminate at the proxy.
- **Quota rows accumulate** at one per active subject per day — a handful of rows/day on a ≤5-seat
  instance. No sweeper: at that rate a cleanup job would cost more than the rows. Revisit if a
  deployment ever has many subjects.
- **Migration `0015`** (`run_quota_usage`), applied with `make db-migrate`. Additive; downgrade
  drops the table. No existing table is touched, so it cannot break a running instance.
- The 429 carries `Retry-After` (seconds to the window roll / to UTC midnight), never 0 — a
  `Retry-After: 0` invites the hot retry loop the control exists to stop.

## Consequences

**Good.**
- The interactive path gains a real bound at ~one dict lookup per request, and zero when disabled
  (no middleware is registered at all).
- The quota is exact under concurrency, and exact across workers, by construction.
- Both are honest about their limits: loud on misconfiguration, loud when a quota has nowhere to
  count, and a route rename fails a test instead of silently un-metering.
- Entirely disjoint from `#35`/`#36` — it can land in parallel.

**Bad / accepted costs.**
- **Deviates from `#34`'s stated acceptance** (`GENERAL_KNOBS`). Deliberate, argued in §2, owner
  decision recorded — but a reviewer should push back here first if they disagree.
- Not tunable from the UI, and a change needs a restart.
- Per-worker rate limits (exact quota).
- Boundary bursts up to 2x the configured rate.
- The quota's route match is literal; the guard test is what keeps that honest.

**Follow-up work.**
1. **Promote the limits to UI knobs once `packages/core` + `apps/web` are free** (after `#35`/`#36`
   land) — if the env-only argument in §2 is judged too strict. Filed as a follow-up issue.
2. **Per-account login backoff/lockout** in the auth store — the brute-force gap §Security names.
   Needs the auth logic `#34` ringfenced.
3. When posture (ADR-0046) exists, these limits are natural **clamp** targets: a Regulated profile
   should be able to impose a ceiling the local config cannot exceed.
4. Surface remaining quota in the UI / a header, so a client can back off before it is refused.

**Honest residual.** This bounds *accident and unprivileged abuse*, which is what the roadmap asked
for. It is not a defense against an authorized-but-hostile caller (who can rotate credentials), not
brute-force protection, and not exact in a multi-worker deploy. Each of those is written down above
rather than implied by the words "rate limiting".

## Addendum (2026-07-17, #37): the quota is promoted to a UI knob; the rate limit stays env-only

Follow-up #1 above asked whether to promote these limits to `GENERAL_KNOBS` "if the env-only
argument in §2 is judged too strict." #37 made that decision — and the answer is **a split, not a
blanket move**. The original §2/§4/§5 mechanisms are unchanged; only the *config surface* of the
quota moves.

- **`run_quota_per_day` → a `GENERAL_KNOBS` knob** (env > stored > default), surfaced in Settings →
  General → "Run budgets" beside `run_max_usd`/`run_max_tokens`. It is read **live** by
  `ratelimit._live_quota()` on the rare `POST /api/runs` path (and once at boot for the guard), so a
  UI save applies **with no restart** — and the interactive hot path stays untouched (§1 holds,
  because the quota was already a run-creation-only check). It is a **number field, not a dropdown**:
  a quota is a *bounded quantity* (`>= 0`, enforced by `coerce_general_patch`), not an *enumerable
  set*, so the no-free-text rule (ADR-0005, whose target is enumerable strings like the sandbox
  network) does not call for a `<Select>` here — a number box matches the per-run budgets it sits
  with. `0` = no cap.

- **`rate_limit_per_min` stays ENV-ONLY.** The §2 argument is *not* judged too strict for it: a
  request-rate limit on the API server is the deployment-infra family ADR-0005 fixes as env-only,
  its middleware runs on **every** request so its config must stay boot-time to keep that path
  "approximately free" (§1) — a UI knob would force a per-request config read or a dishonest
  restart-required Settings toggle — and its **loud-on-garbage** boot parse matters *more* than the
  quota's because it defaults **ON** (a typo must not silently run at 300).

- **Loudness trade (accepted).** The quota env var keeps its loud boot parse (`load_config`'s
  `_int_env` runs first in `install_rate_limit`, so a garbage `MOSAERA_RUN_QUOTA_PER_DAY` still
  `SystemExit`s). A *stored* (UI) garbage value parses leniently like every other knob (falls
  through to the default) — acceptable precisely because the quota is **off by default + opt-in**:
  a typo yields "off", which the operator notices, unlike the always-on rate limit. A live quota
  with no database is inert (the whole quota feature needs Postgres); the boot guard still catches
  the boot-time misconfiguration loudly, now for a stored value too.

**Scope note (TM-0002):** an admin can now set/disable the quota through the existing admin
config-write path (the same path that already governs every knob) — no new external surface. The
blast radius is unchanged: metering can only refuse, so a wrong value costs availability, never
access. `rate_limit_per_min` is unmoved, so the abuse control that runs on every request is still
not reachable from the UI. **Follow-up #1 is resolved** (quota promoted; rate limit intentionally
kept env-only). ~~Follow-ups #2–#4 stand.~~ **Corrected 2026-08-18** (`docs/audits/adr-corpus-review-2026-08-18.md`) — **follow-up #2 (per-account login backoff) also shipped**, the same day, under `#38`: `apps/api/mosaera_api/loginguard.py` + Alembic `0016 login_backoff`. Follow-ups #3 (posture clamping) and #4 (surface remaining quota in the UI / a header) stand; #4 is tracked nowhere else — only `Retry-After` exists today.
