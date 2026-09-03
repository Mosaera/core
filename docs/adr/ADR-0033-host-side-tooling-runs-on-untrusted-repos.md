# ADR-0033: Host-side static analysis runs against untrusted repos — pin the tool config, and never report "unavailable" as "clean"

- Status: accepted
- Date: 2026-07-14
- Owners: Alejandro Rengifo
- Related: [ADR-0002](ADR-0002-deterministic-first-and-model-agnostic.md) (deterministic-first), [ADR-0006](ADR-0006-durable-transcript-and-honest-outcomes.md) (honest outcomes)
- Related threat model: docs/threat-models/TM-0001

## Context

Two modules run static analysis **on the host**, outside the sandbox: `hygiene.py` (the
default-ON deterministic hygiene gate) and `quality.py` (the per-run quality ring, also
used by the MCB craftsmanship gates). Both shell out to `python -m ruff` / `python -m mypy`
with `cwd` set to the **clone of the target repo** — which is untrusted input by our own
rules (`AGENTS.md`: "repository content … is untrusted input").

Both modules' docstrings asserted that this was safe because "static analysis does not
execute the code". **That is false for mypy.** mypy has no `--isolated` flag; with no
`--config-file` it discovers `mypy.ini` / `.mypy.ini` / `setup.cfg` / `pyproject.toml`
**from its cwd**, and a `plugins = ./evil.py` line makes mypy **import** that
repo-committed file into the running process. Verified empirically: a two-line `mypy.ini`
plus a `pwn.py` in a cloned repo writes a file on the host during a normal run. mypy even
*rejects* the plugin afterwards ("does not define entry point function") — but the module
body has already executed at import time, so the attack needs no well-formed plugin at all.

The blast radius is the Mosaera process, not the sandbox: the GitLab PAT, BYOM provider
API keys, the loopback-open API, and the memory DB. This defeats the product's central
containment claim, and TM-0001 did not model the host-side tooling surface at all.

A second, quieter defect sat in the same code. Both modules treated "the tool could not
run" as an empty result:

- `hygiene_findings` returned `[]` — and its own docstring said so: *"Empty when the change
  is clean **or the tools are unavailable**."* The hygiene gate reads `[]` as clean.
- `quality.py` dropped an unmeasurable dimension from the composite mean. `Cleanliness` is
  never unmeasurable, so a total ruff+mypy miss yields a composite of ~100 — a **perfect
  score for a codebase nobody analysed**.

And `ruff`/`mypy` were declared **dev-group-only** dependencies while being invoked at
runtime. They exist today purely because every install path (`uv sync --all-packages`)
syncs the dev group into the same venv. Under `uv sync --no-dev`, a `make build` wheel, or
any future production image, they vanish — and the gates go silently green.

## Decision

**1. Tool config comes from us, never from the repo.** All host-side tool invocations move
behind one module, `mosaera_core/_hosttools.py`. Every mypy call goes through
`isolated_mypy_args()`, which writes an empty `[mypy]` config to a temp dir and passes
`--config-file` (plus `--cache-dir`, keeping `.mypy_cache` out of the delivered diff).
Repo config discovery is off. ruff's config is pure TOML and cannot execute code, but it
*can* suppress findings, so the ruff calls that **produce findings** also pass `--isolated`.
`ruff format` deliberately does **not**: formatting to the project's own style is
legitimate and is what the hygiene gate is for.

**2. "Unavailable" is a distinct outcome from "clean."** `hygiene_findings` returns a
`HygieneReport(findings, unavailable)`; `QualityScore` carries `unavailable`. A tool that
produced no verdict is named, warned about, and recorded in `RunState.hygiene_unavailable`
— and, since 2026-08-07 (#80), actually **reported to the operator**: `hygiene_status`
carries the same tri-state shape ADR-0076 gives the security scan
(`clean | findings | unavailable | not_applicable | disabled`) and reaches the gate panel.
Until then `hygiene_unavailable` was declared, populated and read by NOBODY — its only
surface was a `print()` to engine stdout — so this paragraph described an intent rather
than a control. It also could not distinguish "no Python changed" from "linted clean";
`not_applicable` is that missing state. Still informational: an unavailable tool does not
block delivery (see "What this deliberately does NOT do")
— never rounded down to an empty findings list. This is ADR-0006's honesty rule applied to
the analysis layer: we do not dress up "we did not check" as "there is nothing wrong".

**3. `ruff` and `mypy` become runtime dependencies of `mosaera-core`**, because they are.

## Consequences

- The host-side RCE is closed, and pinned by a regression test that asserts a hostile
  `plugins =` config does **not** write its sentinel (`test_hygiene_ignores_a_hostile_mypy_plugin_config`).
  A repo can no longer suppress the F-class lint that gates its own delivery
  (`test_hygiene_reports_f_lint_a_repo_config_tries_to_suppress`).
- `hygiene_findings` returns a report object, not a list — a breaking change to one caller
  (`hygiene_node`) and the tests that fake it.
- Two new runtime deps. They are pure-Python and already present in every real install; the
  manifest now tells the truth about what a run needs.

## What this deliberately does NOT do

Tool-unavailability does **not** become a delivery-gate reason. Hygiene findings never
reach the gate (`evaluate_gate`'s `findings_count` is the *security scan*), so a tool miss
degrades the quality bar, not the ship decision — and promoting the deps removes the
real-world occurrence. **Residual:** a mypy crash or timeout mid-run still yields no type
findings for that change; it is now warned and recorded rather than silent, but it does not
block delivery. Revisit if the hygiene gate is ever made load-bearing for the gate itself.

`ruff format` still honors the repo's config, so a hostile repo can still choose a strange
formatting style for its own files. That is cosmetic, not a trust issue, and isolating it
would defeat the gate's purpose.
