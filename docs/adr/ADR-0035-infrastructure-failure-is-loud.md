# ADR-0035: Infrastructure failure is loud — fail closed on an unreachable database, and drop `--network host`

- Status: accepted
- Date: 2026-07-14
- Owners: Alejandro Rengifo
- Related: [ADR-0004](ADR-0004-auth-and-session-model.md) (auth model), [ADR-0005](ADR-0005-config-in-ui-settings.md) (`Knob.choices`), [ADR-0006](ADR-0006-durable-transcript-and-honest-outcomes.md) (honest outcomes)
- Related threat models: docs/threat-models/TM-0001, docs/threat-models/TM-0002

## Context

Two unrelated defects, both instances of the same failure of nerve: **the system knew
something was wrong and said nothing.**

### 1. `--network host` was an ordinary dropdown option

`sandbox_install_network` declared `choices=("bridge", "host", "none")`, and the value flows
verbatim to `docker run --network <v>` for the install phase. `host` shares the **host's
network namespace** with the target repo's install code — `setup.py`, an npm `postinstall`,
a dependency's build script. That code then reaches everything the trust model assumes is
private: the Mosaera API (loopback-open by default, per ADR-0004), Ollama, and the dev
Postgres, whose credentials are `mosaera/mosaera` and which the project's own compose file
publishes on a host port.

This escalates the install phase from "runs the repo's build code in a container" (the risk
TM-0001 accepts, and which is no worse than the user running `pip install` themselves) to
"install code can talk to the local API and the database". It was presented in the Settings
UI as a plain third option with no warning, and TM-0001's install-egress row documented only
`bridge` and `none` — `host` was never modelled.

### 2. A configured-but-unreachable database degraded in total silence

`MemoryStore.try_open` was `except Exception: return None` — the cause was **destroyed**, so
nothing downstream could report it. `_default_memory` then could not distinguish "no DB
configured" (a legitimate, chosen mode) from "a DB IS configured and we cannot reach it" (a
failure), because both are `None`. The result, on a DB outage or a failed migration:

- the API booted normally and ran with **no run history**;
- `_build_checkpointer`'s `if history is None or not url` short-circuited **ahead of** the
  `try`, so its "parked runs will not survive a restart" warning was unreachable in exactly
  the case that needed it — parked runs silently became unrehydratable;
- project endpoints 400'd with *"projects require durable memory — set `MOSAERA_DB_URL`"* —
  which **is** set;
- `/healthz` returned the literal `{"status": "ok"}`;
- and, worst: **auth enforcement failed open.** `users_exist` returns `False` for an
  unreachable store, and the middleware computes `auth_required = bool(api_token) or
  users_exist(history)`. An instance whose only auth was user accounts became **fully
  unauthenticated** the moment its database blinked. (`guard_bind` still forces a token on
  any non-loopback bind, so the practical exposure is narrow — but an auth decision that
  fails *open*, silently, is not something to leave standing on a compensating control.)

The CLI already gets this right: it calls `from_url` + `init()` and **crashes loudly**. Two
doctrines for one failure, and the quiet one was in the long-running server.

## Decision

**1. `host` is removed from `sandbox_install_network`.** `choices` is now
`("bridge", "none")`.

Crucially, **the choices change alone is not the fix.** `Knob.choices` guards only the
settings-UI *write* path; the *read* path never consults it. A value stored in
`settings.json` before this change, a `MOSAERA_SANDBOX_INSTALL_NETWORK=host` env var, or a
direct `DockerSandbox(install_network="host")` would all still reach `docker run --network
host`. So `DockerSandbox.__init__` **clamps** the value to `ALLOWED_INSTALL_NETWORKS`,
falling back to `bridge` with a warning. That is the boundary that actually holds. Operators
who want no install egress at all still have `none`.

**2. A configured-but-unreachable database is fatal at boot.** `MemoryStore.open_or_reason`
returns `(store, why)` so the cause survives; `AppContext` carries it as `memory_error`; and
`guard_memory` — sitting next to `guard_bind`, using the same `SystemExit` precedent, and
called from `create_app` so a `--factory` entrypoint cannot skip it — refuses to start,
naming the cause and the stakes.

`MOSAERA_ALLOW_DEGRADED_MEMORY=1` is the escape hatch for an operator who genuinely wants a
history-less API. It degrades **loudly**, as a choice. That is the entire difference.

This closes the auth fail-open **by construction**: a broken DB never reaches the middleware.
Two smaller repairs go with it, for the states that remain reachable:

- `users_exist` now fails **closed** (`True`) when a *live* store raises — a database that
  dies mid-flight must not switch authentication off. The accounts guarding the API do not
  cease to exist because we momentarily cannot read them. (A `None` store still reads
  `False`: that state is now only reachable via the explicit opt-in above.)
- `/auth/status` guards its previously-unguarded `count_users()`, which would otherwise 500
  the one endpoint the SPA needs to bootstrap — and, worse, advertise `needs_setup: true` to
  an attacker while dropping `auth_required`.
- `/healthz` reports the durable-memory state instead of a bare literal.

## Consequences

- **A deployment whose database is down will now refuse to start.** That is the point, and
  it is a behaviour change operators must know about — hence the escape hatch and the
  `.env.example` entry. An orchestrator that health-checks `/healthz` will also now see
  `degraded` instead of `ok`.
- A stored or env-set `host` install network silently becomes `bridge` with a warning rather
  than erroring. Failing *safe* beats failing *shut* here: the run still works, with egress
  scoped to a bridge network, and the operator is told.
- Two tests **inverted**, both toward safety: `test_knob_choices_reject_out_of_set_and_expose`
  asserted that `"host"` was *accepted*, and `test_users_exist_tolerates_missing_store`
  pinned the fail-open branch.

## What this does NOT fix

`guard_bind` reads the bind host from `MOSAERA_API_HOST`, so a `uvicorn --host 0.0.0.0`
deploy that does **not** also set that env var still skips the bind guard entirely (its own
docstring admits this). That weakens the compensating control this ADR leans on for the
narrow window where auth could still fail open. ~~Tracked separately; not closed here.~~ **Closed 2026-08-18** (`docs/audits/adr-corpus-review-2026-08-18.md`) — by ADR-0042: `create_app` now guards the server's own most-exposed declared bind (`_cli_bind_host()` reads every `--host`/`--bind`/`-b` in argv plus `UVICORN_HOST`), falling back to `MOSAERA_API_HOST`. One narrower residual stands: a gunicorn config-FILE `bind` is still invisible to it.

Secrets remain plaintext at rest in `settings.json` (`0600`, a no-op on Windows ACLs), and
the install phase still runs the repo's own build code with egress on `bridge` — the
accepted TM-0001 risk, unchanged.
