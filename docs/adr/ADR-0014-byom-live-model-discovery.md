# ADR-0014: BYOM — validate the API key and discover the models it grants (not a static list)

- Status: accepted
- Date: 2026-07-12
- Owners: Alejandro Rengifo
- Related: [ADR-0005](ADR-0005-config-in-ui-settings.md) (config-in-UI), [ADR-0002](ADR-0002-deterministic-first-and-model-agnostic.md) (the `get_chat_model` seam), [TM-0002](../threat-models/TM-0002-mosaera-api-web-server.md) (provider-key handling)

## Context

BYOM (#21) let a user bind any role to a hosted provider, but the model picker offered a
**hardcoded curated list** (`models.py` `_PROVIDER_SUGGESTIONS` — a handful of OpenAI/Anthropic
names) for hosted providers. Ollama was already discovered live (`/api/tags`); hosted providers
have the same discovery endpoints (OpenAI/OpenAI-compatible `GET /v1/models`, Anthropic
`GET /v1/models`) but we never called them. So a user pasted a key, saw a stale predefined list,
and couldn't pick the model their key actually grants — and there was no way to tell whether the
key even worked.

## Decision

**Validate the key by listing the models it grants, and feed that live list into the picker.**

- **`fetch_provider_models(provider, api_key, base_url=None)`** (`models.py`) calls the provider's
  own list-models endpoint (OpenAI/OpenAI-compatible `GET /v1/models` with `Authorization: Bearer`;
  Anthropic `GET /v1/models` with `x-api-key`), filters obvious non-chat ids, and raises a typed
  **`ProviderAuthError`** on 401/403 — so key validation is meaningful. Results are cached
  in-process (TTL, keyed by provider + key fingerprint + base_url) so validation and the settings
  page don't hammer the provider API.
- **`POST /api/providers/test`** (admin-gated): validates the just-typed **or** stored/env key and
  returns `{ok, count, models, error?}`. A bad/unreachable key returns `{ok:false, error}` (HTTP
  200) so the UI shows it inline — the endpoint never 500s on a provider hiccup.
- **The Settings picker** gets a per-provider **"Test & load models"** button (✓ N models / ✗
  invalid key) **plus** a background auto-fetch on load when a key is already saved. The role model
  dropdown then offers the live models; the curated list is demoted to a **fallback only** (no key,
  fetch failed, or a provider without a list endpoint). Free-text entry still works.
- **Deterministic-first:** the settings view (`list_model_sources`) never blocks on a provider
  call — it serves the **cached** live list if present, else the fallback. All live fetching is the
  explicit Test click or the cached background auto-fetch, so perceived latency stays low.

## Options considered

- **Auto-fetch synchronously inside the settings view** (like Ollama). Rejected — it would make
  every settings-page load hit each configured provider's API (slow, rate-limit-prone, and blocks
  the interactive path). The cache + explicit/background fetch keeps the view fast.
- **Keep the static list, just expand it.** Rejected — it never reflects a specific key's access
  and can't validate the key; the whole point is the models *this* key grants.

## Security implications

No new trust surface (TM-0002 unchanged). The key is used against the provider's own API (its
intended destination) and reaches our Test endpoint under the **same admin gate + write-only,
masked discipline** as saving a provider key — never returned in a response, never logged. The
Test endpoint accepts a just-typed key so it can be validated before it is persisted.

## Consequences

A user pastes a key, clicks Test (or just lands on the page with a saved key), and the dropdown
fills with the exact models that key can use — with a clear ✓/✗ on the key itself. The curated
list remains a graceful offline fallback. Deferred: persisting the fetched list to `settings.json`
(the in-process cache is enough; a restart re-tests), and provider integrations beyond
openai/anthropic/OpenAI-compatible.
