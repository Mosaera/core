# ADR-0005: Configuration in the UI (no .env required)

- Status: accepted
- Date: 2026-07-11
- Owners: Alejandro Rengifo
- Related issue: sectioned settings + config-in-UI (MR !140), enum dropdowns (MR !141); builds on BYOM/cost-modes (ADR-0002)
- Related threat model: docs/threat-models/TM-0002

## Context

Mosaera is env-first: `Settings.from_env()` (`packages/core/mosaera_core/config.py`) reads
`MOSAERA_*` variables and `.env.example` documents every knob. That is correct for deploy and
CI, but it made day-to-day operation of a *running* instance painful. Tuning a run budget, the
iteration cap, the no-progress breaker, or an optional quality/review loop meant editing `.env`
and **restarting the API** — a poor fit for a self-hosted dashboard whose whole point is that a
human operates it from the browser. GitLab connection, pricing, providers, and cost-modes were
already UI-managed (persisted to `settings.json`); the ~30 remaining operational knobs were not.

Two forces shaped the design. First, **env must stay authoritative** — an operator who pins a
value in the deployment (compose file, secret manager) must not have it silently overridden by
something typed into the UI. Second, a growing knob set had turned `from_env` into ~30
near-identical hand-written parse-and-layer lines, each a place for a type/default/precedence
bug.

## Decision

**1. One spec table is the single source of truth.** `GENERAL_KNOBS` is a tuple of
`Knob(field, env, kind, default, choices)` describing every UI-manageable operational knob
(~~~30~~ **~30 at decision time; 76 today** — corrected 2026-08-18, `docs/audits/adr-corpus-review-2026-08-18.md`;
the spec table is designed to grow): run budgets and hard caps, the iteration cap/ceiling, the no-progress breaker, reasoning
streaming, the quality/review/hygiene loops, agent step limits, sandbox toggles, and Ollama
tuning. The `field` name doubles as the `settings.json` key and the `Settings` dataclass field;
`kind` (`int｜float｜opt_int｜opt_float｜bool｜str｜opt_str`) drives both parsing (`_coerce_knob`) and
the UI widget.

**2. Layering precedence is env > stored > default — env always wins.** `_layer_knob` reads the
env var first; only if it is unset (or blank/malformed) does a UI-saved value from `settings.json`
apply; failing that, the coded default. `layer_knobs` returns the effective value for every knob
as one kwargs dict, and `from_env` splices it in with `**layer_knobs(e, stored)` — replacing ~30
hand-written layer lines with one spec-driven call. A UI save therefore applies **only when the
env var is unset**, preserving env as the deploy override.

**3. The store has a write allow-list, kept in sync by a drift test.**
`settings_store._ALLOWED_KEYS` is the set of keys `read_settings`/`write_settings` will persist
(`0600`, owner-only, under gitignored `.mosaera/`); anything else is dropped. It mirrors the knob
`field` names, and a drift test asserts `{k.field for k in GENERAL_KNOBS} <= _ALLOWED_KEYS` so a
new knob cannot ship un-persistable.

**4. No caching → no restart.** `Settings.from_env()` is re-read fresh at the start of every run,
so a UI save takes effect on the **next run with no API restart**.

**5. A deliberate carve-out stays env-only.** Bootstrap / infra / security knobs are excluded
from `GENERAL_KNOBS` and the allow-list on purpose: API host/port, service token, admin token,
CORS, cookie-secure, `db_url`, `home`, sandbox backend, and sandbox/scan image. Several are not
even fields on the `Settings` dataclass. These configure the process before the UI trust surface
exists (or define that surface), so they must not be mutable through it.

