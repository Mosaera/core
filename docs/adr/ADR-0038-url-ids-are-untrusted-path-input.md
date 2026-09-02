# ADR-0038: A URL id is untrusted path input — validate at the boundary, contain at the sink

- Status: accepted
- Date: 2026-07-15
- Owners: Alejandro Rengifo
- Related: [ADR-0004](ADR-0004-auth-and-session-model.md) (the service token is NOT admin — so this was a privilege escalation), [ADR-0033](ADR-0033-host-side-tooling-runs-on-untrusted-repos.md) (treat repo/URL input as untrusted, same instinct one layer up)
- Related threat model: docs/threat-models/TM-0002

## Context

A run/project id arrives from the URL — `run_id`, `project_id` — and is joined onto a base
directory to locate that run's files (`workspaces_dir / run_id`, `projects_dir / project_id`).
Every handler trusted the id as a benign single path segment. It is not: a `..` segment
escapes the base dir, and it is reachable. FastAPI compiles `{run_id}` to `[^/]+`, uvicorn
decodes the percent-encoded `%2e%2e` back to `..` before matching, and an intermediary proxy
does **not** normalise `%2e%2e` away. So `..` reaches the handler as a single, valid path param.

Two live exploits, both reachable by any authenticated caller **or the plain service token**
(which is not admin — ADR-0004), so each is also a privilege escalation (a non-admin destroys
or exfiltrates admin-only secrets):

- **HIGH — secret disclosure.** `GET /runs/%2e%2e/files/settings.json` (`routes/runs.py`
  `download_file`). The containment root was computed *from the id before it was checked*:
  `root = (workspaces_dir / run_id).resolve()` → `root = .mosaera/` when `run_id == ".."`, and
  the subsequent `target.is_relative_to(root)` check then passes for `.mosaera/settings.json` —
  streaming the **unmasked GitLab PAT + provider keys**. The check was real but anchored to an
  attacker-chosen root, so it validated nothing.
- **CRITICAL — data destruction.** `DELETE /runs/%2e%2e` (`delete_run`) ran
  `shutil.rmtree(workspaces_dir / run_id, ignore_errors=True)` with **no check at all** →
  `rmtree(.mosaera)`, erasing `settings.json` (secrets), every workspace, and run history. The
  session/DB guards above it only block *active* runs; they never gate the `rmtree`.

The same id→path pattern recurs in `open_mr`, `run_report`, and `delete_project`. `delete_project`
was incidentally shielded by an earlier `project_detail(..)` existence check that 404s on `..`,
and `run_report` anchors on the fixed `reports_dir` with the id embedded in a filename — neither
is a live exploit — but relying on an unrelated DB lookup to keep a URL away from `rmtree` is not
a boundary. A first-pass audit wrongly recorded this whole class as Low, asserting "each handler
re-checks `is_relative_to`"; `delete_run` does not, and `download_file`'s check is against a
poisoned root.

## Decision

**1. One leaf helper module, deny-by-default: `mosaera_api/_pathsafe.py`.** Two layers so a
single missed call site cannot re-open the hole:

- `safe_segment(value, kind=...)` — the **boundary guard**. Rejects anything that is not a single
  benign path segment (empty, leading dot, any `..` run, or a `/`\`\\` separator — all outside the
  allowed charset) with a clean `400 invalid <kind>`, before the id touches the filesystem or DB.
- `contained_path(base, segment, kind=...)` — the **sink guard**. Validates the segment, then
  resolves `base / segment` and proves it stays under `base.resolve()`. The returned path is safe
  to `rmtree`/serve even if a caller forgets the boundary guard (belt-and-suspenders).

The allowed charset (`[A-Za-z0-9][A-Za-z0-9._-]{0,127}`, no `..`) is a strict superset of every
server-minted id — run `YYYYMMDD-HHMMSS-<6hex>`, project `proj-<slug>-<6hex>` — so no legitimate
id is ever rejected; only traversal shapes are.

**2. Route it through every id→path sink.** `download_file` (build the root via `contained_path`,
so its own path check finally anchors on a real workspace dir), `delete_run` and `delete_project`
(the `rmtree` target), `open_mr` (`workspace_root`), and `run_report` (id hygiene before the
filename join). The two live exploits are closed; the three latent ones are hardened to the same
standard rather than left to depend on incidental guards.

**Not changed: `factory.py`'s `(workspaces_dir / run_id).resolve()`** at run creation — that
`run_id` is server-minted by `_new_run_id()`, never attacker-supplied. Documented as safe rather
than wrapped, to keep the guard where untrusted input actually enters.

## Consequences

- The Critical (`.mosaera` wipe) and High (PAT/key disclosure) are closed, with regression tests
  that drive the exact `..` request and assert a `400` **and** that the base tree is untouched.
- The privilege-escalation angle closes with them: a non-admin session or the service token can no
  longer reach admin-only secrets or destroy them through a data route.
- A reusable, unit-tested pattern now exists for any future `id → filesystem path` route; the
  charset lives in one place.
- No behaviour change for legitimate callers — every real id passes the guard.

## What this does NOT fix

- No generic path-normalising middleware is added; the fix is at the id→path sinks, where the
  untrusted value is actually used. Multi-segment traversal via an encoded slash was already
  blocked by the `[^/]+` path-param match; the single-`..` parent-escape was the live vector, and
  it is what the boundary + containment guards close.
- Authentication still gates these routes — this removes the escalation-to-destruction, not the
  requirement to be authenticated. The broader "the service token is coarse" posture is ADR-0004's.
