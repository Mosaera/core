# ADR-0051: Per-account login backoff, and closing the username-enumeration oracle

- Status: accepted
- Date: 2026-07-17
- Owners: Alejandro Rengifo
- Related issue: #38 (closes ADR-0050 follow-up 2)
- Related: [ADR-0004](ADR-0004-auth-and-session-model.md) (the login path this guards; the service/admin token that bypasses it), [ADR-0005](ADR-0005-config-in-ui-settings.md) (env-only infra knobs), [ADR-0035](ADR-0035-infrastructure-failure-is-loud.md) (a control you cannot read is a failure — `SystemExit` at boot), [ADR-0040](ADR-0040-first-run-setup-token.md) (the setup gate's atomic single-use `RETURNING`, the shape reused here), [ADR-0050](ADR-0050-api-rate-limiting-and-run-quota.md) (**the rate limiter that cannot reach this route; and §5's read-then-write race, repeated here at 130ms scale**)
- Related threat model: [TM-0002](../threat-models/TM-0002-mosaera-api-web-server.md) (**updated** — the false "no enumeration oracle" claim corrected; new lockout + CPU rows)

## Context

ADR-0050's rate limiter keys on the **credential**, so it cannot meter `POST /api/auth/login`: that
route is middleware-exempt and *pre-credential*, so `subject_for` finds nothing and skips it. Both
that ADR and TM-0002 named password brute-force against a known username as the remaining hole.
This closes it with per-**account** backoff — durable, and exact across workers (the quota's
Postgres-side sibling property; the rate limiter's in-process window is only per-worker).

**Two things turned up while building it that reshaped the change.**

**1. The username-enumeration oracle was real, and TM-0002 claimed it was mitigated.**
`routes/auth.py` read:

```python
# Constant-ish work whether or not the user exists (don't leak existence).
ok = creds is not None and verify_password(body.password, str(creds["password_hash"]))
```

The comment asserts the property; the line below it destroys it. Python's `and` short-circuits, so
an unknown username **never ran scrypt at all**. Measured: **~129ms** for a real account versus
**sub-ms** for a fictional one — and end-to-end through the HTTP endpoint, **194ms vs 9ms**. That is
not a statistical side-channel needing thousands of samples; it is a **single-request** oracle
readable with a stopwatch. TM-0002's mitigation cell said *"constant-ish work whether or not the
user exists (no username-enumeration oracle)"* — a false claim, and plausibly the reason nobody
fixed it: the threat model reported the hole closed.

**2. Fixing it is a prerequisite for the feature, not a parallel nicety.** Backoff necessarily
branches on account state. Ship 429-for-real-accounts next to fast-401-for-unknown and the
**status code itself** announces which usernames exist — a cleaner, timing-free oracle than the one
being closed. `#38`'s own acceptance already required this (*"indistinguishable … via status or
timing"*), so it is in scope rather than creep.

## Decision

### 1. Claim the attempt slot BEFORE verifying the password

The obvious design — read the counter, compare to the threshold, run scrypt, increment on failure —
is a **TOCTOU race 130ms wide**. Every concurrent request reads the same under-threshold count,
passes the gate, and gets a guess: the threshold bounds sequential **rounds**, not **guesses**, and
a caller with N connections buys N guesses per window. The control's headline number would be
fiction.

This is precisely the race [ADR-0050 §5](ADR-0050-api-rate-limiting-and-run-quota.md) rejects for
the run quota — *"the obvious implementation … is a read-then-write race"* — and repeating it one
file over, on the authentication path, would be worse. So `attempts` counts **admitted attempts**,
claimed atomically up front, and **cleared on success** (which is what preserves "consecutive
failures" as the effective semantics). A refused attempt claims **nothing**, so a hammering
attacker cannot extend their own lock and the counter keeps meaning "attempts spent".

One conditional UPSERT does check-and-claim in a single atomic step:

```sql
INSERT ... VALUES (:subject, 1, :now, ...)
ON CONFLICT ON CONSTRAINT uq_login_backoff_subject DO UPDATE
   SET attempts = CASE WHEN <idle past reset> THEN 1
                       ELSE LEAST(attempts + 1, :attempts_cap) END,
       last_attempt_at = :now
 WHERE login_backoff.attempts < :threshold
    OR <elapsed> >= LEAST(:max, :base * power(2, LEAST(:exp_cap, attempts - :threshold)))
RETURNING attempts
```

A conflicting row that fails the `WHERE` returns nothing — which *is* the "backed off" signal
(`try_consume_run_quota`'s contract, deliberately mirrored so the two atomics read alike). Verified
by a 40-thread test: exactly `threshold` of 40 racing callers win.

### 2. The policy rides in as bound parameters — nothing derived is stored

The lock predicate must be **in the `WHERE`** for the claim to be atomic, so it cannot be computed
in Python. Config therefore travels as bound params rather than a stored `locked_until` column:
no derived state to go stale, and the schedule stays pure. Python keeps a mirror
(`loginguard.backoff_seconds`) used **only** to render `Retry-After`; a parametrized test pins the
two together at every rung, and `LOGIN_BACKOFF_EXP_CAP` is *imported* from the store rather than
redeclared so the clamp cannot drift.

**Both clamps are load-bearing.** SQL's `LEAST` does **not** short-circuit — it evaluates both arms
— so an unclamped `power(2, attempts - threshold)` overflows `double precision` once an attacker
keeps counting, turning every subsequent `POST /auth/login` into a **500**. `LOGIN_BACKOFF_EXP_CAP`
bounds the exponent; `_ATTEMPTS_CAP` bounds the stored counter.

### 3. Equalize the unknown-username path — unconditionally

`verify_password(password, creds["password_hash"] if creds else _DUMMY_HASH)` — no short-circuit.
The dummy is **not** built with `hash_password`: `verify_password` parses `scheme$n$r$p$salt$hash`,
recomputes scrypt from those params and compares — **it never checks the stored digest is a genuine
scrypt output**. So random bytes verify at identical cost (measured **132.4ms vs 131.8ms, ratio
1.004**) while costing nothing to construct, keeping 130ms of scrypt out of every process start and
every test that imports the module.

Equalization is **never capability-gated**: a store lacking the backoff methods still degrades to
"no backoff", but it must never degrade to "leaks existence".

### 4. The bucket key is `sha256(username.strip())` — `.strip()` only, case-SENSITIVE

The key must be a function of **exactly** the identity the lookup resolves
(`get_user_credentials` strips, nothing more). Both deviations are exploitable:

- **Coarser (`casefold`) is a two-line exploit.** `users.username` is case-sensitively unique, so
  `admin` and `Admin` are two accounts that can coexist. Folding them into one bucket means — since
  a success **deletes** the bucket — a low-privilege member named `Admin` clears the real admin's
  failure counter at will, just by logging into their own account. A complete bypass.
- **Finer (no strip) is a bypass too:** `admin`, `admin `, `admin\t` all resolve to one account but
  would land in distinct buckets → a fresh allowance per whitespace variant, forever.

Enforced structurally: `normalize_username` runs **once** and the same string feeds both the lookup
and the key, so they cannot drift.

**Hashed** because a durable table of *submitted* usernames captures the passwords people
periodically type into the username box — and because sessions and setup tokens already store only
SHA-256 for the same reason.

### 5. Reject, don't delay; and bound concurrent verification

Backed off → **429 + `Retry-After`** (never 0 — that invites the hot retry loop the control exists
to stop). No `sleep`: holding an anyio worker is what "never block the interactive path" forbids,
and is itself the DoS.

`auth_login` is a **sync `def`**, so FastAPI runs it in anyio's ~40-thread pool — **shared with
every other sync endpoint**. At ~130ms and ~16MiB per scrypt, a login flood saturates every core and
~670MB RSS, stalling the whole API rather than just login. A **non-blocking** `Semaphore` bounds
concurrent verifications and returns 503 on contention: a flood fails fast on one endpoint instead
of melting the box. It refuses rather than queues, so it never blocks.

Honest accounting: equalization does **not** raise the DoS ceiling (a known username always bought
130ms/req) — it removes the one-request recon step, which the oracle itself was providing anyway.
Trading a confirmed single-request info-leak for a DoS precondition that was one request deep is
plainly the right trade, and the semaphore bounds what remains.

### 6. Env-only config, loud, and ON by default

`MOSAERA_LOGIN_BACKOFF_THRESHOLD` (5, `0` disables), `_BASE_SECONDS` (30), `_MAX_SECONDS` (900),
`_RESET_SECONDS` (3600), `MOSAERA_LOGIN_VERIFY_SLOTS` (8). Env-only per ADR-0005/`#34`;
range-checked and `SystemExit` on nonsense, resolved **once at app build** so a bad value refuses to
boot rather than 500-ing the login endpoint on first use.

**Defaults ON** — unlike ADR-0050's quota (a fairness *policy* with no safe universal number), this
is an authorization-adjacent security control, so deny-by-default applies.

One cross-field invariant is enforced because its failure is **silent**: `reset_seconds` must exceed
`max_seconds`. Otherwise, by the time any lock expires the reset window has *always* also elapsed,
so the counter resets to 1 on every post-lock attempt and **the escalation never escalates** — an
operator would see a permanent first-tier backoff and no error at all. Per-value range checks cannot
catch this.

## Options considered

- **Count failures (increment after verification).** Rejected — §1; it is the 130ms TOCTOU race.
- **Key on `users.id`.** Rejected — unknown usernames would then never back off, so a 429 would mean
  "this account exists": the status oracle, cleaner than the timing one.
- **Casefold the key.** Rejected — §4; an active bypass, not a robustness nicety.
- **Store `locked_until`.** Rejected — §2; a Python-computed predicate cannot sit in the `WHERE`, so
  it forfeits atomicity, and the stated benefit ("config applies instantly") is illusory when config
  is env-only and needs a restart anyway.
- **Delay the response instead of refusing.** Rejected — §5; holds a worker, self-DoS.
- **Rate-limit `/auth/login` by IP.** Rejected — behind the recommended reverse proxy every client
  shares the proxy's address, so one attacker would lock out the whole team, and `X-Forwarded-For`
  is deliberately untrusted (the same reasoning that made ADR-0050 skip this route).
- **`hash_password(random)` for the dummy.** Rejected — §3; 130ms at every import for a string that
  random bytes provide free.
- **Reuse `ratelimit.py`'s `_int_env`.** Impossible, not merely untidy: `ratelimit.py` imports
  `auth.py`, so importing back is a circular import — and its message picks the unit via
  `'RATE' in name`, so it would tell an operator setting a backoff knob to "expect a whole number of
  runs per day". Forked ~15 lines with a follow-up to extract `envconfig.py`.
- **Re-export `LoginBackoff` from `models.py`.** Declined — that block exists so *pre-existing*
  importers keep working, and `models.py` sits one line under the 500 ceiling; a new re-export would
  push it over and force an unrelated split. `Base.metadata` is unaffected (`models` already imports
  `models_auth`), and leaving the file untouched also keeps this MR off a shared file.

## Security implications

- **This is auth logic → CODEOWNERS.** `guard_bind`, session/token verification and the admin gate
  are untouched; the change adds a gate *in front of* verification and equalizes the branch *inside*
  it.
- **The corrected TM-0002 claim matters more than the code.** A threat model that reports a hole
  closed is worse than one that reports it open: it retires the fix from everyone's queue. The
  mitigation cell now states the defect and the fix.
- **Per-account backoff is an availability trade, and it is new.** Anyone who knows a username can
  hold that account out by failing against it. This is inherent to *any* per-account key (IP is
  untrusted behind the proxy), and it converts TM-0002's lost-admin risk from **host-access-only**
  to **network-reachable**. Three things bound it: the backoff is capped (not a permanent lockout);
  `DELETE /auth/users/{id}/lockout` (admin-gated) clears a member's counter; and — the real escape
  hatch — **`MOSAERA_API_TOKEN`/`MOSAERA_ADMIN_TOKEN` reach `/api/*` without `/auth/login` at all**,
  so an operator is never locked out of their own instance.
- **The unlock endpoint cannot grant anything.** It deletes a counter: it cannot mint a session,
  weaken a password, or bypass verification. The blast radius of a bug in it is "someone gets their
  normal allowance back".
- **Equalization is unconditional** while the backoff is capability-gated — the asymmetry is
  deliberate. "No backoff" is a degraded control; "leaks existence" is a defect.
- **A `_N` bump re-opens the oracle, inverted.** Existing users carry the old (cheaper) params in
  their stored hash while unknown usernames would get the new (dearer) dummy, making unknown
  measurably *slower*. Unfixable in general (you cannot know an unknown user's params), so it is
  commented at `_N`'s definition: a bump needs rehash-on-login first.
- **`prune_sessions` was an unauthenticated N+1 write amplifier** — a full SELECT of expired rows
  then ORM-delete each, on every login. Now one set-based DELETE, and it runs **below** the backoff
  gate so a refused attempt doesn't pay for it.
- **The bucket table is attacker-controlled** in a way `run_quota_usage` is not: every distinct
  submitted username makes a row. ADR-0050's *"no sweeper — a handful of rows/day"* reasoning does
  **not** transfer (quota subjects are ≤5 accounts). Hence a bounded, indexed, probabilistic prune.

## Operational implications

- **Zero UI.** Env-only ⇒ a change needs a restart, same contract as every other infra knob.
- **Exact across workers** (Postgres), unlike the rate limiter's per-worker window — worth knowing
  when sizing.
- **Migration `0016`** (`login_backoff`), additive, single head verified `0015 → 0016`. No existing
  table touched.
- Expect support traffic of the form "I'm locked out": the answer is wait out the cap, use the
  unlock endpoint, or (operator) use the service token.

## Consequences

**Good.**
- Brute-force against a known username is throttled regardless of source IP — the gap ADR-0050 left.
- A **confirmed, single-request** enumeration oracle is closed, and the threat model stops lying
  about it.
- The cap holds under concurrency by construction, not by hope (40-thread test).
- The login CPU/RSS sink is bounded for the first time; `prune_sessions` stops being an anonymous
  N+1 amplifier.

**Bad / accepted costs.**
- **Attacker-induced account lockout is now possible** — the deliberate price of throttling guessing.
- A flood makes legitimate logins 503 rather than slow. That is the intended failure mode, but it is
  a behaviour change.
- The schedule exists in SQL **and** Python; only the parametrized test keeps them honest.
- `_int_env` is forked ~15 lines pending the `envconfig.py` extraction.

**Follow-up work.**
1. Extract `apps/api/mosaera_api/envconfig.py` and re-point `ratelimit.py` + `loginguard.py`
   (needs `ratelimit.py`'s domain free).
2. Surface remaining attempts / lockout state in the UI so a user learns *why* they're refused.
3. `admin`/`Admin` as distinct accounts is a pre-existing confusable-username weakness this does not
   fix, and it now has a second consumer. If username uniqueness ever becomes case-insensitive,
   **the backoff key must change with it** (commented at `normalize_username`).
4. Rehash-on-login, if `_N` is ever bumped (see §Security).

**Honest residual.** This bounds *online* guessing against an account. It does nothing about a
stolen password, an offline attack on a leaked hash, or a distributed campaign against *many*
usernames at a few attempts each (each subject stays under its own threshold). Those want
credential-stuffing detection and password policy — not a counter.
