# ADR-0039: Secrets are encryptable at rest — opt-in envelope encryption keyed by MOSAERA_SECRET_KEY

- Status: accepted
- Date: 2026-07-15
- Owners: Alejandro Rengifo
- Related: [ADR-0004](ADR-0004-auth-and-session-model.md) (the admin gate that protects the write path; this protects the value at rest), [ADR-0038](ADR-0038-url-ids-are-untrusted-path-input.md) (the traversal that made `settings.json` remotely readable — fixed there; this reduces the blast radius if a copy leaks another way), [ADR-0035](ADR-0035-infrastructure-failure-is-loud.md) (fail loud — a missing/wrong key raises, never a silently-wrong token)
- Related threat model: docs/threat-models/TM-0002

## Context

Three live secrets sit at rest in plaintext: a project's scoped GitLab token (`projects.gitlab_token`,
a `String(512)` DB column), the **global GitLab PAT** (`gitlab_token` in `<MOSAERA_HOME>/settings.json`),
and each BYOM provider's API key (`providers.<id>.api_key`, same file). All three are write-only toward
clients — the API returns only a masked hint (`_project_summary`, `mask_secret`) — but the stored value
itself is unprotected. A DB dump, a
backup, a stray file copy, or a filesystem-read bug (e.g. the ADR-0038 traversal, since fixed)
exposes live push and model-provider credentials. `0600` on `settings.json` is also a no-op on
Windows ACLs.

For a self-hosted single-tenant tool the box is largely trusted, so this is an accepted residual —
but "accepted" should be a **choice**, and an operator who wants defense-in-depth for backups/dumps
should be able to turn it on without a re-architecture.

## Decision

Add opt-in envelope encryption at rest, keyed by a single `MOSAERA_SECRET_KEY` (a Fernet key —
authenticated AES via the `cryptography` library). A leaf `mosaera_memory.secrets` module (leaf so
the store *and* core/api can import it without violating the one-way layer graph) exposes
`encrypt_secret` / `decrypt_secret`:

- **Opt-in, backward-compatible.** With no key set, both functions are the identity: nothing is
  encrypted and behaviour is exactly as before (a one-time stderr warning records the choice). An
  existing install keeps working unchanged.
- **Tagged ciphertext + lazy migration.** Ciphertext is tagged `enc:v1:<token>`. An *untagged*
  stored value is treated as legacy plaintext and returned unchanged on read, then re-encrypted on
  its next write — so enabling the key migrates secrets lazily, with no batch job.
- **Encapsulated wiring.** The per-project GitLab token is encrypted inside the store (`create_project` /
  `update_project` on write, `get_project_token` on read) so all callers are oblivious. The global PAT
  is encrypted at the `gitlab/config` write (`routes/settings.py`) and decrypted in `Settings.from_env`
  (`config/_from_env.py`; this ADR originally cited `config/_settings.py`, which only declares
  `from_env` — **path corrected 2026-08-18**, `docs/audits/adr-corpus-review-2026-08-18.md`) so every consumer sees plaintext. Provider keys are encrypted at the settings
  write and decrypted wherever the key is actually used — sending it to a provider (`models.py`) *and*
  the "Test" endpoint that validates a saved key (`routes/settings.py`). Presence checks (`bool`) run on
  the ciphertext untouched; **masking decrypts first**, so the `…last4` hint is the real key's tail, not
  a meaningless, ever-changing ciphertext tail.
- **Fail loud.** A value that is encrypted but whose key is missing, wrong, or malformed raises
  `SecretKeyError` (ADR-0035), never a silently-wrong credential.

  > **Qualified 2026-08-18** (`docs/audits/adr-corpus-review-2026-08-18.md`) — this holds on the **write and use** paths. The per-request
  > `Settings.from_env` READ path is a deliberate exception (M-2): it runs on *every* request
  > including `/healthz`, so a locked PAT (missing/wrong `MOSAERA_SECRET_KEY`) degrades to
  > "no token" via the non-raising `try_decrypt` rather than 500-ing the whole API
  > (`packages/core/mosaera_core/config/_from_env.py`). That is **absence** of a credential, not a
  > wrong one — the invariant this bullet protects is intact — and ADR-0041's property test pins
  > `try_decrypt` as total.

`MOSAERA_SECRET_KEY` is a bootstrap/secret knob, so it stays env-only (never UI-managed).

## Options considered

- **Do nothing / document the acceptance.** Cheapest, and defensible for the trusted single-tenant
  box. Rejected as the *default* because the cost of an opt-in path is small and backups/dumps are a
  real exposure; instead this is exactly the opt-in that documents-and-accepts by default (no key)
  while letting an operator harden.
- **Always-on encryption (mandatory key).** Rejected: it breaks every existing keyless install and
  forces key management on users who don't need it. Opt-in preserves the local-first zero-config
  posture.
- **OS keyring / external KMS.** Heavier and platform-specific; out of scope for a self-hosted tool.
  The `MOSAERA_SECRET_KEY` seam does not preclude a future KMS-backed key source.
- **Encrypt only the DB token, not provider keys (or vice-versa).** Rejected — both are equally
  sensitive; one shared primitive covers both.

## Consequences

Operators who set `MOSAERA_SECRET_KEY` get AES-authenticated secrets at rest with transparent,
lazy migration; everyone else is unaffected. Losing the key means losing access to the secrets it
encrypted (rotate the credential, clear the value) — the same property any at-rest encryption has,
surfaced loudly rather than as a mystery auth failure. `cryptography` becomes a `mosaera-memory`
runtime dependency. See the at-rest confidentiality note in TM-0002.
