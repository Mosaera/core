# ADR-0024: The cloud-egress consent gate + the $0-price USD-cap fix

- Status: accepted
- Date: 2026-07-12
- Owners: Alejandro Rengifo
- Related: [ADR-0018](ADR-0018-reasoning-escalation-ladder.md)/[ADR-0022](ADR-0022-live-model-escalation.md) (the ladders whose "cloud tiers deferred to the cloud-enablers step" clause this discharges), [ADR-0016](ADR-0016-deterministic-model-escalation.md) (the escalation machinery), [ADR-0002](ADR-0002-deterministic-first-and-model-agnostic.md) (cost discipline + the price/budget model), [TM-0001](../threat-models/TM-0001-mosaera-lite-repo-agent.md) (model-context egress)

## Context

Cloud is the strongest rung of every autonomy ladder (reason-escalation, model-escalation), but enabling cloud
*autonomously* was unsafe for two reasons the earlier ADRs explicitly deferred here:

1. **No egress consent.** An autonomous run using a cloud tier sends repo content off-box to a third-party API
   with no operator opt-in. The *reason* ladder hard-blocked cloud (`graph.py` dropped any non-local tier), but
   the *model* ladder was **unguarded** — a configured cloud `role_escalation` tier + `model_escalation_enabled`
   (both operator-set) would egress on a live run with no consent check.
2. **The `$0`-price USD-cap blind spot.** `price_usd()` returns `0.0` for any model absent from `model_prices`,
   and every USD cap (per-run soft/hard + monthly project) reads that sum — so an **unpriced cloud model spends
   real money while the USD cap sits at `$0` and never trips.** Token caps are honest (real provider counts) but
   default OFF, so a USD-only budget is no protection at all against an unpriced cloud model.

These are two facets of one requirement, which is why they fix together.

## Decision

**A cloud model may be used by an AUTONOMOUS run only when the operator has consented to off-box egress AND the
model is priced.** One knob, one predicate, three seams. Default **OFF / local-only**.

- **`allow_cloud_egress`** (`MOSAERA_ALLOW_CLOUD_EGRESS`, bool, **default OFF**) — the operator's explicit consent
  that autonomous runs may send repo content off-box.
- **The predicate** — `models.cloud_tier_allowed(settings, provider, model)`: local (`ollama`) is always allowed;
  a cloud provider is allowed **iff** `allow_cloud_egress` AND `model in model_prices`. Co-located with
  `provider_is_local` (which it reuses), so both `graph.py` and `context.py` import it without an import cycle.
- **Seam 1 — reason ladder** (`graph.py` `_reason_tier`): a reason-escalation tier is used only when
  `cloud_tier_allowed` — replacing the old local-only guard. Backward-compatible (local still fires; unconsented/
  unpriced cloud still falls back to the own-model pass); a consented+priced cloud reason tier now fires (the new
  capability).
- **Seam 2 — model escalation** (`context.py` `_try_model_escalation`): after `escalate_role` picks the bumped
  binding, refuse it (audit `escalation.blocked`, return False → the item defers/parks) when the tier is cloud
  and not allowed. This **tightens** the previously-unguarded model-escalation-to-cloud path — the core safety
  fix. `escalate_role` stays pure (the guard is in the caller, so the benchmark can still exercise cloud tiers
  offline).
- **Seam 3 — autonomous run submit** (`context.py` `launch_item`, `mode=="autonomous"`): before starting, every
  active role binding (pm, coder, reviewer, + tester when enabled) must pass `cloud_tier_allowed`; otherwise the
  run is refused with a specific `CloudEgressBlocked` note (`"role 'coder' uses cloud model 'X' — enable cloud
  egress and set its price, or bind a local model"`), surfaced on the project and caught at `advance_project` /
  `/start` (not the generic "failed to start", not defer-spam). This closes the walk-away hole for **primary**
  cloud bindings too — an unpriced cloud coder + a USD cap was silently blind before.

**`get_chat_model` is deliberately NOT the seam** — it's the shared chokepoint for consented *interactive* BYOM
bindings (a human chose them in the UI, with a warning, and watches the run). Gating there would break intentional
cloud use. The gate is scoped to the **autonomous** path (no human at the loop); guided / high-assurance runs are
unaffected.

## Consequences

- **Cloud tiers are now safe to enable.** With `allow_cloud_egress` ON and the cloud models priced, autonomous
  reason/model escalation may use them — the strongest rung of every ladder — and the USD budget cap actually
  bounds the spend. This discharges the ADR-0018/0022 deferrals.
- **Privacy + cost by default.** Off, nothing changes: autonomous runs are local-only, byte-for-byte as before.
  Repo content never leaves the box on an unattended run without an explicit, auditable opt-in.
- **The blind spot is closed at the point it matters.** An unpriced cloud model can no longer silently evade the
  USD cap on an autonomous run — it's refused (with a clear "set its price" note) rather than run uncapped.
- **Honest residual.** The price is operator-supplied, so the USD cap is only as accurate as the configured rate;
  a hard **token** cap (`run_hard_max_tokens`, price-independent) remains the operator's belt-and-suspenders and
  is recommended alongside cloud egress. The gate governs the autonomous path only — an interactive cloud run is
  still the operator's watched, consented choice (unchanged, per TM-0001).

## Threat surface