**6. The read endpoint exposes provenance; the write endpoint is admin-gated.**
`GET /api/settings/general` returns `general_settings_view()` — each knob's effective `value`
plus its `source` (`env｜stored｜default`) — so the UI renders env-pinned knobs read-only (a "set
via env" badge). `PUT /api/settings/general` is gated by `require_admin`, validates/coerces the
patch through `coerce_general_patch` (unknown fields dropped, numbers must be `>= 0`, `null`
unsets a key), and persists via `write_settings`.

**7. Dropdown-as-validation for enumerable values.** A knob whose values are a known set declares
`Knob.choices` (e.g. `sandbox_install_network` → `("bridge", "none")`; `"host"` was removed in
ADR-0035 — it shared the host network namespace with untrusted install code). The server rejects
out-of-set values in `coerce_general_patch` **and** `general_settings_view` returns the choices so
`KnobForm` renders a `<Select>` (`FieldSpec.widget = "select"`) instead of free text. A typo
cannot produce invalid config. Free text (`Input`) remains only for URLs/keys/freeform values.

## Options considered

- **Spec table vs ~30 hand-written layer lines.** Rejected the hand-written form: it duplicated
  the same parse/default/precedence logic per knob, drifted from `.env.example`, and made every
  new knob a multi-touchpoint change. The `Knob` table centralizes type, default, env name, and
  choices in one line.
- **env-wins vs stored-wins precedence.** Rejected stored-wins: it would let a UI edit silently
  defeat a value an operator pinned in the deployment, breaking the deploy-override contract and
  surprising anyone reading the environment as the source of truth. Env stays authoritative;
  stored is the fallback.
- **A DB settings table vs the existing `settings.json` KV.** Rejected a new table: the KV store
  already existed (GitLab/pricing/providers/cost-modes), works with no database configured (the
  optional-DB posture), and is a plain `0600` file. A table would add a migration and a hard DB
  dependency for config that must work DB-less.
- **Free text vs dropdown for enumerable values.** Rejected free text for known option-sets — it
  admits typos that become invalid runtime config. `Knob.choices` makes the UI a picker and the
  server a validator from the same declaration.

## Security implications

`PUT /api/settings/general` is a new privileged config-mutation surface: it lets an admin change
run budgets, breakers, and sandbox behavior. It is `require_admin`-gated (the `X-Mosaera-Admin`
token), consistent with the other config/secret writes, and its threat surface is analyzed in
TM-0002 — cross-reference it for the two-tier auth model. The carve-out (decision 5) keeps the
security-critical bootstrap knobs — the very ones that define the auth/bind boundary — off this
surface entirely, so a compromised or misused admin session cannot re-home the process, drop the
bind guard, or change the DB. Secrets are unaffected: they are not operational knobs, remain
write-only, and are only ever returned masked (`mask_secret`).

## Operational implications

- **No-restart application.** A saved knob applies on the next run because `from_env` is re-read
  per run and never cached — operators tune a live instance from the dashboard.
- **Env override still available.** Deployments continue to pin any knob via its `MOSAERA_*`
  variable; the UI shows such knobs as read-only with their source, so the effective config is
  always legible without shell access.
- **Malformed input degrades to default.** `_coerce_knob` returns `None` for blank/invalid
  values, so a bad env or stored value falls through the layers rather than crashing a run submit.
- The subprocess-sandbox install safety override still wins over the knob: `from_env` forces
  `sandbox_install` off on the subprocess backend unless explicitly allowed, whatever the UI saved.

## Consequences

- Good: a self-hosted instance is fully operable from the browser with no `.env` and no restart;
  one spec drives parsing, layering, the API view, and the widget; enum knobs are typo-proof; the
  drift test prevents a knob shipping un-persistable.
- Cost: a new admin-gated mutation surface to defend (mitigated by admin-gating + the carve-out);
  two lists to keep aligned (`GENERAL_KNOBS` and `_ALLOWED_KEYS`), which the drift test enforces.
- Follow-up: as knobs are added, extend `GENERAL_KNOBS` (and, for enumerable ones, `choices`) —
  the allow-list and UI follow from the spec.
