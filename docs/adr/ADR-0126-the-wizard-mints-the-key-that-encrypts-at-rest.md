# ADR-0126: The wizard mints the key, and an exposed bind refuses to run without one

- Status: accepted
- Implementation: shipped
- Date accepted: 2026-08-31
- Owners: engineering
- Related issue / MR: #123, #124 (the "fails closed when exposed" arc)
- Supersedes / Superseded by: **amends ADR-0039** (opt-in envelope encryption), which rejected a
  mandatory key on grounds this does not trigger
- Related threat model: TM-0002
- Review trigger: a supported deployment appears where the instance cannot hold its own key (a
  KMS-backed or externally-managed key source); or `.env` stops being the wizard's config sink.

**Decision summary:** Encryption at rest stops being an opt-in nobody opts into. The setup wizard
**mints a Fernet `MOSAERA_SECRET_KEY`** for every install that lacks one, and `guard_bind`
**refuses a non-loopback bind** that has no key (#123) or whose TLS posture is **undeclared**
(#124). The operator declares that posture by choosing it on the access screen, so the wizard never
answers it for them.

## Context

ADR-0039 added envelope encryption keyed by `MOSAERA_SECRET_KEY` and made it **opt-in**, rejecting
an always-on key with two reasons:

> "it breaks every existing keyless install and forces key management on users who don't need it.
> Opt-in preserves the local-first zero-config posture."

Both reasons are about **an operator who must produce and hold a key**. Neither survives a wizard
that mints one: nothing existing breaks, because an install that already has a key or has none is
left exactly as it is and the lazy migration is untouched; and nobody manages anything, because the
key is generated, written to `.env`, and never shown.

What did change is the premise underneath. ADR-0039 reasons explicitly about "the trusted
single-tenant box", which was an accurate description of the population in 2026-07 and stopped being
one the day a public one-liner shipped. Measured state before this ADR:

| | before |
|---|---|
| `MOSAERA_SECRET_KEY` in `guard_bind` | absent — no clause at any bind |
| generated anywhere in setup or `install.sh` | never — zero occurrences |
| `MOSAERA_COOKIE_SECURE` default | `"0"`, silently |
| what a default install stored | GitLab PAT, OAuth client secret, GitHub App private key, every BYOM key — **plaintext under `0600`** |

The Models screen meanwhile tells the operator their keys are "stored server-side (0600) and never
shown back", which reads as a security property. `0600` is a permission, not encryption.

## Decision

### 1. The wizard mints the key (amends ADR-0039)

`ensure_secret_key` writes a Fernet key to `.env` when none is present, for **every** install —
loopback included. Never overwrites: a key already there encrypts secrets already stored, and
replacing it would strand them.

ADR-0039's opt-in remains intact underneath. A keyless install still works, still stores plaintext,
still migrates lazily on the next write. What changes is only what a NEW install starts as.

### 2. An exposed bind refuses without a key (#123)

`guard_bind` gains a clause: no `MOSAERA_SECRET_KEY`, no non-loopback bind. Loopback is untouched,
so the zero-config posture ADR-0039 protected still holds for the box it reasoned about.

### 3. An exposed bind must DECLARE its TLS posture (#124)

**Not** "force `Secure` when exposed". A browser will not send a `Secure` cookie over `http://`, so
forcing it silently breaks every plain-http LAN deploy and the operator's fix under pressure is to
disable the protection — trading a real control for an apparent one. `guard_bind` refuses while
`MOSAERA_COOKIE_SECURE` is **undeclared**; an explicit `0` is a valid, informed answer.

### 4. The operator declares it, not the wizard

The access screen offers three options rather than two — *this machine only*, *this network behind
HTTPS*, *this network over plain HTTP*. **A wizard that wrote a default on the operator's behalf
would satisfy the guard while waiving the control it enforces**, which is the shape this repo calls
a silently-waived control. Making the declaration the choice means it cannot be skipped, and the
enumerable value is a list rather than free text (ADR-0005).

### 5. Read the environment in the guard, not from a parameter

Both clauses read `os.environ` inside `guard_bind`. A clause a caller must remember to pass is a
clause a caller can forget, and this guard has two entrypoints precisely because one of them was
once skippable (ADR-0042).

## Consequences

- **A fresh install encrypts at rest by default.** The one-liner population gets the hardened
  posture without being asked for a decision they have no context to make.
- **An existing keyless install is unchanged** until its wizard is re-run, and then it gains a key
  and migrates lazily. No batch migration, no break — the property ADR-0039 rejected mandatory keys
  to protect.
- **UPGRADE STEP — an already-deployed exposed instance stops until it is given both.** This ADR
  originally said "nothing existing breaks". That was true of the MINTING and false of the GUARD,
  and the distinction cost a live 502 on the author's own staging deployment (2026-09-01): the API
  exited at startup, the reverse proxy found nothing upstream, and the reason was correct, loud,
  and written only to a log the operator had no reason to open. Before upgrading a non-loopback
  deployment, set `MOSAERA_SECRET_KEY` (a real Fernet key — the guard validates it) and
  `MOSAERA_COOKIE_SECURE`. A wizard-driven install repairs itself, because the access step always
  renders and rewrites both; a hand-rolled or proxied deployment has no wizard in its path, so
  both refusals now name themselves as a new requirement rather than reading as a standing one.
- **An exposed deployment can now fail to start for two new reasons**, deliberately and loudly.
  The wizard writes both values when the operator chooses a network bind, so the supported path
  never produces a configuration the server refuses to boot on — the failure `public_bind_blocked_by`
  exists to prevent, one clause later.
- **The key is now the wizard's to remove**, so it joins `OUR_ENV_KEYS`. That creates a new hazard
  and it is named rather than left: removing the key while KEEPING the database volume strands
  every credential in it. The uninstall confirm screen says so before it runs.
- **Losing the key still means losing what it encrypted** — unchanged from ADR-0039, but now it can
  happen to an operator who never chose encryption. That is the honest cost of this ADR, and the
  mitigation is the warning above rather than a claim the risk is gone.
- **`MOSAERA_SECRET_KEY` stays env-only** and is never UI-managed (ADR-0039).
- **red-team: done** — 3 rounds, scoped to this change. **4 FIX-NOW, all fixed and pinned; 2
  FALSE-POSITIVE.** The pass is the reason several claims in this ADR are true rather than
  intended.

  | # | finding | disposition |
  |---|---|---|
  | A1 | `guard_bind` checked the key's PRESENCE, not its usability — `MOSAERA_SECRET_KEY=xxxx…` satisfied #123 while `encrypt_secret` raised `SecretKeyError` at the first credential write, days later and nowhere near the cause | **FIX-NOW** — `_usable_secret_key` constructs a `Fernet` at the door |
  | A2 | the minted key lands in `.env`, which could be world-readable | **FALSE-POSITIVE** — written `0600` from creation via `os.open`, never widened, and a `0400` chosen by the operator is respected |
  | A3 | an exposed deploy might not receive the new vars and would refuse to start | **FALSE-POSITIVE** — the API runs on the host (compose carries only Postgres) and `dev-up.sh` does `set -a; . ./.env` |
  | A5 | **highest severity.** `encrypt_secret` with no key is the IDENTITY function — it stores plaintext and only warns. A server started BEFORE the mint keeps writing plaintext while the wizard paints success, so this ADR's guarantee read as established on the upgrade path of every pre-existing install | **FIX-NOW** — the already-serving path names it and asks for a restart |
  | A6 | `access_env` mints only when a key is ABSENT (correctly — replacing strands what it encrypted), so a present-but-unusable key would be offered a network bind and then meet a server that refuses to start. **Created by A1's fix** | **FIX-NOW** — `public_bind_blocked_by` reports it, which is the seam that exists for exactly this |
  | A7 | `on` and `secure` passed the #124 clause and silently meant OFF — a declaration control accepting an answer it cannot read, which is worse than no answer because the operator believes they gave one | **FIX-NOW** — the value must be in `COOKIE_SECURE_TRUE`/`FALSE` or the bind is refused |

  **STOP rule invoked.** A1 and A6 are one defect class — *presence is not usability* — and it
  surfaced in two rounds. Per the protocol there is no third pass on it; the class is logged here
  instead. Anything reading `MOSAERA_SECRET_KEY` as a boolean is suspect, and the successor should
  sweep for it rather than wait for the next instance.

## Alternatives considered

- **Leave ADR-0039 as-is and document harder.** The status quo, and the reason the gap survived a
  year: the documentation was already correct and nobody read it at install time.
- **Mandatory key for every bind (the ADR-0039 rejection).** Still rejected, for its original
  reason: it breaks keyless installs. Minting is not mandating.
- **Force `MOSAERA_COOKIE_SECURE=1` when exposed.** Rejected — see §3. It breaks plain-http LAN and
  teaches the operator to disable the protection.
- **Have the wizard pick the TLS answer by probing for a proxy.** Rejected: it cannot be known from
  inside the box, and a wrong guess locks the operator out of their own instance.
- **OS keyring / KMS.** Out of scope, unchanged from ADR-0039; the `MOSAERA_SECRET_KEY` seam does
  not preclude it.