This is a live-cloud-tier change, so **TM-0001 is updated** (rows #64/#65): the "not wired to live runs yet"
clause becomes false, and the new control is recorded — autonomous cloud egress is gated by `allow_cloud_egress`
(default OFF) **and** a mandatory `model_prices` entry, refused-and-audited otherwise, autonomous-only. Net effect
is a *tightening*: a previously-unguarded model-escalation-to-cloud path now requires consent + price.

## Alternatives considered

- **Gate at `get_chat_model`.** Rejected — breaks consented interactive BYOM bindings (the human's own choice),
  not just autonomous escalation.
- **A default cloud price table.** Rejected — `model_prices` is bare-model-keyed (collision-prone across
  providers) and a shared table silently drifts from real prices; an explicit operator-set price is honest and is
  exactly ADR-0018's "hosted-tier-price check".
- **Consent without the price check.** Rejected — the two are co-requisites: consented cloud egress with an
  unpriced model still evades the USD cap (the whole point of the blind-spot fix).

## Follow-up (separate)

Node runtime in the sandbox (breadth) — the `validation.py` `javascript` branch is a dead-end today, and the
sandbox image has no Node (CODEOWNERS-protected `infra/`). A separate infra MR (owner review) adds Node; the
validation branch lands behind it.

**Discharged 2026-07-14 by [ADR-0032](ADR-0032-adding-a-languagepack.md); noted 2026-08-18.** Node shipped, but not
as a `validation.py` branch: it landed as a per-pack toolchain image plus a LanguagePack —
`infra/docker/sandbox-node.Dockerfile` (`mosaera-sandbox-node:dev`) and
`packages/core/mosaera_core/languages/node.py` (lockfile-aware install → `tsc --noEmit` → the test suite), with the
mandatory benchmark coverage at `packages/core/mosaera_core/bench/cases/MCB-23/`. The paragraph above ("the sandbox
image has no Node") is therefore no longer true. Recorded in `docs/audits/adr-corpus-review-2026-08-18.md`.

## Amendment 2026-07-28 — an on-box endpoint is not cloud

**Problem.** The predicate treated `ollama` as the only local provider (`_LOCAL_PROVIDERS`). A local
OpenAI-compatible inference server (vLLM, llama.cpp, TGI, LM Studio) is reached through the `openai` provider with
a custom `base_url`, so it was classified as **cloud** — autonomous runs refused it unless the operator turned on
`allow_cloud_egress` and invented a `model_prices` entry. That is the wrong trade in both directions: it forces a
**grant of off-box egress consent for traffic that never leaves the box**, hollowing out the knob's meaning for
every genuinely-hosted binding, and it prices a model that costs nothing.

**Decision.** A binding is **on-box** — and therefore exempt from the consent + price gate — when **either**:

- the provider is inherently local (`ollama`, unchanged), **or**
- **both** (a) its `base_url` host is a loopback address, **and** (b) the operator has explicitly declared the
  endpoint on-box (`ProviderConfig.on_box`, admin-gated, default **OFF**).

The predicate is `models.endpoint_is_on_box`; `cloud_tier_allowed` early-returns on it and is otherwise unchanged.
`provider_is_local` keeps its provider-only meaning — the settings-save **API-key** checks depend on it, and a
local vLLM still needs a key (it is normally launched with `--api-key`).

**Why both conditions.** Loopback alone is *not* evidence of local execution. A LiteLLM-style forwarding proxy —
already tracked as a roadmap `[debt]` item ("LiteLLM / vLLM / OpenAI-compatible proxy in front of the gateway") —
binds to loopback and relays to a hosted API. A bare loopback exemption would silently reclassify real cloud
egress as on-box, defeating both the consent gate and the USD cap. Requiring a separate, deliberate declaration
keeps the exemption **deny-by-default**: when that proxy lands, its operator must consciously assert on-box rather
than inherit the exemption. The declaration alone grants nothing either — the API refuses to store it against a
non-loopback `base_url` (422) rather than persist a flag that means nothing.

**Loopback is tested by ADDRESS, never by substring.** The URL is parsed and the host checked with
`ipaddress.is_loopback` (127.0.0.0/8, ::1) plus the literal name `localhost`, so `http://127.0.0.1.evil.com` and
`http://evil.com/?x=127.0.0.1` are correctly rejected. A false positive here is a silent egress-gate bypass, so
it is pinned by test. The web UI mirrors the check to disable the checkbox inline, but that is an affordance only
— the API re-checks and is authoritative.

**Compatibility.** `on_box` defaults `False` and a missing/malformed value parses to `False` (strict `is True`, so
a truthy string like `"false"` cannot enable it by typo). An existing `settings.json` therefore keeps today's
classification byte-for-byte. No migration.

**Residual (accepted, documented).** An operator who declares a loopback *forwarding proxy* on-box does evade both
the consent gate and the USD cap. This is now an explicit, admin-gated, auditable assertion rather than an
accident, and the price-independent token cap (`run_hard_max_tokens`) remains the belt-and-suspenders control per
the Honest residual above. Separately, `localhost` is trusted by name and not re-resolved — resolving at config
time would put a network call and a TOCTOU window on a pure config path; `/etc/hosts` is operator-controlled.

**Threat surface.** TM-0001 rows #64/#65 updated with the exemption and its two conditions.
