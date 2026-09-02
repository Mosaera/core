# ADR-0042: The clone path injects a scoped token only for the configured GitLab host

- Status: accepted
- Date: 2026-07-15
- Owners: Alejandro Rengifo
- Related: the `is_gitlab_source` host-equality fix (TM-0002 / M-1) that closed the SAME class for the `ls-remote` access check (~~an [ADR-0036] follow-up~~ — **corrected 2026-08-18**, `docs/audits/adr-corpus-review-2026-08-18.md`: ADR-0036 is the test-integrity baseline and is unrelated to this class; the M-1 finding has no ADR of its own); [ADR-0038](ADR-0038-url-ids-are-untrusted-path-input.md) (contain at the sink — the same principle applied to the project-file routes here); [ADR-0041](ADR-0041-prevent-repeats-guardrails.md) (prevent-repeats)
- Related threat model: docs/threat-models/TM-0002

## Context

A project carries its own scoped `write_repository` GitLab PAT (set by an admin). To clone a
private source, `run_intake` reads that token and passes it to `clone_project`, which builds an
authenticated URL in `_auth_url` (`https://oauth2:<token>@<host>/…`).

`_auth_url` injected the token into **any** `http(s)` source host — it had no notion of *which*
host was the trusted GitLab. So a project whose `source_repo` pointed at an attacker-controlled
host (a look-alike like `gitlab.example.com.evil.io`, or simply an unrelated host) would receive
the scoped PAT at clone time. This is exactly the exfiltration class that was fixed for the
`check_repo_access` / `ls-remote` path (host EQUALITY via `is_gitlab_source`, TM-0002 M-1) — but
the **clone** path was never given the same gate. Same token, same class, different sink.

## Decision

Gate the token injection at the sink. `_auth_url(source, token, gitlab_url)` injects the token
**only** when `is_gitlab_source(source, gitlab_url)` holds — bare-host equality, the same
predicate the ls-remote path uses (which already handles https, scp/ssh, ports, case, and the
userinfo/`@` trick). `gitlab_url` is threaded through `clone_project` → `_clone_into` from
`run_intake` (`settings.gitlab_url`). A non-GitLab, tokenless, or non-http source — or a missing
`gitlab_url` — returns the URL **unchanged** (fail safe): the token never leaves the box.

Containing it *in `_auth_url`* rather than only at the caller is deliberate (the ADR-0038
principle): it is the single sink through which every clone token flows, so even a future caller
that forgets to pre-check cannot leak the PAT.

This ADR ships alongside two same-spirit parity fixes recorded in TM-0002:
- the project file/patch routes (`project_file`, `_project_ws`) now build their containment root
  from a **validated** `project_id` (`contained_path` / `safe_segment`), closing the ADR-0038
  poisoned-root anti-pattern that still lived there; and
- `create_app`'s `guard_bind` now reads the real bind host from the server's own
  `--host`/`--bind` CLI flag, closing the residual where a raw `uvicorn --factory --host 0.0.0.0`
  (no `MOSAERA_API_HOST`) bypassed the guard.

## Consequences

- A project's scoped PAT can no longer be exfiltrated to a look-alike/foreign host via the clone
  step; the clone and ls-remote paths now enforce the same host-equality invariant.
- `clone_project` / `_clone_into` gain an optional `gitlab_url` argument; callers that pass a
  token now pass `gitlab_url` too. Tokenless clones (the per-run `clone_repo`) are unaffected.
- Behaviour is unchanged for legitimate GitLab sources (including scp/ssh, which stay untouched
  because they are not `http(s)` — auth rides the SSH key, not the URL).
- Fail-safe default: if `gitlab_url` is not supplied, no token is injected — an over-cautious
  clone (which then fails auth loudly) is strictly better than a leaked credential.
